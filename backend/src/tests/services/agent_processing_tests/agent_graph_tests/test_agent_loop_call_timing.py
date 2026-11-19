"""The agent loop must log how long each model call and each tool call took, so a slow run can be split into model time, preparation time, retry waits, and tool time."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from api.services.agent_processing.lifecycle.execution_graph import agent_loop_model_recovery as recovery_module
from api.services.agent_processing.lifecycle.execution_graph import agent_loop_tool_surface as tool_surface_module
from api.services.agent_processing.lifecycle.execution_graph.agent_loop_model_recovery import (
    AgentRunFlags,
    ModelRecoveryMiddleware,
)
from api.services.agent_processing.lifecycle.execution_graph.agent_loop_tool_surface import ToolSurfaceMiddleware
from api.services.agent_processing.lifecycle.execution_graph.model_errors import TransientModelError


class StubRequest:
    def __init__(self, messages):
        self.messages = list(messages)

    def override(self, **kwargs):
        return StubRequest(kwargs.get("messages", self.messages))


def _middleware():
    middleware = ModelRecoveryMiddleware(AgentRunFlags(), completed_model_calls=1)
    middleware.backoff_base_seconds = 0
    return middleware


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def model_log():
    # The backend's handlers sit on a non-propagating parent logger, so the handler goes on the module logger itself.
    handler = _Capture()
    recovery_module.logger.addHandler(handler)
    previous_level = recovery_module.logger.level
    recovery_module.logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        recovery_module.logger.removeHandler(handler)
        recovery_module.logger.setLevel(previous_level)


@pytest.fixture
def tool_log():
    handler = _Capture()
    tool_surface_module.logger.addHandler(handler)
    previous_level = tool_surface_module.logger.level
    tool_surface_module.logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        tool_surface_module.logger.removeHandler(handler)
        tool_surface_module.logger.setLevel(previous_level)


@pytest.mark.asyncio
async def test_a_model_call_logs_its_phase_timing(model_log):
    async def handler(_request):
        return AIMessage(content="ok")

    await _middleware().awrap_model_call(StubRequest([HumanMessage(content="hi")]), handler)

    lines = [message for message in model_log.messages if "model-call-timing" in message]
    assert len(lines) == 1
    for field in ("model_seconds=", "prep_seconds=", "failed_attempt_seconds=", "retry_wait_seconds=", "prefix="):
        assert field in lines[0]
    assert "attempts=1" in lines[0]
    assert "failed_attempt_seconds=0.00" in lines[0]
    assert "retry_wait_seconds=0.00" in lines[0]


@pytest.mark.asyncio
async def test_a_retried_model_call_reports_the_failed_attempt_and_the_wait(model_log, monkeypatch):
    async def instant_sleep(_seconds):
        return None

    monkeypatch.setattr(recovery_module.asyncio, "sleep", instant_sleep)
    attempts = []

    async def handler(_request):
        attempts.append(1)
        if len(attempts) == 1:
            raise TransientModelError("busy")
        return AIMessage(content="ok")

    await _middleware().awrap_model_call(StubRequest([HumanMessage(content="hi")]), handler)

    lines = [message for message in model_log.messages if "model-call-timing" in message]
    assert len(lines) == 1
    assert "attempts=2" in lines[0]


def _tool_request(name: str = "a_tool", call_id: str = "call-1"):
    return SimpleNamespace(tool_call={"name": name, "id": call_id}, tool=object())


def _tool_middleware() -> ToolSurfaceMiddleware:
    return ToolSurfaceMiddleware(SimpleNamespace(surface_names={"a_tool"}))


@pytest.mark.asyncio
async def test_a_tool_call_logs_its_duration_and_outcome(tool_log):
    async def handler(_request):
        return "done"

    result = await _tool_middleware().awrap_tool_call(_tool_request(), handler)

    assert result == "done"
    lines = [message for message in tool_log.messages if "tool-call-timing" in message]
    assert len(lines) == 1
    assert "tool=a_tool" in lines[0]
    assert "outcome=ok" in lines[0]
    assert "call_id=call-1" in lines[0]
    assert "seconds=" in lines[0]


@pytest.mark.asyncio
async def test_a_failing_tool_call_still_logs_and_still_raises(tool_log):
    async def handler(_request):
        raise RuntimeError("tool blew up")

    with pytest.raises(RuntimeError):
        await _tool_middleware().awrap_tool_call(_tool_request(), handler)

    lines = [message for message in tool_log.messages if "tool-call-timing" in message]
    assert len(lines) == 1
    assert "outcome=error" in lines[0]
