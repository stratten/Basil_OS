"""Regression coverage for the 2026-10-28 incident in which seven copies of one scheduled run started at the same instant.

The reconciler re-arms every active schedule once a minute by canceling the runner's task and scheduling a replacement for the same run.
Both tasks carry the same name, so the canceled predecessor's ``finally`` block used to evict the live replacement from the runner's map without canceling it.
The next re-arm then could not find (or cancel) the evicted task, and every second tick left one more orphaned sleeper that fired at the original ETA.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Tuple
from unittest.mock import patch

from api.services.scheduled_agent_tasks.async_scheduled_agent_task_runner import (
    AsyncScheduledAgentTaskRunner,
)
from api.services.scheduled_agent_tasks.scheduled_agent_task_service import (
    ScheduledAgentTaskService,
)


async def _rearm_and_count_executions(rearm_count: int) -> Tuple[int, AsyncScheduledAgentTaskRunner]:
    executed: List[Tuple[str, str]] = []

    async def fake_execute(self, scheduled_agent_task_id: str, run_id: str):
        executed.append((scheduled_agent_task_id, run_id))
        return {}

    runner = AsyncScheduledAgentTaskRunner()
    eta = datetime.now(timezone.utc) + timedelta(seconds=0.5)
    with patch.object(ScheduledAgentTaskService, "__init__", lambda self: None), patch.object(
        ScheduledAgentTaskService, "execute_scheduled_run", fake_execute
    ):
        for _ in range(rearm_count):
            runner.cancel("schedule-1", quiet=True)
            runner.schedule("schedule-1", "run-1", eta, quiet=True)
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.8)
    return len(executed), runner


def test_repeated_rearms_of_the_same_run_execute_it_exactly_once():
    executions, _runner = asyncio.run(_rearm_and_count_executions(13))
    assert executions == 1


def test_single_rearm_still_executes_once():
    executions, _runner = asyncio.run(_rearm_and_count_executions(2))
    assert executions == 1


def test_runner_releases_its_entry_after_the_run_finishes():
    _executions, runner = asyncio.run(_rearm_and_count_executions(3))
    assert runner.has_pending("schedule-1") is False


def test_canceled_predecessor_does_not_evict_its_replacement():
    asyncio.run(_assert_replacement_survives())


async def _assert_replacement_survives():
    runner = AsyncScheduledAgentTaskRunner()
    eta = datetime.now(timezone.utc) + timedelta(seconds=30)
    runner.schedule("schedule-1", "run-1", eta, quiet=True)
    runner.schedule("schedule-1", "run-1", eta, quiet=True)
    await asyncio.sleep(0.05)
    try:
        assert runner.has_pending("schedule-1") is True
    finally:
        runner.cancel("schedule-1", quiet=True)
        await asyncio.sleep(0.01)
