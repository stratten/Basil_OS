"""Watchdog verdicts must match what the system can actually reconcile."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import api.services.agent_processing.lifecycle.execution_graph.tool_run_watchdog as watchdog_module
from api.services.agent_processing.lifecycle.execution_graph.agent_progress_system import LiveProgressCallbackHandler
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.models import BaseModel
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_execution import create_tool_function
from api.services.agent_processing.lifecycle.execution_graph.tool_run_watchdog import (
    ActiveToolRunRegistry,
    get_tool_run_registry,
    record_tool_progress,
)
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)

SHELL_TOOL = "shell_service_execute_command"


class EmptyInput(BaseModel):
    pass


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Notifier:
    def __init__(self) -> None:
        self.added = []
        self.updated = []
        self.progress = []
        self.details = []

    async def send_dynamic_step_added(self, **kwargs):
        self.added.append(kwargs)
        return "step_1"

    async def send_dynamic_step_updated(self, **kwargs):
        self.updated.append(kwargs)

    async def send_agent_progress_update(self, **kwargs):
        self.progress.append(kwargs)

    async def send_step_detail_update(self, **kwargs):
        self.details.append(kwargs)


class _HangingEngine:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.service_canceled = asyncio.Event()

    async def execute_service_method(self, service_name, method_name, parameters):
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.service_canceled.set()
            raise


def _register(registry, run_id: str, agent_task_id: str, tool_name: str = SHELL_TOOL):
    return registry.register(
        run_id=run_id,
        agent_task_id=agent_task_id,
        step_id=f"step-{run_id}",
        tool_name=tool_name,
        description="Running shell command",
    )


def _hanging_tool(engine: _HangingEngine, tool_error_log: list):
    factory = SimpleNamespace(
        service_execution_engine=engine,
        max_tool_output_chars=20_000,
        max_context_tokens=200_000,
        tool_error_log=tool_error_log,
    )
    return create_tool_function(factory, "fake_service_hang", "Hang", EmptyInput, "fake_service", "hang", {})


def test_wait_statuses_are_excluded_from_active_time(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(watchdog_module, "_monotonic", clock)
    registry = ActiveToolRunRegistry()
    run = _register(registry, "r1", "t1")

    clock.now += 10
    run.mark("input_waiting", "input_requested")
    clock.now += 500
    assessment = registry.assess("r1")
    assert assessment.status == "input_waiting"
    assert assessment.should_continue is True
    assert run.active_elapsed_seconds == pytest.approx(10)

    run.mark("service_running", "input_resolved")
    clock.now += 5
    assert run.active_elapsed_seconds == pytest.approx(15)
    assert run.elapsed_seconds == pytest.approx(515)


def test_waiting_status_reports_deliberate_wait(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(watchdog_module, "_monotonic", clock)
    registry = ActiveToolRunRegistry()
    run = _register(registry, "r-wait", "t-wait", tool_name="wait_before_checking_again")
    run.mark("waiting", "wait_started")
    clock.now += 10_000

    assessment = registry.assess("r-wait")

    assert assessment.status == "waiting"
    assert assessment.should_continue is True


def test_quiet_run_without_declared_timeout_keeps_running(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(watchdog_module, "_monotonic", clock)
    registry = ActiveToolRunRegistry()
    _register(registry, "r2", "t2", tool_name="fake_service_do_work")
    clock.now += 10_000

    assessment = registry.assess("r2")

    assert assessment.should_continue is True
    assert assessment.status == "quiet"
    assert "no progress reported for 166m" in assessment.message


def test_declared_timeout_overrun_is_stale_only_with_cancel_handle(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(watchdog_module, "_monotonic", clock)
    registry = ActiveToolRunRegistry()
    run = _register(registry, "r3", "t3")
    run.mark("service_running", "process_started", timeout_seconds=60.0)

    clock.now += 149
    assert registry.assess("r3").should_continue is True

    clock.now += 2
    unhandled = registry.assess("r3")
    assert unhandled.status == "unresponsive"
    assert unhandled.should_continue is True
    assert unhandled.metadata["unresponsive"] is True

    canceled = []
    handle = SimpleNamespace(done=lambda: False, cancel=lambda: canceled.append(True))
    assert registry.attach_cancel_handle(agent_task_id="t3", tool_name=SHELL_TOOL, handle=handle) is run
    handled = registry.assess("r3")
    assert handled.status == "stale"
    assert handled.stale_reason == "declared_timeout_exceeded"
    assert handled.should_continue is False

    assert registry.force_cancel("r3", reason="stop it") is True
    assert canceled == [True]
    assert run.force_cancel_reason == "stop it"


def test_force_cancel_ignores_finished_or_missing_handles():
    registry = ActiveToolRunRegistry()
    run = _register(registry, "r-done", "t-done")
    assert registry.force_cancel("r-done", reason="nothing attached") is False
    run.cancel_handle = SimpleNamespace(done=lambda: True, cancel=lambda: None)
    assert registry.force_cancel("r-done", reason="already finished") is False
    assert run.force_cancel_reason is None
    assert registry.force_cancel("missing-run", reason="no run") is False


def test_input_waiting_run_can_be_marked_resumed():
    registry = get_tool_run_registry()
    registry.clear_agent_task("t4")
    run = _register(registry, "r4", "t4")
    try:
        record_tool_progress(agent_task_id="t4", tool_name=SHELL_TOOL, status="input_waiting", progress_kind="input_requested")
        resumed = record_tool_progress(agent_task_id="t4", tool_name=SHELL_TOOL, status="service_running", progress_kind="input_resolved")
        assert resumed is run
        assert run.status == "service_running"
    finally:
        registry.discard("r4")


@pytest.mark.asyncio
async def test_watchdog_force_cancel_returns_tool_error():
    registry = get_tool_run_registry()
    registry.clear_agent_task("task-force")
    _register(registry, "force-run", "task-force", tool_name="fake_service_hang")
    engine = _HangingEngine()
    tool_error_log: list = []
    token = set_current_agent_context({"agent_task_id": "task-force"})
    try:
        invocation = asyncio.create_task(_hanging_tool(engine, tool_error_log).ainvoke({}))
        await asyncio.wait_for(engine.started.wait(), 5)
        assert registry.force_cancel("force-run", reason="Stopped by watchdog test") is True
        output = await asyncio.wait_for(invocation, 5)
    finally:
        reset_current_agent_context(token)
        registry.discard("force-run")

    assert engine.service_canceled.is_set()
    assert output.startswith("ERROR: Tool execution failed for fake_service.hang")
    assert "Stopped by watchdog test" in output
    assert tool_error_log[-1]["type"] == "exception"


@pytest.mark.asyncio
async def test_agent_cancellation_still_propagates_through_wrapper():
    registry = get_tool_run_registry()
    registry.clear_agent_task("task-outer-cancel")
    run = _register(registry, "outer-run", "task-outer-cancel", tool_name="fake_service_hang")
    engine = _HangingEngine()
    token = set_current_agent_context({"agent_task_id": "task-outer-cancel"})
    try:
        invocation = asyncio.create_task(_hanging_tool(engine, []).ainvoke({}))
        await asyncio.wait_for(engine.started.wait(), 5)
        invocation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await invocation
    finally:
        reset_current_agent_context(token)
        registry.discard("outer-run")

    assert engine.service_canceled.is_set()
    assert run.force_cancel_reason is None
    assert run.cancel_handle is None


@pytest.mark.asyncio
async def test_heartbeat_force_cancels_run_that_overran_its_declared_timeout():
    registry = get_tool_run_registry()
    registry.clear_agent_task("task-heartbeat")
    notifier = _Notifier()
    handler = LiveProgressCallbackHandler(notifier=notifier, todo_id="task-heartbeat")
    handler._heartbeat_interval_seconds = 0.01
    hung = asyncio.create_task(asyncio.Event().wait())
    try:
        await handler.on_tool_start({"name": SHELL_TOOL}, run_id="hb-run", inputs={"command": "sleep"})
        run = registry.get("hb-run")
        assert run is not None
        run.mark("service_running", "process_started", timeout_seconds=1.0)
        registry.attach_cancel_handle(agent_task_id="task-heartbeat", tool_name=SHELL_TOOL, handle=hung)
        run.started_at_monotonic -= 100

        for _ in range(300):
            if hung.done():
                break
            await asyncio.sleep(0.01)
    finally:
        if not hung.done():
            hung.cancel()
        handler._stop_active_step_heartbeat("hb-run")
        registry.discard("hb-run")

    assert hung.cancelled()
    assert notifier.updated[-1]["status"] == "failed"
    assert "exceeded its own time limit" in notifier.updated[-1]["completion_message"]
