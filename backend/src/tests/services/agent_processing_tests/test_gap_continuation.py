"""Gap continuation: evaluator parsing, scheduling caps, the continuing note, and the scheduler's model and user-reply handling."""

from __future__ import annotations

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
from api.services.agent_follow_ups.follow_up_scheduler import (
    GAP_CONTINUATION_REASON,
    AgentFollowUpScheduler,
    build_follow_up_display_markdown,
    build_follow_up_prompt,
)
from api.services.agent_processing.lifecycle.finalization.evaluation import (
    MAX_CONTINUATION_INSTRUCTIONS_CHARS,
    build_evaluation_prompt,
    parse_continuation_instructions,
)
from api.services.agent_processing.lifecycle.finalization.gap_continuation import (
    MAX_GAP_CONTINUATIONS_PER_CHAIN,
    apply_continuation_note,
    schedule_gap_continuation,
)

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
GAP = "The sidebar component was never built; build it from the attached reference."


@pytest.fixture
def repository(tmp_path) -> AgentTaskFollowUpRepository:
    db_path = tmp_path / "gap.db"
    with sqlite3.connect(db_path) as conn:
        migrate_agent_follow_up_tables(conn)
    return AgentTaskFollowUpRepository(str(db_path))


async def _schedule(repository, instructions=GAP, root="root-1", source="task-1"):
    return await schedule_gap_continuation(
        root_task_id=root,
        source_agent_task_id=source,
        instructions=instructions,
        repository_provider=lambda: repository,
        now_fn=lambda: NOW,
    )


def test_parse_requires_a_non_empty_string_and_clamps_length():
    assert parse_continuation_instructions({}) is None
    assert parse_continuation_instructions({"continuation_instructions": "   "}) is None
    assert parse_continuation_instructions({"continuation_instructions": 7}) is None
    assert parse_continuation_instructions({"continuation_instructions": f"  {GAP}  "}) == GAP
    assert len(parse_continuation_instructions({"continuation_instructions": "x" * 5000})) == MAX_CONTINUATION_INSTRUCTIONS_CHARS


def test_parse_defers_to_pending_work_when_the_evaluator_says_work_is_still_running():
    assert parse_continuation_instructions({"work_still_pending": True, "continuation_instructions": GAP}) is None


def test_evaluation_prompt_asks_for_the_continuation_field():
    prompt = build_evaluation_prompt(
        original_prompt="Build it",
        self_assessment=None,
        full_agent_output="done",
        max_output_chars=50000,
        steps=[],
        tool_error_history=None,
        evaluation_context=None,
    )
    assert '"continuation_instructions"' in prompt
    assert "CONTINUATION:" in prompt


@pytest.mark.asyncio
async def test_schedules_a_due_now_row_with_the_distinct_reason(repository):
    row = await _schedule(repository)

    assert row["reason"] == GAP_CONTINUATION_REASON
    assert row["instructions"] == GAP
    assert row["source_agent_task_id"] == "task-1"
    assert row["due_at"] == NOW.isoformat(timespec="seconds")


@pytest.mark.asyncio
async def test_blank_instructions_or_ids_schedule_nothing(repository):
    assert await _schedule(repository, instructions="   ") is None
    assert await schedule_gap_continuation(
        root_task_id=None, source_agent_task_id=None, instructions=GAP, repository_provider=lambda: repository
    ) is None
    assert await repository.list_for_root("root-1") == []


@pytest.mark.asyncio
async def test_an_active_follow_up_blocks_a_new_continuation(repository):
    await repository.create_follow_up(
        root_task_id="root-1", source_agent_task_id="task-1", instructions="Check", reason="r", due_at=NOW.isoformat()
    )

    assert await _schedule(repository) is None


@pytest.mark.asyncio
async def test_the_chain_cap_stops_further_continuations(repository):
    for index in range(MAX_GAP_CONTINUATIONS_PER_CHAIN):
        created = await _schedule(repository, source=f"task-{index}")
        assert created is not None
        await repository.cancel_pending_for_root("root-1", reason="done")

    assert MAX_GAP_CONTINUATIONS_PER_CHAIN == 2
    assert await _schedule(repository, source="task-9") is None


@pytest.mark.asyncio
async def test_a_repository_failure_schedules_nothing():
    def broken():
        raise RuntimeError("database locked")

    assert await schedule_gap_continuation(
        root_task_id="root-1", source_agent_task_id="task-1", instructions=GAP, repository_provider=broken
    ) is None


def test_continuing_note_keeps_the_verdict_partial_and_says_basil_is_continuing():
    refined = {"success": False, "outcome": "partial", "summary_text": "Partial result: the sidebar is missing.", "result_payload": {"outcome": "partial"}}

    apply_continuation_note(refined, {"id": "fu-1", "instructions": GAP})

    assert refined["outcome"] == "partial"
    assert refined["success"] is False
    assert refined["summary_text"].startswith("Partial result: the sidebar is missing.")
    assert f"Basil is continuing automatically to close this gap: {GAP}" in refined["summary_text"]
    assert refined["result_payload"]["continuation_scheduled"] is True
    assert refined["result_payload"]["continuation_follow_up_id"] == "fu-1"
    assert refined["result_payload"]["outcome"] == "partial"


def test_continuation_prompt_and_display_name_the_gap_not_a_scheduled_check():
    follow_up = {"reason": GAP_CONTINUATION_REASON, "instructions": GAP}

    prompt = build_follow_up_prompt(follow_up)

    assert GAP in prompt
    assert "outcome check found a gap" in prompt
    assert build_follow_up_display_markdown(follow_up) == f"**Continuing task:** {GAP}"


class _ChainReader:
    def __init__(self, tasks):
        self.tasks = tasks

    async def get_agent_task_chain(self, root_task_id):
        return self.tasks

    async def list_agent_tasks_by_origin(self, origin_type, origin_id, include_terminal=True):
        return []


class _Submission:
    def __init__(self):
        self.calls = []

    async def process_agent_task_direct(self, **kwargs):
        self.calls.append(kwargs)
        return {"success": True}


def _scheduler(repository, tasks, submission):
    return AgentFollowUpScheduler(
        repository=repository, chain_reader=_ChainReader(tasks), submission_service=submission, now_fn=lambda: NOW + timedelta(seconds=5)
    )


@pytest.mark.asyncio
async def test_scheduler_runs_the_continuation_on_the_chains_model(repository):
    row = await _schedule(repository, source="task-1")
    tasks = [SimpleNamespace(id="task-1", status="completed", accumulated_artifacts={"model_id": "local-qwen"})]
    submission = _Submission()

    counts = await _scheduler(repository, tasks, submission).run_once()

    assert counts["submitted"] == 1
    call = submission.calls[0]
    assert call["model_id"] == "local-qwen"
    assert GAP in call["agent_task"]
    assert call["display_prompt_markdown"] == f"**Continuing task:** {GAP}"
    assert (await repository.get_follow_up(row["id"]))["status"] == "submitted"


@pytest.mark.asyncio
async def test_scheduler_omits_model_id_when_the_chain_has_no_override(repository):
    await _schedule(repository, source="task-1")
    tasks = [SimpleNamespace(id="task-1", status="completed", accumulated_artifacts=None)]
    submission = _Submission()

    await _scheduler(repository, tasks, submission).run_once()

    assert "model_id" not in submission.calls[0]


@pytest.mark.asyncio
async def test_scheduler_cancels_a_continuation_when_the_user_already_replied(repository):
    row = await _schedule(repository, source="task-1")
    tasks = [
        SimpleNamespace(id="task-1", status="completed", accumulated_artifacts={}),
        SimpleNamespace(id="task-2", status="completed", accumulated_artifacts={}),
    ]
    submission = _Submission()

    counts = await _scheduler(repository, tasks, submission).run_once()

    assert counts["canceled"] == 1
    assert submission.calls == []
    stored = await repository.get_follow_up(row["id"])
    assert stored["status"] == "canceled"
    assert "moved on" in stored["error_message"]


@pytest.mark.asyncio
async def test_scheduler_cancels_a_continuation_for_a_canceled_run(repository):
    await _schedule(repository, source="task-1")
    tasks = [SimpleNamespace(id="task-1", status="canceled", accumulated_artifacts={})]
    submission = _Submission()

    counts = await _scheduler(repository, tasks, submission).run_once()

    assert counts["canceled"] == 1
    assert submission.calls == []


@pytest.mark.asyncio
async def test_pending_work_follow_ups_still_use_the_scheduled_check_prompt(repository):
    row = await repository.create_follow_up(
        root_task_id="root-1", source_agent_task_id="task-1", instructions="Check the deploy", reason="deploy", due_at=NOW.isoformat()
    )
    tasks = [SimpleNamespace(id="task-9", status="completed", accumulated_artifacts={"model_id": "m"})]
    submission = _Submission()

    counts = await _scheduler(repository, tasks, submission).run_once()

    assert counts["submitted"] == 1
    assert "outcome check found a gap" not in submission.calls[0]["agent_task"]
    assert submission.calls[0]["model_id"] == "m"
    assert (await repository.get_follow_up(row["id"]))["status"] == "submitted"
