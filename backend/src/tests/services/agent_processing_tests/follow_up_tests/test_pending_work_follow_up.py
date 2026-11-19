"""A verdict of "work still pending" becomes one durable follow-up check and a waiting result."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.follow_up_repository import (
    AgentTaskFollowUpRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.agent_follow_up_migrations import (
    migrate_agent_follow_up_tables,
)
from api.services.agent_processing.lifecycle.finalization.evaluation import (
    DEFAULT_PENDING_CHECK_DELAY_MINUTES,
    MAX_PENDING_CHECK_DELAY_MINUTES,
    MIN_PENDING_CHECK_DELAY_MINUTES,
    compose_outcome_intro,
    parse_pending_work,
)
from api.services.agent_processing.lifecycle.finalization.pending_work_follow_up import (
    AUTO_FOLLOW_UP_REASON,
    MAX_AUTO_FOLLOW_UPS_PER_ROOT,
    apply_waiting_state,
    schedule_follow_up_for_pending_work,
)

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
PENDING = {"instructions": "Check the delegated agent run for REQ-1.", "delay_minutes": 30}


@pytest.fixture
def repository(tmp_path) -> AgentTaskFollowUpRepository:
    db_path = tmp_path / "pending_work.db"
    with sqlite3.connect(db_path) as conn:
        migrate_agent_follow_up_tables(conn)
    return AgentTaskFollowUpRepository(str(db_path))


async def _schedule(repository, pending=PENDING, root="root-1", source="task-1"):
    return await schedule_follow_up_for_pending_work(
        root_task_id=root,
        source_agent_task_id=source,
        pending_work=pending,
        repository_provider=lambda: repository,
        now_fn=lambda: NOW,
    )


def test_parse_requires_an_explicit_true_flag_and_instructions():
    assert parse_pending_work({}) is None
    assert parse_pending_work({"work_still_pending": "true", "pending_check_instructions": "x"}) is None
    assert parse_pending_work({"work_still_pending": False, "pending_check_instructions": "x"}) is None
    assert parse_pending_work({"work_still_pending": True, "pending_check_instructions": "   "}) is None
    assert parse_pending_work({"work_still_pending": True}) is None


def test_parse_clamps_delay_and_defaults_when_missing_or_invalid():
    def delay(value):
        return parse_pending_work(
            {"work_still_pending": True, "pending_check_instructions": "check", "pending_check_delay_minutes": value}
        )["delay_minutes"]

    assert delay(1) == MIN_PENDING_CHECK_DELAY_MINUTES
    assert delay(10**6) == MAX_PENDING_CHECK_DELAY_MINUTES
    assert delay(45) == 45
    assert delay(None) == DEFAULT_PENDING_CHECK_DELAY_MINUTES
    assert delay("soon") == DEFAULT_PENDING_CHECK_DELAY_MINUTES
    assert delay(True) == DEFAULT_PENDING_CHECK_DELAY_MINUTES


def test_parse_bounds_long_instructions():
    parsed = parse_pending_work({"work_still_pending": True, "pending_check_instructions": "x" * 5000})
    assert len(parsed["instructions"]) == 1000


@pytest.mark.asyncio
async def test_schedules_one_follow_up_at_the_requested_delay(repository):
    row = await _schedule(repository)

    assert row["status"] == "scheduled"
    assert row["root_task_id"] == "root-1"
    assert row["source_agent_task_id"] == "task-1"
    assert row["reason"] == AUTO_FOLLOW_UP_REASON
    assert row["due_at"] == "2026-10-12T12:30:00+00:00"
    assert row["instructions"] == PENDING["instructions"]


@pytest.mark.asyncio
async def test_does_not_schedule_when_a_follow_up_is_already_active(repository):
    await repository.create_follow_up(
        root_task_id="root-1", source_agent_task_id="task-1", instructions="agent made this", reason="", due_at="2026-10-12T13:00:00+00:00"
    )
    assert await _schedule(repository) is None
    assert len(await repository.list_for_root("root-1")) == 1


@pytest.mark.asyncio
async def test_automatic_follow_ups_are_limited_per_chain(repository):
    for _ in range(MAX_AUTO_FOLLOW_UPS_PER_ROOT):
        row = await _schedule(repository)
        assert row is not None
        await repository.cancel_pending_for_root("root-1", reason="done")
    assert await _schedule(repository) is None


@pytest.mark.asyncio
async def test_falls_back_to_the_task_id_without_a_root(repository):
    row = await _schedule(repository, root=None, source="task-9")
    assert row["root_task_id"] == "task-9"


@pytest.mark.asyncio
async def test_empty_or_missing_inputs_schedule_nothing(repository):
    assert await _schedule(repository, pending={"instructions": " ", "delay_minutes": 10}) is None
    assert await _schedule(repository, root=None, source=None) is None


@pytest.mark.asyncio
async def test_repository_failure_never_raises(repository):
    class _Broken:
        async def list_for_root(self, root_task_id):
            raise RuntimeError("database locked")

    assert await schedule_follow_up_for_pending_work(
        root_task_id="root-1", source_agent_task_id="task-1", pending_work=PENDING, repository_provider=lambda: _Broken()
    ) is None


def test_waiting_state_replaces_the_partial_framing():
    reason = "A required follow-up step remains."
    refined = {
        "success": False,
        "outcome": "partial",
        "outcome_reason": reason,
        "summary_text": f"{compose_outcome_intro('partial', reason)}\n\nThe delegated agent is running.",
        "result_payload": {"outcome": "partial", "outcome_reason": reason},
    }

    apply_waiting_state(refined, {"due_at": "2026-10-12T12:30:00+00:00", "instructions": "Check the run."})

    assert refined["success"] is True
    assert refined["outcome"] == "success"
    assert "outcome_reason" not in refined
    assert refined["result_payload"]["outcome"] == "success"
    assert refined["result_payload"]["outcome_reason"] == ""
    assert refined["result_payload"]["pending_follow_up_due_at"] == "2026-10-12T12:30:00+00:00"
    assert not refined["summary_text"].startswith("Partial result")
    assert "The delegated agent is running." in refined["summary_text"]
    assert "check again automatically at 2026-10-12T12:30:00+00:00: Check the run." in refined["summary_text"]


def test_waiting_state_handles_a_summary_without_the_partial_prefix():
    refined = {"success": False, "summary_text": "", "result_payload": {}}
    apply_waiting_state(refined, {"due_at": "2026-10-12T12:30:00+00:00", "instructions": "Check."})
    assert refined["summary_text"].startswith("Waiting on work that is still running.")


@pytest.mark.asyncio
async def test_earliest_pending_due_by_root_reports_only_scheduled_rows(repository):
    await repository.create_follow_up(root_task_id="root-a", source_agent_task_id="t", instructions="late", reason="", due_at="2026-10-12T15:00:00+00:00")
    await repository.create_follow_up(root_task_id="root-a", source_agent_task_id="t", instructions="soon", reason="", due_at="2026-10-12T13:00:00+00:00")
    await repository.create_follow_up(root_task_id="root-b", source_agent_task_id="t", instructions="gone", reason="", due_at="2026-10-12T14:00:00+00:00")
    await repository.cancel_pending_for_root("root-b", reason="canceled")

    due = await repository.earliest_pending_due_by_root(["root-a", "root-b", "root-c", "root-a", ""])

    assert due == {"root-a": "2026-10-12T13:00:00+00:00"}
    assert await repository.earliest_pending_due_by_root([]) == {}


def test_evaluation_prompt_asks_for_the_pending_work_fields():
    from api.services.agent_processing.lifecycle.finalization.evaluation import build_evaluation_prompt

    prompt = build_evaluation_prompt(
        original_prompt="Chase the request.",
        self_assessment=None,
        full_agent_output="The delegated agent is running.",
        max_output_chars=50000,
        steps=[],
        tool_error_history=None,
        evaluation_context=None,
    )
    for field in ("work_still_pending", "pending_check_instructions", "pending_check_delay_minutes"):
        assert f'"{field}"' in prompt
    assert "PENDING WORK" in prompt
