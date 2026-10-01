"""Pause-aware workflow deadline accounting."""

from __future__ import annotations

import asyncio

import pytest

from api.services.agent_processing.lifecycle.execution_graph import workflow_deadline
from api.services.agent_processing.lifecycle.execution_graph.workflow_deadline import (
    WorkflowDeadline,
    run_within_workflow_deadline,
)
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.shared.workflow_budget_pause import pause_workflow_budget


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(workflow_deadline, "_monotonic", fake)
    return fake


def test_paused_interval_is_excluded_from_active_budget(clock):
    deadline = WorkflowDeadline.start(
        total_seconds=100,
        finalization_reserve_seconds=0,
        absolute_ceiling_seconds=1000,
    )
    clock.now += 30
    deadline.begin_pause("approval")
    clock.now += 500
    assert deadline.is_paused is True
    assert deadline.remaining_seconds() == pytest.approx(70)
    deadline.end_pause("approval")
    clock.now += 10
    assert deadline.is_paused is False
    assert deadline.active_elapsed_seconds() == pytest.approx(40)
    assert deadline.paused_seconds() == pytest.approx(500)
    assert deadline.remaining_seconds() == pytest.approx(60)


def test_nested_pauses_count_the_union_once(clock):
    deadline = WorkflowDeadline.start(total_seconds=100, finalization_reserve_seconds=0)
    deadline.begin_pause("approval")
    clock.now += 10
    deadline.begin_pause("command_input")
    clock.now += 10
    deadline.end_pause("approval")
    assert deadline.is_paused is True
    assert deadline.pause_reasons == ["command_input"]
    clock.now += 10
    deadline.end_pause("command_input")
    assert deadline.paused_seconds() == pytest.approx(30)
    assert deadline.active_elapsed_seconds() == pytest.approx(0)


def test_unbalanced_end_pause_is_ignored(clock):
    deadline = WorkflowDeadline.start(total_seconds=100, finalization_reserve_seconds=0)
    deadline.end_pause("never-started")
    clock.now += 5
    assert deadline.active_elapsed_seconds() == pytest.approx(5)


def test_absolute_ceiling_applies_while_paused(clock):
    deadline = WorkflowDeadline.start(total_seconds=100, finalization_reserve_seconds=0)
    assert deadline.absolute_ceiling_seconds == pytest.approx(300)
    deadline.begin_pause("approval")
    clock.now += 299
    assert deadline.remaining_seconds() == pytest.approx(1)
    clock.now += 2
    assert deadline.remaining_seconds() == 0.0
    assert deadline.can_start_execution(per_pass_cap_seconds=100) is False


def test_to_dict_reports_pause_evidence(clock):
    deadline = WorkflowDeadline.start(total_seconds=100, finalization_reserve_seconds=0)
    deadline.begin_pause("approval")
    clock.now += 4
    payload = deadline.to_dict()
    assert payload["is_paused"] is True
    assert payload["pause_reasons"] == ["approval"]
    assert payload["paused_seconds"] == pytest.approx(4)
    assert payload["active_elapsed_seconds"] == pytest.approx(0)


def test_pause_workflow_budget_uses_current_agent_context(clock):
    deadline = WorkflowDeadline.start(total_seconds=100, finalization_reserve_seconds=0)
    token = set_current_agent_context({"_workflow_deadline": deadline})
    try:
        with pause_workflow_budget("approval") as paused:
            assert paused is True
            assert deadline.is_paused is True
            clock.now += 50
        assert deadline.is_paused is False
        assert deadline.remaining_seconds() == pytest.approx(100)
    finally:
        reset_current_agent_context(token)


def test_pause_workflow_budget_outside_agent_execution_is_a_noop():
    with pause_workflow_budget("approval") as paused:
        assert paused is False


@pytest.mark.asyncio
async def test_run_within_deadline_times_out_and_cancels_inner_work():
    deadline = WorkflowDeadline.start(total_seconds=0.05, finalization_reserve_seconds=0)
    inner_canceled = asyncio.Event()

    async def never_returns():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            inner_canceled.set()
            raise

    with pytest.raises(asyncio.TimeoutError):
        await run_within_workflow_deadline(never_returns(), deadline, poll_seconds=0.01)
    assert inner_canceled.is_set()


@pytest.mark.asyncio
async def test_run_within_deadline_does_not_expire_while_paused():
    deadline = WorkflowDeadline.start(
        total_seconds=0.1,
        finalization_reserve_seconds=0,
        absolute_ceiling_seconds=5.0,
    )
    deadline.begin_pause("approval")

    async def slow_but_paused():
        await asyncio.sleep(0.3)
        return "finished"

    try:
        result = await run_within_workflow_deadline(slow_but_paused(), deadline, poll_seconds=0.02)
    finally:
        deadline.end_pause("approval")
    assert result == "finished"


@pytest.mark.asyncio
async def test_run_within_deadline_propagates_outer_cancellation():
    deadline = WorkflowDeadline.start(total_seconds=10, finalization_reserve_seconds=0)
    inner_canceled = asyncio.Event()

    async def never_returns():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            inner_canceled.set()
            raise

    outer = asyncio.create_task(run_within_workflow_deadline(never_returns(), deadline, poll_seconds=0.01))
    await asyncio.sleep(0.05)
    outer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await outer
    assert inner_canceled.is_set()
