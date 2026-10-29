"""Durable follow-up rows: limits, claiming, transitions, cancellation, and restart recovery."""

from __future__ import annotations

import sqlite3

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.follow_up_repository import (
    MAX_PENDING_FOLLOW_UPS_PER_ROOT,
    AgentTaskFollowUpRepository,
    FollowUpLimitExceeded,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.agent_follow_up_migrations import (
    migrate_agent_follow_up_tables,
)


@pytest.fixture
def repository(tmp_path) -> AgentTaskFollowUpRepository:
    db_path = tmp_path / "follow_ups.db"
    with sqlite3.connect(db_path) as conn:
        migrate_agent_follow_up_tables(conn)
        migrate_agent_follow_up_tables(conn)
    return AgentTaskFollowUpRepository(str(db_path))


async def _create(repository, *, root="root-1", due_at="2026-10-01T12:00:00+00:00", instructions="Check the build"):
    return await repository.create_follow_up(
        root_task_id=root,
        source_agent_task_id="task-1",
        instructions=instructions,
        reason="waiting on CI",
        due_at=due_at,
    )


@pytest.mark.asyncio
async def test_create_and_list_round_trip_special_characters(repository):
    created = await _create(repository, instructions="Check 'build' \"status\" ; DROP TABLE x; -- \u00e9")

    assert created["status"] == "scheduled"
    assert created["defer_count"] == 0
    listed = await repository.list_for_root("root-1")
    assert [row["id"] for row in listed] == [created["id"]]
    assert listed[0]["instructions"] == "Check 'build' \"status\" ; DROP TABLE x; -- \u00e9"
    assert await repository.get_follow_up("missing") is None


@pytest.mark.asyncio
async def test_pending_limit_is_enforced_per_root(repository):
    for _ in range(MAX_PENDING_FOLLOW_UPS_PER_ROOT):
        await _create(repository)

    with pytest.raises(FollowUpLimitExceeded):
        await _create(repository)
    other_root = await _create(repository, root="root-2")

    assert other_root["status"] == "scheduled"
    assert len(await repository.list_for_root("root-1")) == MAX_PENDING_FOLLOW_UPS_PER_ROOT


@pytest.mark.asyncio
async def test_lifetime_limit_counts_finished_rows(repository, monkeypatch):
    from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks import follow_up_repository

    monkeypatch.setattr(follow_up_repository, "MAX_TOTAL_FOLLOW_UPS_PER_ROOT", 2)
    first = await _create(repository)
    await repository.claim_due_follow_ups(now_iso="2026-10-01T12:00:00+00:00")
    await repository.mark_submitted(first["id"], follow_up_agent_task_id="turn-1")
    await _create(repository)

    with pytest.raises(FollowUpLimitExceeded):
        await _create(repository)


@pytest.mark.asyncio
async def test_claim_only_returns_due_rows_once(repository):
    due = await _create(repository, due_at="2026-10-01T11:59:59+00:00")
    later = await _create(repository, due_at="2026-10-01T12:00:01+00:00")

    claimed = await repository.claim_due_follow_ups(now_iso="2026-10-01T12:00:00+00:00")
    assert [row["id"] for row in claimed] == [due["id"]]
    assert claimed[0]["status"] == "dispatching"
    assert await repository.claim_due_follow_ups(now_iso="2026-10-01T12:00:00+00:00") == []
    assert (await repository.get_follow_up(later["id"]))["status"] == "scheduled"


@pytest.mark.asyncio
async def test_transitions_require_dispatching(repository):
    row = await _create(repository)

    assert await repository.mark_submitted(row["id"], follow_up_agent_task_id="turn-1") is False
    await repository.claim_due_follow_ups(now_iso="2026-10-01T12:00:00+00:00")
    assert await repository.defer_follow_up(row["id"], due_at="2026-10-01T12:01:00+00:00", reason="busy") is True

    deferred = await repository.get_follow_up(row["id"])
    assert deferred["status"] == "scheduled"
    assert deferred["defer_count"] == 1
    assert deferred["error_message"] == "busy"

    await repository.claim_due_follow_ups(now_iso="2026-10-01T12:01:00+00:00")
    assert await repository.mark_submitted(row["id"], follow_up_agent_task_id="turn-1") is True
    submitted = await repository.get_follow_up(row["id"])
    assert submitted["status"] == "submitted"
    assert submitted["follow_up_agent_task_id"] == "turn-1"
    assert submitted["error_message"] is None


@pytest.mark.asyncio
async def test_finish_rejects_unsupported_status(repository):
    row = await _create(repository)
    await repository.claim_due_follow_ups(now_iso="2026-10-01T12:00:00+00:00")

    with pytest.raises(ValueError):
        await repository.finish_without_submission(row["id"], status="submitted", error_message="nope")
    assert await repository.finish_without_submission(row["id"], status="missed", error_message="late") is True
    assert (await repository.get_follow_up(row["id"]))["status"] == "missed"


@pytest.mark.asyncio
async def test_cancel_for_root_skips_dispatching_and_other_roots(repository):
    dispatching = await _create(repository, due_at="2026-10-01T11:00:00+00:00")
    await repository.claim_due_follow_ups(now_iso="2026-10-01T11:30:00+00:00")
    scheduled = await _create(repository, due_at="2026-10-02T11:00:00+00:00")
    other = await _create(repository, root="root-2")

    assert await repository.cancel_pending_for_root("root-1", reason="user canceled") == 1
    assert (await repository.get_follow_up(scheduled["id"]))["status"] == "canceled"
    assert (await repository.get_follow_up(dispatching["id"]))["status"] == "dispatching"
    assert (await repository.get_follow_up(other["id"]))["status"] == "scheduled"
    assert await repository.cancel_pending_for_root("root-1", reason="again") == 0


@pytest.mark.asyncio
async def test_recover_interrupted_dispatches(repository):
    row = await _create(repository)
    await repository.claim_due_follow_ups(now_iso="2026-10-01T12:00:00+00:00")

    assert await repository.recover_interrupted_dispatches() == 1
    assert (await repository.get_follow_up(row["id"]))["status"] == "scheduled"
    assert await repository.recover_interrupted_dispatches() == 0


def test_check_constraint_rejects_unknown_status(repository):
    with sqlite3.connect(repository.db_path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_task_follow_ups (id, root_task_id, source_agent_task_id, instructions, due_at, status, created_at, updated_at) VALUES ('x', 'r', 's', 'i', 'd', 'unknown_status', 'c', 'u')"
        )


@pytest.mark.asyncio
async def test_knowledge_service_creates_table_and_exposes_repository(tmp_path):
    service = SQLiteKnowledgeService(tmp_path / "knowledge_base.db")

    created = await service.agent_task_follow_up_repository.create_follow_up(
        root_task_id="root-1",
        source_agent_task_id="task-1",
        instructions="Check the deploy",
        reason="",
        due_at="2026-10-01T12:00:00+00:00",
    )

    assert created["status"] == "scheduled"
