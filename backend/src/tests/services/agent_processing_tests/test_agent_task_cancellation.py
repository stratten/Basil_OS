"""Tests for AgentTaskCancellationRegistry.

Covers the cooperative-state surface (canceled set + events) and the new
preemptive task-tracking surface (register / deregister / cancel_active_task),
including the negative and adversarial cases called out in the plan:
  * cancel with nothing registered / with an already-done task -> no-op (False),
  * deregister with a different task must not clobber a re-submitted task.
"""

from __future__ import annotations

import asyncio

import pytest

from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_cancellation import (
    AgentTaskCancellationRegistry,
)


def test_is_canceled_false_by_default():
    registry = AgentTaskCancellationRegistry()
    assert registry.is_canceled("task-1") is False


@pytest.mark.asyncio
async def test_mark_canceled_flips_state_and_sets_event():
    registry = AgentTaskCancellationRegistry()
    event = registry.get_cancellation_event("task-1")
    assert event.is_set() is False

    registry.mark_canceled(["task-1"])

    assert registry.is_canceled("task-1") is True
    assert event.is_set() is True


@pytest.mark.asyncio
async def test_mark_canceled_ignores_empty_ids():
    registry = AgentTaskCancellationRegistry()

    registry.mark_canceled(["", None])  # type: ignore[list-item]

    assert registry.is_canceled("") is False
    # No spurious events were created for the falsy ids.
    assert registry._cancellation_events == {}


def test_get_cancellation_event_returns_stable_instance():
    registry = AgentTaskCancellationRegistry()
    first = registry.get_cancellation_event("task-1")
    second = registry.get_cancellation_event("task-1")
    assert first is second


@pytest.mark.asyncio
async def test_cancel_active_task_cancels_running_task():
    registry = AgentTaskCancellationRegistry()

    started = asyncio.Event()

    async def _long_running():
        started.set()
        await asyncio.sleep(3600)

    task = asyncio.create_task(_long_running())
    await started.wait()
    registry.register_active_task("task-1", task)

    assert registry.cancel_active_task("task-1") is True

    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled() is True


@pytest.mark.asyncio
async def test_cancel_active_task_no_op_when_nothing_registered():
    registry = AgentTaskCancellationRegistry()
    assert registry.cancel_active_task("unknown") is False


@pytest.mark.asyncio
async def test_cancel_active_task_no_op_when_task_already_done():
    registry = AgentTaskCancellationRegistry()

    async def _noop():
        return None

    task = asyncio.create_task(_noop())
    await task  # let it finish
    registry.register_active_task("task-1", task)

    assert registry.cancel_active_task("task-1") is False


@pytest.mark.asyncio
async def test_deregister_with_different_task_does_not_clobber():
    registry = AgentTaskCancellationRegistry()

    async def _sleeper():
        await asyncio.sleep(3600)

    current = asyncio.create_task(_sleeper())
    stale = asyncio.create_task(_sleeper())
    try:
        registry.register_active_task("task-1", current)

        # A stale coroutine's finally tries to deregister with ITS task object;
        # it must not remove the current registration.
        registry.deregister_active_task("task-1", stale)

        assert registry.cancel_active_task("task-1") is True
    finally:
        current.cancel()
        stale.cancel()
        for t in (current, stale):
            with pytest.raises(asyncio.CancelledError):
                await t


@pytest.mark.asyncio
async def test_deregister_with_matching_task_removes_registration():
    registry = AgentTaskCancellationRegistry()

    async def _sleeper():
        await asyncio.sleep(3600)

    task = asyncio.create_task(_sleeper())
    try:
        registry.register_active_task("task-1", task)
        registry.deregister_active_task("task-1", task)
        assert registry.cancel_active_task("task-1") is False
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
