"""execute_with_token_retry recovers per failure kind and enforces a pause-aware pass budget."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.services.agent_processing.lifecycle.execution_graph.agent_execution_core import (
    ModelUnavailableBeforeFirstResponse,
    execute_with_token_retry,
)
from api.services.agent_processing.lifecycle.execution_graph.model_errors import TransientModelError
from api.services.agent_processing.lifecycle.execution_graph.workflow_deadline import WorkflowDeadline
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)

LONG_INPUT = ("padding " * 10000) + "Current request: do the actual task now."


class _ScriptedExecutor:
    """Raises each scripted exception in turn, then returns a fixed result."""

    def __init__(self, failures: list, result: Any = None) -> None:
        self.failures = list(failures)
        self.result = result if result is not None else {"output": "done", "intermediate_steps": []}
        self.calls = 0

    async def ainvoke(self, payload: dict, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return self.result


def _handler(completed_llm_calls: int) -> MagicMock:
    handler = MagicMock()
    handler.completed_llm_calls = completed_llm_calls
    return handler


@pytest.mark.asyncio
async def test_auth_proxy_value_error_overflow_reaches_trim_recovery():
    executor = _ScriptedExecutor([
        ValueError("Auth service error (400): prompt is too long: 203619 tokens > 200000 maximum"),
    ])

    result, final_input = await execute_with_token_retry(executor, LONG_INPUT, callbacks=[])

    assert result["output"] == "done"
    assert executor.calls == 2
    assert len(final_input) < len(LONG_INPUT)
    assert final_input.endswith("do the actual task now.")


@pytest.mark.asyncio
async def test_overflow_without_token_counts_trims_a_quarter_of_the_input():
    executor = _ScriptedExecutor([ValueError('Auth service error (400): {"code": "context_length_exceeded"}')])

    result, final_input = await execute_with_token_retry(executor, LONG_INPUT, callbacks=[])

    assert result["output"] == "done"
    assert len(final_input) < len(LONG_INPUT)
    assert final_input.endswith("do the actual task now.")


@pytest.mark.asyncio
async def test_transient_retries_do_not_consume_trim_attempts(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    overflow = RuntimeError("prompt is too long: 203619 tokens > 200000 maximum")
    executor = _ScriptedExecutor([ConnectionError("connection reset"), overflow, overflow])

    result, _ = await execute_with_token_retry(executor, LONG_INPUT, callbacks=[], max_trim_retries=2)

    assert result["output"] == "done"
    assert executor.calls == 4


@pytest.mark.asyncio
async def test_typed_transient_error_does_not_restart_the_pass_after_progress():
    error = TransientModelError("Auth service error (503): busy")
    executor = _ScriptedExecutor([error, error, error])

    with pytest.raises(TransientModelError):
        await execute_with_token_retry(executor, "do it", callbacks=[_handler(1)])

    assert executor.calls == 1


@pytest.mark.asyncio
async def test_typed_transient_error_before_first_response_allows_local_fallback():
    executor = _ScriptedExecutor([TransientModelError("Auth service connection failed: connection refused")])

    with pytest.raises(ModelUnavailableBeforeFirstResponse):
        await execute_with_token_retry(executor, "do it", callbacks=[_handler(0)])

    assert executor.calls == 1


@pytest.mark.asyncio
async def test_error_after_empty_generation_retry_is_still_classified():
    executor = _ScriptedExecutor([
        ValueError("No generation chunks were returned"),
        RuntimeError("prompt is too long: 203619 tokens > 200000 maximum"),
    ])

    result, _ = await execute_with_token_retry(executor, LONG_INPUT, callbacks=[])

    assert result["output"] == "done"
    assert executor.calls == 3


@pytest.mark.asyncio
async def test_pass_budget_exhaustion_cancels_the_pass_and_returns_timed_out_result():
    invoke_stopped = asyncio.Event()

    class _BlockingExecutor:
        async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
            try:
                await asyncio.Event().wait()
            finally:
                invoke_stopped.set()

    result, _ = await asyncio.wait_for(
        execute_with_token_retry(_BlockingExecutor(), "do it", callbacks=[], pass_budget_seconds=0.05),
        timeout=5,
    )

    assert invoke_stopped.is_set()
    assert result["execution_timed_out"] is True
    assert result["pass_budget_exhausted"]["budget_seconds"] == pytest.approx(0.05)
    assert result["intermediate_steps"] == []
    assert "Time spent waiting for approvals or your input was not counted." in result["output"]


class _SlowExecutor:
    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(0.3)
        return {"output": "done", "intermediate_steps": []}


@pytest.mark.asyncio
async def test_paused_time_on_explicit_deadline_is_not_charged_to_the_pass():
    deadline = WorkflowDeadline.start(total_seconds=100, finalization_reserve_seconds=0)
    deadline.begin_pause("execution_approval")
    try:
        result, _ = await execute_with_token_retry(
            _SlowExecutor(), "do it", callbacks=[], pass_budget_seconds=0.1, workflow_deadline=deadline
        )
    finally:
        deadline.end_pause("execution_approval")

    assert result["output"] == "done"


@pytest.mark.asyncio
async def test_paused_time_on_context_deadline_is_not_charged_to_the_pass():
    deadline = WorkflowDeadline.start(total_seconds=100, finalization_reserve_seconds=0)
    token = set_current_agent_context({"agent_task_id": "task-budget", "_workflow_deadline": deadline})
    deadline.begin_pause("command_input")
    try:
        result, _ = await execute_with_token_retry(
            _SlowExecutor(), "do it", callbacks=[], pass_budget_seconds=0.1
        )
    finally:
        deadline.end_pause("command_input")
        reset_current_agent_context(token)

    assert result["output"] == "done"


@pytest.mark.asyncio
async def test_unpaused_slow_pass_still_hits_the_budget():
    result, _ = await execute_with_token_retry(_SlowExecutor(), "do it", callbacks=[], pass_budget_seconds=0.1)

    assert result["execution_timed_out"] is True
