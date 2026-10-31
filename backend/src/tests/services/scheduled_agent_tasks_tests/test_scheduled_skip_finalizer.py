"""A skipped run ends without touching the schedule's last status and arms the next occurrence."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from api.services.scheduled_agent_tasks.scheduled_agent_task_service_components import scheduled_run_lifecycle


class _Repo:
    def __init__(self, schedule):
        self.schedule = schedule
        self.update_scheduled_run = AsyncMock()
        self.get_scheduled_agent_task = AsyncMock(return_value=schedule)
        self.update_scheduled_agent_task = AsyncMock()


def _schedule(**overrides):
    base = {
        "id": "s1",
        "is_active": True,
        "schedule_type": "recurring",
        "schedule_config": {"mode": "interval", "minutes": 30},
        "timezone": "UTC",
    }
    base.update(overrides)
    return base


def test_skipped_run_records_notice_and_rearms_without_changing_last_status():
    repo = _Repo(_schedule())
    with patch.object(scheduled_run_lifecycle, "enqueue_scheduled_agent_task", new=AsyncMock()) as enqueue:
        result = asyncio.run(scheduled_run_lifecycle.finalize_skipped_run(repo, scheduled_agent_task_id="s1", run_id="r1", reason="Busy"))
    run_call = repo.update_scheduled_run.await_args
    assert run_call.args == ("r1",)
    assert run_call.kwargs["status"] == "skipped" and run_call.kwargs["notice"] == "Busy"
    update_kwargs = repo.update_scheduled_agent_task.await_args.kwargs
    assert set(update_kwargs) == {"next_run_at"}
    assert result["status"] == "skipped" and result["next_run_at"] == update_kwargs["next_run_at"]
    enqueue.assert_awaited_once_with(repo, "s1", update_kwargs["next_run_at"])


def test_skipped_run_of_an_inactive_schedule_does_not_rearm():
    repo = _Repo(_schedule(is_active=False))
    with patch.object(scheduled_run_lifecycle, "enqueue_scheduled_agent_task", new=AsyncMock()) as enqueue:
        result = asyncio.run(scheduled_run_lifecycle.finalize_skipped_run(repo, scheduled_agent_task_id="s1", run_id="r1", reason="Busy"))
    assert result["next_run_at"] is None
    repo.update_scheduled_agent_task.assert_not_awaited()
    enqueue.assert_not_awaited()


def test_skipped_run_clears_next_run_when_windows_leave_no_time():
    schedule = _schedule(
        schedule_config={"mode": "daily", "time": "23:00", "exclusion_windows": [{"start": "22:00", "end": "07:00"}]},
    )
    repo = _Repo(schedule)
    with patch.object(scheduled_run_lifecycle, "enqueue_scheduled_agent_task", new=AsyncMock()) as enqueue:
        result = asyncio.run(scheduled_run_lifecycle.finalize_skipped_run(repo, scheduled_agent_task_id="s1", run_id="r1", reason="Busy"))
    assert result["next_run_at"] is None
    repo.update_scheduled_agent_task.assert_awaited_once_with("s1", clear_next_run_at=True)
    enqueue.assert_not_awaited()
