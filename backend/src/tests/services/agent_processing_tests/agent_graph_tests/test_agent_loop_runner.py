"""End-to-end tests for the inner agent loop runner with a scripted chat model."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.services.agent_processing.lifecycle.execution_graph import agent_loop_runner as runner
from api.services.agent_processing.lifecycle.execution_graph.agent_conversation_thread import StoredConversationThread
from api.services.agent_processing.lifecycle.execution_graph.agent_loop_nudges import SCRIPTING_FLOOR_PROMPT
from api.services.agent_processing.lifecycle.execution_graph.conversation_turns import is_turn_input, mark_turn_input
from api.services.agent_processing.lifecycle.planning.agent_context_assembler import CONVERSATION_THREAD_SEEDED_KEY
from api.services.agent_processing.lifecycle.execution_graph.execution_limits import active_time_limit_message
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_call_repetition_guard import (
    RepeatedInvalidToolCallStop,
)
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_ledger_capture import (
    ToolLedgerCaptureCoordinator,
)
from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import CheckpointRequest

TASK_TEXT = "Paint the wall"


class ScriptedChatModel(BaseChatModel):
    responses: list[Any] = Field(default_factory=list)
    calls: list[Any] = Field(default_factory=list)
    bound_tool_names: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        self.bound_tool_names.append(sorted(str(getattr(tool, "name", "")) for tool in tools))
        return self

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        self.calls.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])


class TextInput(BaseModel):
    text: str = ""


def _call(name: str, call_id: str, **args: Any) -> dict[str, Any]:
    return {"name": name, "args": dict(args), "id": call_id, "type": "tool_call"}


def _tool(name: str, coroutine: Any = None) -> StructuredTool:
    async def _default(text: str = "") -> str:
        return f"{name} ok"

    return StructuredTool.from_function(
        coroutine=coroutine or _default,
        name=name,
        description=f"{name} test tool",
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


def _request(model: ScriptedChatModel, state: SimpleNamespace, cancel_event: Any = None) -> runner.AgentRunRequest:
    return runner.AgentRunRequest(
        langchain_llm=model,
        state=state,
        user_profile_context="",
        communication_context_section="",
        custom_instructions_section="",
        selected_skill_section="",
        live_callbacks=None,
        cancel_event=cancel_event,
    )


@pytest.fixture(autouse=True)
def runner_seams(monkeypatch):
    formatted_states: list[Any] = []

    def fake_format_chain_context(state: Any) -> str:
        formatted_states.append(state)
        return TASK_TEXT

    async def fake_emit_activity_phase(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def fake_capture_observation(self: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(runner, "format_chain_context", fake_format_chain_context)
    monkeypatch.setattr(runner, "get_agent_system_prompt", lambda **_kwargs: "You are Basil.")
    monkeypatch.setattr(runner, "emit_activity_phase", fake_emit_activity_phase)
    monkeypatch.setattr(ToolLedgerCaptureCoordinator, "capture_observation", fake_capture_observation)
    return formatted_states


@pytest.mark.asyncio
async def test_load_family_grows_surface_within_one_run():
    tools = [_tool("browser_inspect"), _tool("request_user_input")]
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_call("load_tool_family", "call-load", family_names=["browser"], reason="page")]),
            AIMessage(content="", tool_calls=[_call("browser_inspect", "call-inspect", text="body")]),
            AIMessage(content="The page is loaded."),
        ]
    )
    state = _state(tools)

    run = await runner.run_agent_loop(_request(model, state))

    assert "browser_inspect" not in model.bound_tool_names[0]
    assert "browser_inspect" in model.bound_tool_names[1]
    assert len(model.calls) == 3
    assert run.agent_output == "The page is loaded."
    assert run.loaded_families == ["browser"]
    assert [action.tool for action, _observation in run.intermediate_steps] == ["load_tool_family", "browser_inspect"]
    assert run.intermediate_steps[1][1] == "browser_inspect ok"
    assert state.context["loaded_tool_families"] == ["browser"]
    assert run.final_input == TASK_TEXT
    assert "browser_inspect" in {tool.name for tool in run.surface_tools}


@pytest.mark.asyncio
async def test_off_surface_call_is_rejected_then_family_is_loaded():
    tools = [_tool("browser_inspect"), _tool("request_user_input")]
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_call("browser_inspect", "call-early", text="body")]),
            AIMessage(content="", tool_calls=[_call("browser_inspect", "call-late", text="body")]),
            AIMessage(content="Inspected."),
        ]
    )

    run = await runner.run_agent_loop(_request(model, _state(tools)))

    rejected = next(message for message in model.calls[1] if isinstance(message, ToolMessage) and message.tool_call_id == "call-early")
    assert "browser_inspect is not a valid tool" in rejected.content
    assert "browser_inspect" in model.bound_tool_names[1]
    assert run.intermediate_steps[-1][1] == "browser_inspect ok"
    assert run.agent_output == "Inspected."


@pytest.mark.asyncio
async def test_checkpoint_pause_attaches_messages_and_resume_answers_call(runner_seams):
    async def ask(text: str = "") -> str:
        raise CheckpointRequest({"prompt": "Which color?"})

    tools = [_tool("request_user_input", ask)]
    first_model = ScriptedChatModel(
        responses=[AIMessage(content="Asking.", tool_calls=[_call("request_user_input", "call-ask", text="Which color?")])]
    )

    with pytest.raises(CheckpointRequest) as paused:
        await runner.run_agent_loop(_request(first_model, _state(tools)))

    assert paused.value.basil_tool_call_id == "call-ask"
    assert isinstance(paused.value.basil_agent_messages, list)
    assert len(runner_seams) == 1

    second_model = ScriptedChatModel(responses=[AIMessage(content="Painted it blue.")])
    resumed_state = _state(
        tools,
        agent_messages=paused.value.basil_agent_messages,
        agent_pending_tool_call_id=paused.value.basil_tool_call_id,
        agent_resume_input="Blue",
    )

    run = await runner.run_agent_loop(_request(second_model, resumed_state))

    answered = [message for message in second_model.calls[0] if isinstance(message, ToolMessage)]
    assert [(message.tool_call_id, message.content) for message in answered] == [("call-ask", "Blue")]
    assert run.agent_output == "Painted it blue."
    assert run.final_input == TASK_TEXT
    assert len(runner_seams) == 1


class LoopRecordingCallback(AsyncCallbackHandler):
    def __init__(self) -> None:
        self.tool_start_loops: list[Any] = []

    async def on_tool_start(self, serialized: Any, input_str: str, **kwargs: Any) -> None:
        self.tool_start_loops.append(asyncio.get_running_loop())


def _sync_tool(name: str, func: Any) -> StructuredTool:
    return StructuredTool.from_function(func=func, name=name, description=f"{name} test tool", args_schema=TextInput)


@pytest.mark.asyncio
async def test_sync_checkpoint_tool_pauses_with_callbacks_on_the_running_loop():
    def ask(text: str = "") -> str:
        raise CheckpointRequest({"prompt": text})

    recorder = LoopRecordingCallback()
    model = ScriptedChatModel(
        responses=[AIMessage(content="Asking.", tool_calls=[_call("request_user_input", "call-ask", text="First or third?")])]
    )
    request = replace(_request(model, _state([_sync_tool("request_user_input", ask)])), live_callbacks=[recorder])

    with pytest.raises(CheckpointRequest) as paused:
        await asyncio.wait_for(runner.run_agent_loop(request), timeout=10)

    assert paused.value.basil_tool_call_id == "call-ask"
    assert recorder.tool_start_loops == [asyncio.get_running_loop()]


@pytest.mark.asyncio
async def test_sync_tool_result_returns_through_the_guard():
    recorder = LoopRecordingCallback()
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_call("request_user_input", "call-sync", text="hello")]),
            AIMessage(content="Done."),
        ]
    )
    request = replace(
        _request(model, _state([_sync_tool("request_user_input", lambda text="": f"echo {text}")])),
        live_callbacks=[recorder],
    )

    run = await asyncio.wait_for(runner.run_agent_loop(request), timeout=10)

    answered = [message for message in model.calls[1] if isinstance(message, ToolMessage)]
    assert [(message.tool_call_id, message.content) for message in answered] == [("call-sync", "echo hello")]
    assert recorder.tool_start_loops == [asyncio.get_running_loop()]
    assert run.agent_output == "Done."


@pytest.mark.asyncio
async def test_resume_without_saved_messages_starts_fresh(runner_seams):
    model = ScriptedChatModel(responses=[AIMessage(content="Starting over.")])
    state = _state([_tool("request_user_input")], agent_messages=None, agent_resume_input="Blue")

    run = await runner.run_agent_loop(_request(model, state))

    assert run.agent_output == "Starting over."
    assert len(runner_seams) == 1
    assert isinstance(model.calls[0][-1], HumanMessage)


@pytest.mark.asyncio
async def test_active_time_budget_stops_the_run(monkeypatch):
    async def slow(text: str = "") -> str:
        await asyncio.sleep(5)
        return "too late"

    monkeypatch.setattr(runner, "AGENT_RUN_MAX_ACTIVE_SECONDS", 0.2)
    tools = [_tool("shell_service_execute_command", slow)]
    model = ScriptedChatModel(
        responses=[AIMessage(content="", tool_calls=[_call("shell_service_execute_command", "call-slow", text="sleep")])]
    )

    run = await runner.run_agent_loop(_request(model, _state(tools)))

    assert run.result["execution_timed_out"] is True
    assert run.result["pass_budget_exhausted"]["budget_seconds"] == 0.2
    assert run.agent_output == active_time_limit_message(0.2)


@pytest.mark.asyncio
async def test_repetition_guard_stop_returns_guard_output():
    async def stuck(text: str = "") -> str:
        raise RepeatedInvalidToolCallStop(
            tool_name="shell_service_execute_command",
            signature="sig",
            repeat_count=6,
            diagnostic={"tool_name": "shell_service_execute_command", "invalid_kind": "missing_required_argument"},
            agent_output="Stopped: repeated invalid calls.",
        )

    tools = [_tool("shell_service_execute_command", stuck)]
    model = ScriptedChatModel(
        responses=[AIMessage(content="", tool_calls=[_call("shell_service_execute_command", "call-stuck", text="x")])]
    )

    run = await runner.run_agent_loop(_request(model, _state(tools)))

    assert run.agent_output == "Stopped: repeated invalid calls."
    assert run.result["tool_repetition_guard_stop"]["invalid_kind"] == "missing_required_argument"


@pytest.mark.asyncio
async def test_scripting_floor_nudges_once_after_off_surface_call():
    tools = [
        _tool("browser_inspect"),
        _tool("applescript_service_execute_applescript"),
        _tool("request_user_input"),
    ]
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_call("browser_inspect", "call-browser", text="body")]),
            AIMessage(content="I could not do it."),
            AIMessage(content="Done with a script."),
        ]
    )

    run = await runner.run_agent_loop(_request(model, _state(tools)))

    assert len(model.calls) == 3
    floor_messages = [
        message for message in model.calls[2] if isinstance(message, HumanMessage) and message.content == SCRIPTING_FLOOR_PROMPT
    ]
    assert len(floor_messages) == 1
    assert run.agent_output == "Done with a script."


@pytest.mark.asyncio
async def test_cancel_event_stops_a_running_tool():
    cancel_event = asyncio.Event()
    tool_finished = asyncio.Event()

    async def slow(text: str = "") -> str:
        cancel_event.set()
        await asyncio.sleep(5)
        tool_finished.set()
        return "too late"

    tools = [_tool("shell_service_execute_command", slow)]
    model = ScriptedChatModel(
        responses=[AIMessage(content="", tool_calls=[_call("shell_service_execute_command", "call-slow", text="sleep")])]
    )

    with pytest.raises(asyncio.CancelledError):
        await runner.run_agent_loop(_request(model, _state(tools), cancel_event=cancel_event))
    assert not tool_finished.is_set()


class ToolRunStoppingCallback(AsyncCallbackHandler):
    def __init__(self) -> None:
        self.started: list[str] = []
        self.stop_calls = 0

    async def on_tool_start(self, serialized: Any, input_str: str, **kwargs: Any) -> None:
        self.started.append(serialized.get("name", ""))

    def stop_active_tool_runs(self) -> None:
        self.stop_calls += 1


@pytest.mark.asyncio
async def test_cancel_stops_live_tool_runs_left_without_an_end_callback():
    cancel_event = asyncio.Event()

    async def waiting_for_approval(text: str = "") -> str:
        cancel_event.set()
        await asyncio.sleep(5)
        return "too late"

    recorder = ToolRunStoppingCallback()
    tools = [_tool("shell_service_execute_command", waiting_for_approval)]
    model = ScriptedChatModel(
        responses=[AIMessage(content="", tool_calls=[_call("shell_service_execute_command", "call-wait", text="ls")])]
    )
    request = replace(_request(model, _state(tools), cancel_event=cancel_event), live_callbacks=[recorder])

    with pytest.raises(asyncio.CancelledError):
        await runner.run_agent_loop(request)

    assert recorder.started == ["shell_service_execute_command"]
    assert recorder.stop_calls == 1


@pytest.mark.asyncio
async def test_finalizer_recovery_agent_returns_executor_shape():
    async def finalize(text: str = "") -> str:
        return '{"status": "completed"}'

    finalizer = StructuredTool.from_function(
        coroutine=finalize,
        name="finalize_agent_task_result",
        description="finalize",
        args_schema=TextInput,
        return_direct=True,
    )
    model = ScriptedChatModel(
        responses=[AIMessage(content="", tool_calls=[_call("finalize_agent_task_result", "call-final", text="done")])]
    )
    agent = runner.FinalizerRecoveryAgent(
        langchain_llm=model,
        tools=[finalizer],
        system_prompt_text="You are Basil.",
        cancel_event=None,
        budget_seconds=30.0,
    )

    result = await agent.ainvoke({"input": "Finalize now."})

    assert result["output"] == '{"status": "completed"}'
    assert [action.tool for action, _observation in result["intermediate_steps"]] == ["finalize_agent_task_result"]
    assert len(model.calls) == 1


def _prior_turn(tool_name: str, request: str, answer: str) -> list[Any]:
    return [
        mark_turn_input(HumanMessage(content=f"Current request: {request}")),
        AIMessage(content="", tool_calls=[_call(tool_name, "old-call", text="notes")]),
        ToolMessage(content=f"{tool_name} ok", tool_call_id="old-call", name=tool_name),
        AIMessage(content=answer),
    ]


@pytest.mark.asyncio
async def test_prior_thread_seeds_the_conversation_and_scopes_the_result():
    prior = _prior_turn("browser_inspect", "Read the notes", "The code word is amber.")
    model = ScriptedChatModel(responses=[AIMessage(content="It was amber.")])
    state = _state([_tool("request_user_input")])
    request = replace(_request(model, state), prior_thread=StoredConversationThread("task-0", "scripted", "", prior))

    run = await runner.run_agent_loop(request)

    sent = model.calls[0]
    assert [message.content for message in sent[1:5]] == [message.content for message in prior]
    assert is_turn_input(sent[-1])
    assert sent[-1].content == TASK_TEXT
    assert state.context[CONVERSATION_THREAD_SEEDED_KEY] is True
    assert run.intermediate_steps == []
    assert run.agent_output == "It was amber."
    assert run.final_input.endswith(TASK_TEXT)
    assert "User: Read the notes" in run.final_input
    assert len(run.messages) == len(prior) + 2


@pytest.mark.asyncio
async def test_without_a_prior_thread_the_run_is_unchanged():
    model = ScriptedChatModel(responses=[AIMessage(content="Done.")])
    state = _state([_tool("request_user_input")])

    run = await runner.run_agent_loop(_request(model, state))

    assert CONVERSATION_THREAD_SEEDED_KEY not in state.context
    assert run.final_input == TASK_TEXT
    assert len(model.calls[0]) == 2
    assert is_turn_input(model.calls[0][1])


@pytest.mark.asyncio
async def test_scripting_floor_ignores_tool_calls_from_earlier_turns():
    tools = [
        _tool("browser_inspect"),
        _tool("applescript_service_execute_applescript"),
        _tool("request_user_input"),
    ]
    prior = _prior_turn("browser_inspect", "Inspect the page", "I could not do it.")
    model = ScriptedChatModel(responses=[AIMessage(content="Answered from memory.")])
    request = replace(_request(model, _state(tools)), prior_thread=StoredConversationThread("task-0", "scripted", "", prior))

    run = await runner.run_agent_loop(request)

    assert len(model.calls) == 1
    assert run.agent_output == "Answered from memory."
