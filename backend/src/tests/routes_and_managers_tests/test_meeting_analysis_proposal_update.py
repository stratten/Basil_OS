"""Tests for in-place persistence of suggested-action proposal outcomes."""

import json
from datetime import datetime

import pytest

from api.routes.meetings import analysis_proposal_store
from api.routes.meetings.analysis_proposal_store import update_proposal_outcome
from api.services.whisper_live_core.post_processing.meeting_analysis_models import (
    AnalysisMode,
    MeetingAnalysisResult,
)
from api.services.whisper_live_core.post_processing.meeting_analyzer import MeetingAnalyzer

VALID_FILENAME = "analysis_20240101_000000.json"


def _write_analysis(directory) -> str:
    """Write an analysis file with one suggested-action proposal.

    Returns the stable proposal id so tests can target it.
    """
    analyzer = MeetingAnalyzer("meeting-proposal-update-test")
    proposals = analyzer._build_action_proposals([
        {
            "source_task": "Follow up with Alex about the launch checklist.",
            "suggested_agent_task": "Draft a follow-up email to Alex about the launch checklist.",
            "capability_type": "email_draft",
            "confidence": 0.9,
            "why_basil_can_help": "Basil can draft the follow-up from meeting context.",
        }
    ])
    result = MeetingAnalysisResult(
        meeting_id="meeting-proposal-update-test",
        analyzed_at=datetime.utcnow(),
        model_used="test-model",
        modes_analyzed=[AnalysisMode.SUGGESTED_ACTIONS.value],
        suggested_actions=proposals,
        transcript_duration=120.0,
        speaker_count=2,
        processing_time=1.0,
    )
    with open(directory / VALID_FILENAME, "w") as f:
        json.dump(result.to_dict(), f, indent=2, default=str)
    return proposals[0].id


@pytest.fixture
def meeting_dir(tmp_path, monkeypatch):
    """Point the store's meeting-directory lookup at a temp directory."""
    monkeypatch.setattr(
        analysis_proposal_store.MeetingRecorder,
        "get_meeting_directory",
        staticmethod(lambda meeting_id: tmp_path),
    )
    return tmp_path


def test_update_sets_status_and_agent_task_id(meeting_dir):
    proposal_id = _write_analysis(meeting_dir)

    updated = update_proposal_outcome(
        "meeting-proposal-update-test",
        VALID_FILENAME,
        proposal_id,
        execution_status="submitted",
        submitted_agent_task_id="agent-123",
    )

    assert updated["execution_status"] == "submitted"
    assert updated["submitted_agent_task_id"] == "agent-123"

    # Round-trips to disk.
    with open(meeting_dir / VALID_FILENAME, "r") as f:
        data = json.load(f)
    stored = next(p for p in data["suggested_actions"] if p["id"] == proposal_id)
    assert stored["execution_status"] == "submitted"
    assert stored["submitted_agent_task_id"] == "agent-123"


def test_update_can_clear_agent_task_id(meeting_dir):
    proposal_id = _write_analysis(meeting_dir)

    update_proposal_outcome(
        "meeting-proposal-update-test", VALID_FILENAME, proposal_id,
        execution_status="submitted", submitted_agent_task_id="agent-123",
    )
    updated = update_proposal_outcome(
        "meeting-proposal-update-test", VALID_FILENAME, proposal_id,
        execution_status="proposed", submitted_agent_task_id=None,
    )

    assert updated["execution_status"] == "proposed"
    assert updated["submitted_agent_task_id"] is None


def test_unknown_proposal_id_raises_key_error(meeting_dir):
    _write_analysis(meeting_dir)

    with pytest.raises(KeyError):
        update_proposal_outcome(
            "meeting-proposal-update-test", VALID_FILENAME, "does-not-exist",
            execution_status="submitted", submitted_agent_task_id=None,
        )


def test_malformed_filename_raises_value_error(meeting_dir):
    proposal_id = _write_analysis(meeting_dir)

    with pytest.raises(ValueError):
        update_proposal_outcome(
            "meeting-proposal-update-test", "../evil.json", proposal_id,
            execution_status="submitted", submitted_agent_task_id=None,
        )


def test_missing_file_raises_file_not_found(meeting_dir):
    # No analysis written; a well-formed but absent filename.
    with pytest.raises(FileNotFoundError):
        update_proposal_outcome(
            "meeting-proposal-update-test", "analysis_20990101_000000.json", "any-id",
            execution_status="submitted", submitted_agent_task_id=None,
        )


def test_invalid_status_raises_value_error(meeting_dir):
    proposal_id = _write_analysis(meeting_dir)

    with pytest.raises(ValueError):
        update_proposal_outcome(
            "meeting-proposal-update-test", VALID_FILENAME, proposal_id,
            execution_status="banana", submitted_agent_task_id=None,
        )


def test_update_accepts_added_to_todos_status_with_a_todo_id(meeting_dir):
    proposal_id = _write_analysis(meeting_dir)

    updated = update_proposal_outcome(
        "meeting-proposal-update-test", VALID_FILENAME, proposal_id,
        execution_status="added_to_todos", submitted_agent_task_id=None, todo_id="todo-123",
    )

    assert updated["execution_status"] == "added_to_todos"
    assert updated["submitted_agent_task_id"] is None
    assert updated["todo_id"] == "todo-123"

    with open(meeting_dir / VALID_FILENAME, "r") as f:
        data = json.load(f)
    stored = next(p for p in data["suggested_actions"] if p["id"] == proposal_id)
    assert stored["todo_id"] == "todo-123"


def test_update_without_a_todo_id_leaves_the_field_absent(meeting_dir):
    proposal_id = _write_analysis(meeting_dir)

    updated = update_proposal_outcome(
        "meeting-proposal-update-test", VALID_FILENAME, proposal_id,
        execution_status="submitted", submitted_agent_task_id="agent-456",
    )

    assert "todo_id" not in updated or updated.get("todo_id") is None


def test_promotion_is_idempotent_via_source_lookup_when_the_projection_write_fails(meeting_dir, monkeypatch):
    """Proves the promotion route's own idempotency (source-lookup-first, per
    `routes/todos/routes.py`'s `promote_meeting_proposal`) is independent of
    whether the best-effort meeting-analysis-file projection write below it
    succeeds: even if `update_proposal_outcome` itself raises (e.g. a
    transient disk error), the durable To-Do created via `TodoService`
    remains discoverable by source on retry, so a retried promotion call
    still finds it via `find_todo_by_source` rather than creating a
    duplicate."""
    import asyncio

    from api.services.todos.repository import TodoRepository
    from api.services.todos.service import TodoService

    class NoOpAgentTasks:
        async def list_agent_tasks_by_origin(self, *a, **k):
            return []

        async def list_nonterminal_agent_tasks_by_origin_type(self, *a, **k):
            return []

    todo_service = TodoService(
        repository=TodoRepository(str(meeting_dir / "todos_projection.db")), agent_task_service=NoOpAgentTasks(),
    )

    async def _promote_and_fail_projection():
        detail = await todo_service.promote_meeting_proposal_to_todo(
            meeting_id="meeting-proposal-update-test", filename=VALID_FILENAME, proposal_id="p-fail",
            title="Follow up", description="", excerpt="",
        )
        with pytest.raises(OSError):
            with monkeypatch.context() as m:
                def _raise_disk_error(*args, **kwargs):
                    raise OSError("simulated disk failure")

                m.setattr(analysis_proposal_store, "open", _raise_disk_error, raising=False)
                update_proposal_outcome(
                    "meeting-proposal-update-test", VALID_FILENAME, "p-fail",
                    execution_status="added_to_todos", submitted_agent_task_id=None, todo_id=detail.id,
                )
        return detail

    detail = asyncio.run(_promote_and_fail_projection())

    async def _retry_lookup():
        return await todo_service.repository.find_todo_by_source(
            source_kind="meeting_analysis_proposal",
            source_id="meeting-proposal-update-test:" + VALID_FILENAME + ":p-fail",
        )

    recovered = asyncio.run(_retry_lookup())
    assert recovered is not None
    assert recovered.id == detail.id
