"""Regression coverage for runs that canceled themselves while finalizing.

A run finalizes by arming the next occurrence of the same schedule, which cancels whatever the runner holds for that schedule and installs a new timer.
While the executing task was still the runner's entry for that schedule it canceled itself at its next await, so ``scheduled_agent_task_run_completed`` was never broadcast and the mini panel kept showing finished runs as "Working on the task" or "Verifying the outcome".
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List
from unittest.mock import patch

from api.services.scheduled_agent_tasks.async_scheduled_agent_task_runner import (
    AsyncScheduledAgentTaskRunner,
)
from api.services.scheduled_agent_tasks.scheduled_agent_task_service import (
    ScheduledAgentTaskService,
)


async def _run_that_rearms_its_own_schedule() -> tuple[List[str], AsyncScheduledAgentTaskRunner]:
    steps: List[str] = []
    runner = AsyncScheduledAgentTaskRunner()
    next_eta = datetime.now(timezone.utc) + timedelta(seconds=30)

    async def fake_execute(self, scheduled_agent_task_id: str, run_id: str):
        steps.append("started")
        runner.cancel(scheduled_agent_task_id)
        runner.schedule(scheduled_agent_task_id, "run-2", next_eta)
        await asyncio.sleep(0.05)
        steps.append("completion broadcast")
        return {}

    with patch.object(ScheduledAgentTaskService, "__init__", lambda self: None), patch.object(
        ScheduledAgentTaskService, "execute_scheduled_run", fake_execute
    ):
        runner.schedule("schedule-1", "run-1", datetime.now(timezone.utc))
        await asyncio.sleep(0.3)
    return steps, runner


def test_a_run_that_rearms_its_own_schedule_still_reaches_its_completion_step():
    steps, runner = asyncio.run(_run_that_rearms_its_own_schedule())
    assert steps == ["started", "completion broadcast"]


def test_the_next_occurrence_timer_survives_the_finished_run():
    async def scenario() -> bool:
        steps, runner = await _run_that_rearms_its_own_schedule()
        try:
            return runner.has_pending("schedule-1")
        finally:
            runner.cancel("schedule-1", quiet=True)
            await asyncio.sleep(0.01)

    assert asyncio.run(scenario()) is True


def test_a_finished_run_leaves_nothing_in_the_executing_map():
    async def scenario() -> int:
        steps, runner = await _run_that_rearms_its_own_schedule()
        try:
            return len(runner._executing)
        finally:
            runner.cancel("schedule-1", quiet=True)
            await asyncio.sleep(0.01)

    assert asyncio.run(scenario()) == 0


def test_canceling_a_schedule_does_not_stop_a_run_that_is_executing():
    async def scenario() -> List[str]:
        steps: List[str] = []
        runner = AsyncScheduledAgentTaskRunner()

        async def fake_execute(self, scheduled_agent_task_id: str, run_id: str):
            steps.append("started")
            await asyncio.sleep(0.1)
            steps.append("finished")
            return {}

        with patch.object(ScheduledAgentTaskService, "__init__", lambda self: None), patch.object(
            ScheduledAgentTaskService, "execute_scheduled_run", fake_execute
        ):
            runner.schedule("schedule-1", "run-1", datetime.now(timezone.utc))
            await asyncio.sleep(0.03)
            assert runner.cancel("schedule-1", quiet=True) is False
            await asyncio.sleep(0.3)
        return steps

    assert asyncio.run(scenario()) == ["started", "finished"]


def test_shutdown_still_stops_a_run_that_is_executing():
    async def scenario() -> List[str]:
        steps: List[str] = []
        runner = AsyncScheduledAgentTaskRunner()

        async def fake_execute(self, scheduled_agent_task_id: str, run_id: str):
            steps.append("started")
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                steps.append("canceled")
                raise
            steps.append("finished")
            return {}

        with patch.object(ScheduledAgentTaskService, "__init__", lambda self: None), patch.object(
            ScheduledAgentTaskService, "execute_scheduled_run", fake_execute
        ):
            runner.schedule("schedule-1", "run-1", datetime.now(timezone.utc))
            await asyncio.sleep(0.03)
            runner.cancel_all()
            await asyncio.sleep(0.05)
        return steps

    assert asyncio.run(scenario()) == ["started", "canceled"]
