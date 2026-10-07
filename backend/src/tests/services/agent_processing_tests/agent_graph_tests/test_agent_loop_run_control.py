"""Notes and pause requests delivered at the agent loop's next model call."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.services.agent_processing.lifecycle.execution_graph import agent_loop_run_control
from api.services.agent_processing.lifecycle.execution_graph import agent_loop_runner as runner
from api.services.agent_processing.lifecycle.execution_graph.agent_loop_run_control import (
    USER_PAUSE_PROMPT,
    UserPauseRequest,
)
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_ledger_capture import (
    ToolLedgerCaptureCoordinator,
)
from api.services.agent_processing.shared import agent_run_control
from api.services.agent_processing.shared.agent_run_control import (
    AgentRunControl,
    discard_run_control,
    existing_run_control,
    run_control_for,
)
from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import CheckpointRequest

TASK_TEXT = "Paint the wall"
TOOL_NAME = "shell_service_execute_command"


class ScriptedChatModel(BaseChatModel):
    responses: list[Any] = Field(default_factory=list)
    calls: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        self.calls.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])


class NoteDuringAnswerModel(ScriptedChatModel):
    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        run_control_for("task-1").enqueue("Also check the ceiling")
        return super()._generate(messages, stop, run_manager, **kwargs)


class TextInput(BaseModel):
    text: str = ""


def _call(call_id: str) -> dict[str, Any]:
    return {"name": TOOL_NAME, "args": {"text": "go"}, "id": call_id, "type": "tool_call"}


def _tool(coroutine: Any) -> StructuredTool:
    return StructuredTool.from_function(
        coroutine=coroutine,
        name=TOOL_NAME,
        description="test tool",
        args_schema=TextInput,
    )


def _state(tools: list[Any], **overrides: Any) -> SimpleNamespace:
    values = {
        "context": {"agent_task_id": "task-1"},
        "available_tools": SimpleNamespace(tools=tools),
        "user_agent_task": TASK_TEXT,
        "agent_messages": None,
        "agent_pending_tool_call_id": None,
        "agent_resume_input": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _request(model: ScriptedChatModel, state: SimpleNamespace) -> runner.AgentRunRequest:
    return runner.AgentRunRequest(
        langchain_llm=model,
        state=state,
        user_profile_context="",
        communication_context_section="",
        custom_instructions_section="",
        selected_skill_section="",
        live_callbacks=None,
        cancel_event=None,
    )


@pytest.fixture(autouse=True)
def runner_seams(monkeypatch):
    async def fake_emit_activity_phase(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def fake_capture_observation(self: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(runner, "format_chain_context", lambda _state: TASK_TEXT)
    monkeypatch.setattr(runner, "get_agent_system_prompt", lambda **_kwargs: "You are Basil.")
    monkeypatch.setattr(runner, "emit_activity_phase", fake_emit_activity_phase)
    monkeypatch.setattr(ToolLedgerCaptureCoordinator, "capture_observation", fake_capture_observation)


@pytest.fixture(autouse=True)
def clean_controls():
    agent_run_control._controls.clear()
    yield
    agent_run_control._controls.clear()


@pytest.fixture
def recorded(monkeypatch):
    entries: list[dict[str, Any]] = []

    async def fake_record(agent_task_id: Any, **kwargs: Any) -> None:
        entries.append({"agent_task_id": agent_task_id, **kwargs})

    monkeypatch.setattr(agent_loop_run_control, "record_user_interaction_entry", fake_record)
    return entries


def _has_note(messages: list[Any], text: str) -> bool:
    return any(isinstance(message, HumanMessage) and text in str(message.content) for message in messages)


@pytest.mark.asyncio
async def test_note_sent_during_a_tool_reaches_the_next_model_call(recorded):
    async def work(text: str = "") -> str:
        assert run_control_for("task-1").enqueue("Use blue paint") is not None
        return "primed"

    model = ScriptedChatModel(responses=[AIMessage(content="", tool_calls=[_call("call-1")]), AIMessage(content="Painted it blue.")])

    run = await runner.run_agent_loop(_request(model, _state([_tool(work)])))

    assert run.agent_output == "Painted it blue."
    assert not _has_note(model.calls[0], "Use blue paint")
    assert _has_note(model.calls[1], "Use blue paint")
    assert [(entry["kind"], entry["status"], entry["prompt"]) for entry in recorded] == [
        ("guidance", "resolved", "Use blue paint")
    ]
    assert recorded[0]["interaction_id"].startswith("note_")
    assert existing_run_control("task-1") is None


@pytest.mark.asyncio
async def test_pause_saves_the_conversation_with_the_pending_note_and_resumes(recorded):
    async def work(text: str = "") -> str:
        control = run_control_for("task-1")
        control.enqueue("Use blue paint")
        assert control.request_pause() is True
        return "primed"

    tools = [_tool(work)]
    first_model = ScriptedChatModel(responses=[AIMessage(content="", tool_calls=[_call("call-1")])])

    with pytest.raises(CheckpointRequest) as paused:
        await runner.run_agent_loop(_request(first_model, _state(tools)))

    assert isinstance(paused.value, UserPauseRequest)
    assert paused.value.is_user_pause is True
    assert paused.value.checkpoint_data["prompt"] == USER_PAUSE_PROMPT
    assert paused.value.checkpoint_data["metadata"] == {"source": "user_pause"}
    assert getattr(paused.value, "basil_tool_call_id", None) is None
    assert len(first_model.calls) == 1
    assert existing_run_control("task-1") is None

    second_model = ScriptedChatModel(responses=[AIMessage(content="Painted it blue.")])
    resumed_state = _state(
        tools,
        agent_messages=paused.value.basil_agent_messages,
        agent_pending_tool_call_id=None,
        agent_resume_input="Continue",
    )

    run = await runner.run_agent_loop(_request(second_model, resumed_state))

    assert _has_note(second_model.calls[0], "Use blue paint")
    assert any(isinstance(message, HumanMessage) and message.content == "Continue" for message in second_model.calls[0])
    assert run.agent_output == "Painted it blue."
    assert [(entry["kind"], entry["status"]) for entry in recorded] == [("guidance", "resolved")]


@pytest.mark.asyncio
async def test_note_left_when_the_run_finishes_is_recorded_as_not_delivered(recorded):
    model = NoteDuringAnswerModel(responses=[AIMessage(content="Done.")])

    run = await runner.run_agent_loop(_request(model, _state([])))

    assert run.agent_output == "Done."
    assert [(entry["kind"], entry["status"], entry["prompt"]) for entry in recorded] == [
        ("guidance", "canceled", "Also check the ceiling")
    ]
    assert existing_run_control("task-1") is None


@pytest.mark.asyncio
async def test_run_without_an_agent_task_id_has_no_run_control(recorded):
    model = ScriptedChatModel(responses=[AIMessage(content="Done.")])

    run = await runner.run_agent_loop(_request(model, _state([], context={})))

    assert run.agent_output == "Done."
    assert agent_run_control._controls == {}
    assert recorded == []


def test_control_refuses_notes_and_pause_when_no_loop_is_attached():
    control = AgentRunControl()

    assert control.enqueue("Hello") is None
    assert control.request_pause() is False

    control.attach()
    assert control.enqueue("Hello") is not None
    assert control.request_pause() is True

    leftovers = control.detach()
    assert [note.text for note in leftovers] == ["Hello"]
    assert control.pause_requested() is False
    assert control.drain() == []


def test_discard_keeps_an_attached_or_replaced_control():
    first = run_control_for("task-1")
    first.attach()
    discard_run_control("task-1", first)
    assert existing_run_control("task-1") is first

    first.detach()
    agent_run_control._controls["task-1"] = AgentRunControl()
    discard_run_control("task-1", first)
    assert existing_run_control("task-1") is not first

    replacement = existing_run_control("task-1")
    discard_run_control("task-1", replacement)
    assert existing_run_control("task-1") is None
