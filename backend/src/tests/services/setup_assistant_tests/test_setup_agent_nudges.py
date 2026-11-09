"""Tests for the setup agent's plain-text reply nudge."""

from __future__ import annotations

from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from api.routes.setup_assistant.models import SetupAssistantPhase
from api.services.setup_assistant.agent_graph.setup_agent_nudges import (
    AGENDA_NUDGE_ADDENDUM,
    PLAIN_REPLY_NUDGE,
    SETUP_NUDGE_MARKER,
    SetupPresentationNudgeMiddleware,
)


def _middleware(phase=SetupAssistantPhase.agent_synthesis, agenda_owed=False, finalize_mode=False):
    return SetupPresentationNudgeMiddleware(phase=phase, agenda_owed=agenda_owed, finalize_mode=finalize_mode)


def _tool_call(name: str) -> dict[str, Any]:
    return {"name": name, "args": {}, "id": f"call-{name}", "type": "tool_call"}


@pytest.mark.asyncio
async def test_plain_text_reply_is_sent_back_once_with_the_reply_removed():
    middleware = _middleware()
    plain = AIMessage(content="Here is my plan.", id="plain-1")
    state = {"messages": [HumanMessage(content="User's latest setup message: hi"), plain]}

    update = await middleware.aafter_model(state, None)

    assert update["jump_to"] == "model"
    removal, nudge = update["messages"]
    assert removal.id == "plain-1"
    assert nudge.content == PLAIN_REPLY_NUDGE
    assert nudge.additional_kwargs[SETUP_NUDGE_MARKER] is True
    assert await middleware.aafter_model(state, None) is None


@pytest.mark.asyncio
async def test_first_turn_nudge_also_asks_for_the_agenda():
    middleware = _middleware(agenda_owed=True)
    state = {"messages": [HumanMessage(content="hi"), AIMessage(content="Plan.", id="p")]}

    update = await middleware.aafter_model(state, None)

    assert update["messages"][-1].content == PLAIN_REPLY_NUDGE + AGENDA_NUDGE_ADDENDUM


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["say", "set_chips"])
async def test_no_nudge_when_say_or_set_chips_was_already_called_this_turn(tool_name):
    state = {
        "messages": [
            HumanMessage(content="hi"),
            AIMessage(content="", tool_calls=[_tool_call(tool_name)], id="a1"),
            ToolMessage(content="ok", tool_call_id=f"call-{tool_name}"),
            AIMessage(content="Done.", id="a2"),
        ]
    }

    assert await _middleware().aafter_model(state, None) is None


@pytest.mark.asyncio
async def test_a_say_call_from_an_earlier_turn_does_not_count():
    state = {
        "messages": [
            HumanMessage(content="earlier turn"),
            AIMessage(content="", tool_calls=[_tool_call("say")], id="old"),
            HumanMessage(content="this turn"),
            AIMessage(content="Plain reply.", id="new"),
        ]
    }

    assert await _middleware().aafter_model(state, None) is not None


@pytest.mark.asyncio
async def test_no_nudge_during_orientation_finalize_empty_text_or_tool_calls():
    plain_state = {"messages": [HumanMessage(content="hi"), AIMessage(content="Plain.", id="p")]}

    assert await _middleware(phase=SetupAssistantPhase.deterministic_discovery).aafter_model(plain_state, None) is None
    assert await _middleware(finalize_mode=True).aafter_model(plain_state, None) is None
    assert await _middleware().aafter_model({"messages": [HumanMessage(content="hi"), AIMessage(content="  ", id="e")]}, None) is None
    calling = AIMessage(content="", tool_calls=[_tool_call("narrate_progress")], id="c")
    assert await _middleware().aafter_model({"messages": [HumanMessage(content="hi"), calling]}, None) is None


@pytest.mark.asyncio
async def test_a_real_agent_resends_the_reply_through_the_tools_after_the_nudge():
    sent: list[str] = []

    @tool
    def say(message: str) -> str:
        """Show a message to the user."""
        sent.append(message)
        return "shown"

    class _ScriptedModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):  # noqa: ANN001
            return self

    model = _ScriptedModel(
        messages=iter(
            [
                AIMessage(content="Plain reply with no tools."),
                AIMessage(content="", tool_calls=[{"name": "say", "args": {"message": "Resent through say."}, "id": "c1", "type": "tool_call"}]),
                AIMessage(content="All done."),
            ]
        )
    )
    agent = create_agent(model, tools=[say], middleware=[_middleware()], checkpointer=False)

    result = await agent.ainvoke({"messages": [HumanMessage(content="User's latest setup message: hello")]})

    assert sent == ["Resent through say."]
    texts = [message.content for message in result["messages"] if isinstance(message, AIMessage)]
    assert "Plain reply with no tools." not in texts
