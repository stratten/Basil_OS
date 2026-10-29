"""A lost network connection pauses a run that made progress instead of failing it."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

import api.services.model_usage_service as model_usage_service
from api.services.agent_processing.lifecycle.execution_graph import agent_loop_connection
from api.services.agent_processing.lifecycle.execution_graph import agent_loop_runner as runner
from api.services.agent_processing.lifecycle.execution_graph.agent_execution_core import (
    ModelUnavailableBeforeFirstResponse,
)
from api.services.agent_processing.lifecycle.execution_graph.agent_loop_connection import (
    CONNECTION_LOST_PROMPT,
    CONNECTION_WAIT_AFTER_SLEEP_SECONDS,
    CONNECTION_WAIT_SECONDS,
    RESUME_MODEL_SWITCH_KEY,
    SLEEP_DRIFT_THRESHOLD_SECONDS,
    ConnectionLostPause,
    ConnectionWait,
    is_connectivity_error,
)
from api.services.agent_processing.lifecycle.execution_graph.agent_loop_model_recovery import (
    TRANSIENT_RETRIES,
    AgentRunFlags,
    ModelRecoveryMiddleware,
)
from api.services.agent_processing.lifecycle.execution_graph.model_errors import TransientModelError
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_ledger_capture import (
    ToolLedgerCaptureCoordinator,
)
from api.services.agent_processing.shared import agent_run_control
from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import CheckpointRequest


class FakeClock:
    """Monotonic and wall clocks that only move when the test sleeps, so waits cost no real time."""

    def __init__(self) -> None:
        self.monotonic_now = 1_000.0
        self.wall_now = 1_700_000_000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.monotonic_now

    def wall(self) -> float:
        return self.wall_now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.monotonic_now += seconds
        self.wall_now += seconds

    def machine_sleeps(self, seconds: float) -> None:
        """The Mac sleeps: wall time passes, monotonic time does not."""
        self.wall_now += seconds


class Notices:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def __call__(self, lifecycle_state: str, title: str) -> None:
        self.events.append((lifecycle_state, title))


class FakeDeadline:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def begin_pause(self, reason: str) -> None:
        self.events.append(("begin", reason))

    def end_pause(self, reason: str) -> None:
        self.events.append(("end", reason))


def _connection(clock: FakeClock, notices: Notices | None = None) -> ConnectionWait:
    return ConnectionWait(notify=notices, monotonic=clock.monotonic, wall_clock=clock.wall, sleep=clock.sleep)


class StubRequest:
    def __init__(self, messages):
        self.messages = list(messages)

    def override(self, **kwargs):
        return StubRequest(kwargs.get("messages", self.messages))


def _middleware(clock: FakeClock, *, completed_model_calls=1, notices: Notices | None = None, pause=True):
    middleware = ModelRecoveryMiddleware(
        AgentRunFlags(),
        completed_model_calls=completed_model_calls,
        model_label="Test Model",
        connection=_connection(clock, notices),
        pause_when_connection_lost=pause,
    )
    middleware.backoff_base_seconds = 0
    return middleware


def _request():
    return StubRequest([HumanMessage(content="hi")])


# --- classifying the failure -------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        ConnectionError("Connection error."),
        RuntimeError("[Errno 8] nodename nor servname provided, or not known"),
        RuntimeError("Temporary failure in name resolution"),
        TimeoutError(),
        TransientModelError("network connection was lost"),
    ],
)
def test_network_failures_are_connectivity_errors(error):
    assert is_connectivity_error(error) is True


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("Rate limit reached for requests"),
        TransientModelError("The model is overloaded"),
        RuntimeError("invalid api key"),
        ValueError("No generation chunks were returned"),
    ],
)
def test_busy_or_rejected_services_are_not_connectivity_errors(error):
    assert is_connectivity_error(error) is False


def test_the_cause_chain_decides_when_the_wrapper_is_vague():
    try:
        try:
            raise OSError("[Errno 8] nodename nor servname provided, or not known")
        except OSError as inner:
            raise RuntimeError("Request failed") from inner
    except RuntimeError as wrapped:
        assert is_connectivity_error(wrapped) is True


# --- the wait itself -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_backs_off_and_gives_up_after_the_budget():
    clock = FakeClock()
    wait = _connection(clock)
    error = ConnectionError("Connection error.")

    retries = 0
    while await wait.wait_before_retry(error):
        retries += 1
        assert retries < 100

    assert clock.sleeps[:5] == [2.0, 4.0, 8.0, 16.0, 30.0]
    assert max(clock.sleeps) <= agent_loop_connection.CONNECTION_BACKOFF_CAP_SECONDS
    assert sum(clock.sleeps) == pytest.approx(CONNECTION_WAIT_SECONDS)
    assert wait.waited_seconds() == pytest.approx(CONNECTION_WAIT_SECONDS)


@pytest.mark.asyncio
async def test_wait_is_longer_after_the_machine_slept():
    clock = FakeClock()
    wait = _connection(clock)
    clock.machine_sleeps(SLEEP_DRIFT_THRESHOLD_SECONDS + 1)
    assert wait.slept_since_last_success() is True

    while await wait.wait_before_retry(ConnectionError("Connection error.")):
        pass

    assert sum(clock.sleeps) == pytest.approx(CONNECTION_WAIT_AFTER_SLEEP_SECONDS)


@pytest.mark.asyncio
async def test_a_success_resets_the_sleep_baseline_and_announces_recovery():
    clock = FakeClock()
    notices = Notices()
    wait = _connection(clock, notices)
    clock.machine_sleeps(3_600)
    await wait.wait_before_retry(ConnectionError("Connection error."))

    await wait.restored()

    assert wait.slept_since_last_success() is False
    assert wait.waiting is False
    assert [state for state, _title in notices.events] == ["in_progress", "completed"]


@pytest.mark.asyncio
async def test_the_wait_is_excluded_from_the_run_time_budget(monkeypatch):
    deadline = FakeDeadline()
    monkeypatch.setattr(agent_loop_connection, "current_pausable_deadline", lambda: deadline)
    clock = FakeClock()
    wait = _connection(clock)

    await wait.wait_before_retry(ConnectionError("Connection error."))
    await wait.wait_before_retry(ConnectionError("Connection error."))
    assert deadline.events == [("begin", "model_connection_wait")]

    wait.close()
    wait.close()
    assert deadline.events == [("begin", "model_connection_wait"), ("end", "model_connection_wait")]


# --- the model call --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_brief_outage_is_ridden_out_without_pausing():
    clock = FakeClock()
    notices = Notices()
    attempts: list[int] = []

    async def handler(_request):
        attempts.append(1)
        if len(attempts) <= 4:
            raise ConnectionError("Connection error.")
        return AIMessage(content="ok")

    response = await _middleware(clock, notices=notices).awrap_model_call(_request(), handler)

    assert response.content == "ok"
    assert len(attempts) == 5
    assert len(clock.sleeps) == 4
    assert [state for state, _title in notices.events] == ["in_progress", "completed"]


@pytest.mark.asyncio
async def test_a_long_outage_pauses_the_run_with_the_original_error():
    clock = FakeClock()
    notices = Notices()
    failure = ConnectionError("Connection error.")

    async def handler(_request):
        raise failure

    with pytest.raises(ConnectionLostPause) as paused:
        await _middleware(clock, notices=notices).awrap_model_call(_request(), handler)

    assert isinstance(paused.value, CheckpointRequest)
    assert paused.value.original_error is failure
    assert paused.value.model_label == "Test Model"
    assert paused.value.waited_seconds == pytest.approx(CONNECTION_WAIT_SECONDS)
    assert paused.value.checkpoint_data["prompt"] == CONNECTION_LOST_PROMPT
    assert paused.value.checkpoint_data["metadata"] == {"source": "connection_lost"}
    assert getattr(paused.value, "is_user_pause", False) is False
    assert [state for state, _title in notices.events] == ["in_progress", "failed"]


@pytest.mark.asyncio
async def test_a_busy_service_pauses_after_the_short_retries_without_the_long_wait():
    clock = FakeClock()
    attempts: list[int] = []

    async def handler(_request):
        attempts.append(1)
        raise TransientModelError("The model is overloaded")

    with pytest.raises(ConnectionLostPause):
        await _middleware(clock).awrap_model_call(_request(), handler)

    assert len(attempts) == TRANSIENT_RETRIES + 1
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_before_any_model_response_the_local_fallback_path_is_kept(monkeypatch):
    monkeypatch.setattr(model_usage_service, "is_model_unreachable_error", lambda _error: True)
    clock = FakeClock()

    async def handler(_request):
        raise ConnectionError("Connection error.")

    with pytest.raises(ModelUnavailableBeforeFirstResponse):
        await _middleware(clock, completed_model_calls=0).awrap_model_call(_request(), handler)

    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_other_failures_are_not_turned_into_a_pause():
    clock = FakeClock()

    async def handler(_request):
        raise RuntimeError("invalid api key")

    with pytest.raises(RuntimeError, match="invalid api key"):
        await _middleware(clock).awrap_model_call(_request(), handler)


@pytest.mark.asyncio
async def test_without_the_pause_option_the_original_error_still_surfaces():
    clock = FakeClock()

    attempts: list[int] = []

    async def handler(_request):
        attempts.append(1)
        raise ConnectionError("Connection error.")

    with pytest.raises(ConnectionError):
        await _middleware(clock, pause=False).awrap_model_call(_request(), handler)

    assert len(attempts) == TRANSIENT_RETRIES + 1
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_cancellation_ends_the_budget_pause(monkeypatch):
    deadline = FakeDeadline()
    monkeypatch.setattr(agent_loop_connection, "current_pausable_deadline", lambda: deadline)
    clock = FakeClock()
    middleware = _middleware(clock)

    async def canceling_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError()

    middleware.connection._sleep = canceling_sleep

    async def handler(_request):
        raise ConnectionError("Connection error.")

    with pytest.raises(asyncio.CancelledError):
        await middleware.awrap_model_call(_request(), handler)

    assert deadline.events == [("begin", "model_connection_wait"), ("end", "model_connection_wait")]


# --- the whole loop: pause with progress saved, then resume -----------------------------------------

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
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return ChatResult(generations=[ChatGeneration(message=response)])


class TextInput(BaseModel):
    text: str = ""


def _tool() -> StructuredTool:
    async def work(text: str = "") -> str:
        return "wall primed"

    return StructuredTool.from_function(coroutine=work, name=TOOL_NAME, description="test tool", args_schema=TextInput)


def _state(**overrides: Any) -> SimpleNamespace:
    values = {
        "context": {"agent_task_id": "task-1"},
        "available_tools": SimpleNamespace(tools=[_tool()]),
        "user_agent_task": "Paint the wall",
        "agent_messages": None,
        "agent_pending_tool_call_id": None,
        "agent_resume_input": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _run_request(model: ScriptedChatModel, state: SimpleNamespace) -> runner.AgentRunRequest:
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


@pytest.fixture
def loop_seams(monkeypatch):
    phases: list[tuple[str, str]] = []

    async def fake_emit_activity_phase(_state: Any, *, phase: str, lifecycle_state: str, **_kwargs: Any) -> None:
        phases.append((phase, lifecycle_state))

    async def fake_capture_observation(self: Any, **_kwargs: Any) -> None:
        return None

    clock = FakeClock()
    agent_run_control._controls.clear()
    monkeypatch.setattr(runner, "format_chain_context", lambda _state: "Paint the wall")
    monkeypatch.setattr(runner, "get_agent_system_prompt", lambda **_kwargs: "You are Basil.")
    monkeypatch.setattr(runner, "emit_activity_phase", fake_emit_activity_phase)
    monkeypatch.setattr(ToolLedgerCaptureCoordinator, "capture_observation", fake_capture_observation)
    monkeypatch.setattr(
        runner,
        "ConnectionWait",
        lambda notify=None: ConnectionWait(
            notify=notify, monotonic=clock.monotonic, wall_clock=clock.wall, sleep=clock.sleep
        ),
    )
    yield SimpleNamespace(phases=phases, clock=clock)
    agent_run_control._controls.clear()


def _tool_call(call_id: str) -> dict[str, Any]:
    return {"name": TOOL_NAME, "args": {"text": "go"}, "id": call_id, "type": "tool_call"}


@pytest.mark.asyncio
async def test_losing_the_connection_after_progress_pauses_with_the_conversation_saved(loop_seams):
    model = ScriptedChatModel(
        responses=[AIMessage(content="", tool_calls=[_tool_call("call-1")]), *[ConnectionError("Connection error.")] * 40]
    )

    with pytest.raises(ConnectionLostPause) as paused:
        await runner.run_agent_loop(_run_request(model, _state()))

    saved = paused.value.basil_agent_messages
    assert [item["type"] for item in saved] == ["human", "ai", "tool"]
    assert saved[2]["data"]["content"] == "wall primed"
    assert paused.value.basil_system_prompt_text == "You are Basil."
    assert ("model_connection", "in_progress") in loop_seams.phases
    assert ("model_connection", "failed") in loop_seams.phases
    assert sum(loop_seams.clock.sleeps) == pytest.approx(CONNECTION_WAIT_SECONDS)

    resumed_model = ScriptedChatModel(responses=[AIMessage(content="Painted it.")])
    resumed_state = _state(agent_messages=saved, agent_resume_input="The connection is back. Continue.")

    run = await runner.run_agent_loop(_run_request(resumed_model, resumed_state))

    replayed = resumed_model.calls[0]
    assert any(isinstance(message, ToolMessage) and message.content == "wall primed" for message in replayed)
    assert any(
        isinstance(message, HumanMessage) and message.content == "The connection is back. Continue."
        for message in replayed
    )
    assert run.agent_output == "Painted it."


@pytest.mark.asyncio
async def test_a_connection_that_returns_mid_run_never_pauses(loop_seams):
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("call-1")]),
            ConnectionError("Connection error."),
            ConnectionError("Connection error."),
            AIMessage(content="Painted it."),
        ]
    )

    run = await runner.run_agent_loop(_run_request(model, _state()))

    assert run.agent_output == "Painted it."
    assert len(loop_seams.clock.sleeps) == 2
    assert ("model_connection", "completed") in loop_seams.phases


def test_switching_models_continues_the_conversation_in_plain_provider_neutral_form():
    saved_with_provider_detail = [
        HumanMessage(content="Paint the wall"),
        AIMessage(
            content=[{"type": "thinking", "thinking": "private", "signature": "sig"}, {"type": "text", "text": "Starting."}],
            tool_calls=[_tool_call("call-1")],
        ),
        ToolMessage(content="wall primed", tool_call_id="call-1", name=TOOL_NAME),
    ]
    serialized = runner.serialize_agent_messages(saved_with_provider_detail)

    same_model = runner._initial_messages(
        _state(agent_messages=serialized, agent_resume_input="Continue", context={}), None, None
    )
    switched_context = {RESUME_MODEL_SWITCH_KEY: True}
    switched = runner._initial_messages(
        _state(agent_messages=serialized, agent_resume_input="Continue", context=switched_context), None, None
    )

    assert isinstance(same_model[1].content, list)
    assert switched[1].content == "Starting."
    assert switched[1].tool_calls[0]["id"] == "call-1"
    assert switched[-1].content == "Continue"
    assert RESUME_MODEL_SWITCH_KEY not in switched_context
