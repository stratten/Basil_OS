"""Follow-up dispatch: submission into the chain, busy/canceled/missing chains, idempotency, and lifecycle."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.follow_up_repository import (
    AgentTaskFollowUpRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.agent_follow_up_migrations import (
    migrate_agent_follow_up_tables,
)
from api.services.agent_follow_ups import follow_up_scheduler as scheduler_module
from api.services.agent_follow_ups.follow_up_scheduler import (
    FOLLOW_UP_MAX_DEFERS,
    FOLLOW_UP_ORIGIN_TYPE,
    AgentFollowUpScheduler,
)

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


class _ChainReader:
    def __init__(self, statuses=("completed",), existing=()):
        self.statuses = list(statuses)
        self.existing = list(existing)

    async def get_agent_task_chain(self, root_task_id):
        return [SimpleNamespace(id=f"turn-{index}", status=status) for index, status in enumerate(self.statuses)]

    async def list_agent_tasks_by_origin(self, origin_type, origin_id, include_terminal=True):
        assert origin_type == FOLLOW_UP_ORIGIN_TYPE
        return [SimpleNamespace(id=turn_id) for turn_id in self.existing]


class _Submission:
    def __init__(self, result=None):
        self.calls = []
        self.result = {"success": True} if result is None else result

    async def process_agent_task_direct(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


@pytest.fixture
def repository(tmp_path) -> AgentTaskFollowUpRepository:
    db_path = tmp_path / "follow_ups.db"
    with sqlite3.connect(db_path) as conn:
        migrate_agent_follow_up_tables(conn)
    return AgentTaskFollowUpRepository(str(db_path))


async def _due_row(repository, *, due_at=NOW - timedelta(seconds=1)):
    return await repository.create_follow_up(
        root_task_id="root-1",
        source_agent_task_id="task-1",
        instructions="Check whether the deploy finished",
        reason="deploy takes ten minutes",
        due_at=due_at.isoformat(timespec="seconds"),
    )


def _scheduler(repository, chain_reader, submission):
    return AgentFollowUpScheduler(
        repository=repository,
        chain_reader=chain_reader,
        submission_service=submission,
        now_fn=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_due_follow_up_submits_a_chain_turn(repository):
    row = await _due_row(repository)
    submission = _Submission()

    counts = await _scheduler(repository, _ChainReader(), submission).run_once()

    assert counts["submitted"] == 1
    call = submission.calls[0]
    assert call["root_task_id"] == "root-1"
    assert call["origin_type"] == FOLLOW_UP_ORIGIN_TYPE
    assert call["origin_id"] == row["id"]
    assert "Check whether the deploy finished" in call["agent_task"]
    assert "deploy takes ten minutes" in call["agent_task"]
    stored = await repository.get_follow_up(row["id"])
    assert stored["status"] == "submitted"
    assert stored["follow_up_agent_task_id"] == call["agent_task_id"]


@pytest.mark.asyncio
async def test_future_follow_up_is_not_claimed(repository):
    row = await _due_row(repository, due_at=NOW + timedelta(minutes=5))
    submission = _Submission()

    counts = await _scheduler(repository, _ChainReader(), submission).run_once()

    assert sum(counts.values()) == 0
    assert submission.calls == []
    assert (await repository.get_follow_up(row["id"]))["status"] == "scheduled"


@pytest.mark.asyncio
async def test_busy_chain_defers_by_a_minute(repository):
    row = await _due_row(repository)
    submission = _Submission()

    counts = await _scheduler(repository, _ChainReader(statuses=("completed", "awaiting_user_input")), submission).run_once()

    assert counts["deferred"] == 1
    assert submission.calls == []
    stored = await repository.get_follow_up(row["id"])
    assert stored["status"] == "scheduled"
    assert stored["defer_count"] == 1
    assert stored["due_at"] == (NOW + timedelta(seconds=60)).isoformat(timespec="seconds")
    assert "awaiting_user_input" in stored["error_message"]


@pytest.mark.asyncio
async def test_defer_cap_fails_the_follow_up(repository, monkeypatch):
    monkeypatch.setattr(scheduler_module, "FOLLOW_UP_MAX_DEFERS", 0)
    row = await _due_row(repository)

    counts = await _scheduler(repository, _ChainReader(statuses=("processing",)), _Submission()).run_once()

    assert counts["failed"] == 1
    stored = await repository.get_follow_up(row["id"])
    assert stored["status"] == "failed"
    assert "Gave up" in stored["error_message"]
    assert FOLLOW_UP_MAX_DEFERS == 60


@pytest.mark.asyncio
async def test_canceled_chain_cancels_the_follow_up(repository):
    row = await _due_row(repository)

    counts = await _scheduler(repository, _ChainReader(statuses=("completed", "canceled")), _Submission()).run_once()

    assert counts["canceled"] == 1
    assert (await repository.get_follow_up(row["id"]))["status"] == "canceled"


@pytest.mark.asyncio
async def test_missing_chain_fails_the_follow_up(repository):
    row = await _due_row(repository)

    counts = await _scheduler(repository, _ChainReader(statuses=()), _Submission()).run_once()

    assert counts["failed"] == 1
    assert (await repository.get_follow_up(row["id"]))["error_message"] == "The task chain no longer exists."


@pytest.mark.asyncio
async def test_follow_up_more_than_a_day_late_is_missed(repository):
    row = await _due_row(repository, due_at=NOW - timedelta(hours=25))
    submission = _Submission()

    counts = await _scheduler(repository, _ChainReader(), submission).run_once()

    assert counts["missed"] == 1
    assert submission.calls == []
    assert (await repository.get_follow_up(row["id"]))["status"] == "missed"


@pytest.mark.asyncio
async def test_existing_origin_turn_is_recorded_instead_of_resubmitted(repository):
    row = await _due_row(repository)
    submission = _Submission()

    counts = await _scheduler(repository, _ChainReader(existing=("turn-already",)), submission).run_once()

    assert counts["submitted"] == 1
    assert submission.calls == []
    assert (await repository.get_follow_up(row["id"]))["follow_up_agent_task_id"] == "turn-already"


@pytest.mark.asyncio
async def test_submission_failure_and_cancellation_suppression(repository):
    failed_row = await _due_row(repository)
    failing = _Submission({"success": False, "error": "model unavailable"})

    counts = await _scheduler(repository, _ChainReader(), failing).run_once()
    assert counts["failed"] == 1
    assert (await repository.get_follow_up(failed_row["id"]))["error_message"] == "model unavailable"

    suppressed_row = await _due_row(repository)
    suppressed = _Submission({"success": False, "operation": "canceled"})
    counts = await _scheduler(repository, _ChainReader(), suppressed).run_once()
    assert counts["deferred"] == 1
    assert (await repository.get_follow_up(suppressed_row["id"]))["status"] == "scheduled"


@pytest.mark.asyncio
async def test_submission_exception_marks_failed_and_tick_continues(repository):
    row = await _due_row(repository)

    class _Raising:
        async def process_agent_task_direct(self, **kwargs):
            raise RuntimeError("orchestrator offline")

    counts = await _scheduler(repository, _ChainReader(), _Raising()).run_once()

    assert counts["failed"] == 1
    assert "orchestrator offline" in (await repository.get_follow_up(row["id"]))["error_message"]


@pytest.mark.asyncio
async def test_start_recovers_dispatching_rows_and_stop_ends_the_loop(repository):
    row = await _due_row(repository)
    await repository.claim_due_follow_ups(now_iso=NOW.isoformat(timespec="seconds"))
    scheduler = AgentFollowUpScheduler(
        repository=repository,
        chain_reader=_ChainReader(),
        submission_service=_Submission(),
        poll_seconds=3600,
        now_fn=lambda: NOW,
    )

    started = await scheduler.start()
    for _ in range(100):
        if (await repository.get_follow_up(row["id"]))["status"] == "submitted":
            break
        await asyncio.sleep(0.01)

    assert started["recovered_dispatches"] == 1
    assert scheduler.is_running is True
    assert (await repository.get_follow_up(row["id"]))["status"] == "submitted"
    await scheduler.stop()
    assert scheduler.is_running is False
    await scheduler.stop()
