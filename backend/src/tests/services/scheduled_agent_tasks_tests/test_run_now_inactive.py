"""Run now starts a run even when the schedule is deactivated, and only Run now does."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import patch

from api.services.scheduled_agent_tasks.async_scheduled_agent_task_runner import AsyncScheduledAgentTaskRunner
from api.services.scheduled_agent_tasks.scheduled_agent_task_service import ScheduledAgentTaskService
from api.services.scheduled_agent_tasks.scheduled_agent_task_service_components import scheduled_run_lifecycle


class _Repo:
    def __init__(self) -> None:
        self.canceled_for: List[str] = []
        self.created: List[Dict[str, Any]] = []

    async def cancel_pending_runs_for_agent_task(self, scheduled_agent_task_id: str) -> None:
        self.canceled_for.append(scheduled_agent_task_id)

    async def create_scheduled_run(self, **kwargs: Any) -> Dict[str, Any]:
        self.created.append(kwargs)
        return {"id": "run-1"}


def test_run_now_schedules_the_run_so_it_executes_even_when_the_schedule_is_inactive() -> None:
    scheduled: List[Any] = []
    runner = SimpleNamespace(
        cancel=lambda *_args, **_kwargs: True,
        schedule=lambda *args, **kwargs: scheduled.append((args, kwargs)),
    )
    repo = _Repo()

    with patch("api.services.scheduled_agent_tasks.async_scheduled_agent_task_runner.get_async_scheduled_agent_task_runner", lambda: runner):
        run_id = asyncio.run(scheduled_run_lifecycle.run_scheduled_agent_task_now(repo, "schedule-1"))

    assert run_id == "run-1"
    assert repo.canceled_for == ["schedule-1"]
    assert len(scheduled) == 1
    args, kwargs = scheduled[0]
    assert args[:2] == ("schedule-1", "run-1")
    assert kwargs == {"allow_inactive": True}


def test_a_timer_driven_run_never_allows_an_inactive_schedule() -> None:
    calls: List[Dict[str, Any]] = []

    async def fake_execute(self, scheduled_agent_task_id: str, run_id: str, **options: Any) -> Dict[str, Any]:
        calls.append({"run_id": run_id, **options})
        return {}

    async def scenario() -> None:
        runner = AsyncScheduledAgentTaskRunner()
        with patch.object(ScheduledAgentTaskService, "__init__", lambda self: None), patch.object(
            ScheduledAgentTaskService, "execute_scheduled_run", fake_execute
        ):
            runner.schedule("schedule-1", "timer-run", datetime.now(timezone.utc))
            runner.schedule("schedule-2", "manual-run", datetime.now(timezone.utc), allow_inactive=True)
            await asyncio.sleep(0.3)

    asyncio.run(scenario())

    assert sorted(calls, key=lambda call: call["run_id"]) == [
        {"run_id": "manual-run", "allow_inactive": True},
        {"run_id": "timer-run"},
    ]
