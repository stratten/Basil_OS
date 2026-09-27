"""TodoService coverage: hydration/listing, manual/tool/meeting-promotion
creation, every user transition, the complete-blocked-by-active-worker rule,
worker reconciliation (active -> in_progress, completed -> ready_for_review),
and startup recovery counting."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.queries import (
    AgentTaskQueries,
    _result_severity_for_sidebar,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
)
from api.services.todos.repository import TodoRepository
from api.services.todos.service import TodoConflictError, TodoNotFoundError, TodoService, TodoTransitionError


@pytest.mark.parametrize(
    ("status", "result_data", "expected_severity"),
    [
        (
            "failed",
            {"finalizer_result": {"result_payload": {"outcome": "partial"}}},
            "warning",
        ),
        (
            "completed",
            {"finalizer_result": {"result_payload": {"outcome": "success"}}},
            "success",
        ),
        (
            "completed",
            {"finalizer_result": {"result_payload": {"outcome": "failure"}}},
            "error",
        ),
        ("failed", {}, "error"),
    ],
)
def test_sidebar_result_severity_reserves_error_for_failures(
    status: str,
    result_data: Dict[str, Any],
    expected_severity: str,
) -> None:
    assert _result_severity_for_sidebar(status, result_data) == expected_severity


@pytest.mark.asyncio
async def test_origin_status_lookup_surfaces_active_follow_up_from_root_origin(tmp_path: Path) -> None:
    database_path = tmp_path / "agent_task_status.db"
    with get_sync_connection(str(database_path)) as connection:
        connection.execute(
            """
            INSERT INTO agent_tasks (
                id, timestamp, original_prompt, transcribed_prompt, root_task_id,
                origin_type, origin_id, status, result_data, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "root", "2026-01-01T00:00:00Z", "Original task", "Original task",
                "root", "todo", "todo-1", "completed", "{}", "2026-01-01T00:00:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO agent_tasks (
                id, timestamp, original_prompt, transcribed_prompt, root_task_id,
                origin_type, origin_id, status, result_data, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "follow-up",
                "2026-01-01T00:01:00Z", "Follow-up task", "Follow-up task",
                "root", None, None, "processing", "{}", "2026-01-01T00:02:00Z",
            ),
        )

    queries = AgentTaskQueries(str(database_path), lambda row: row)

    statuses = await queries.list_latest_agent_task_status_by_origins("todo", ["todo-1"])

    assert statuses["todo-1"]["agent_task_id"] == "follow-up"
    assert statuses["todo-1"]["status"] == "processing"
    assert statuses["todo-1"]["is_active"] is True


@dataclass
class FakeAgentTask:
    id: str
    status: str
    origin_type: Optional[str] = None
    origin_id: Optional[str] = None
    title: Optional[str] = None
    result_data: Optional[Dict[str, Any]] = None
    accumulated_artifacts: Optional[Dict[str, Any]] = None

    @property
    def timestamp(self):
        import datetime

        return datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


class FakeAgentTaskService:
    """Stands in for `SQLiteKnowledgeService` from `TodoService`'s point of
    view: only the three methods `TodoService` actually calls."""

    def __init__(self) -> None:
        self.tasks: List[FakeAgentTask] = []
        self.root_status_by_origin: Dict[str, Dict[str, Any]] = {}

    async def list_agent_tasks_by_origin(self, origin_type: str, origin_id: str, include_terminal: bool = True):
        matches = [t for t in self.tasks if t.origin_type == origin_type and t.origin_id == origin_id]
        if include_terminal:
            return matches
        return [t for t in matches if t.status not in ("completed", "failed", "cancelled")]

    async def list_nonterminal_agent_tasks_by_origin_type(self, origin_type: str):
        return [
            t for t in self.tasks
            if t.origin_type == origin_type and t.status not in ("completed", "failed", "cancelled")
        ]

    async def list_agent_task_origin_ids_by_origin_type(self, origin_type: str):
        return sorted({t.origin_id for t in self.tasks if t.origin_type == origin_type and t.origin_id})

    async def list_latest_agent_task_status_by_origins(self, origin_type: str, origin_ids: List[str]):
        return {
            origin_id: self.root_status_by_origin[origin_id]
            for origin_id in origin_ids
            if origin_type == "todo" and origin_id in self.root_status_by_origin
        }


@pytest.fixture
def agent_tasks() -> FakeAgentTaskService:
    return FakeAgentTaskService()


@pytest.fixture
def service(tmp_path: Path, agent_tasks: FakeAgentTaskService) -> TodoService:
    repository = TodoRepository(str(tmp_path / "todo_service.db"))
    return TodoService(repository=repository, agent_task_service=agent_tasks)


@pytest.mark.asyncio
async def test_get_workspace_hydration_reflects_created_items(service: TodoService) -> None:
    await service.create_manual_todo(
        title="Draft the follow-up email", description="", notes="", responsibility="user",
        priority="normal", due_at=None, idempotency_key=None, payload_for_hash={},
    )
    hydration = await service.get_workspace_hydration()
    assert len(hydration.items) == 1
    assert hydration.items[0].title == "Draft the follow-up email"


@pytest.mark.asyncio
async def test_get_item_detail_raises_not_found_for_unknown_id(service: TodoService) -> None:
    with pytest.raises(TodoNotFoundError):
        await service.get_item_detail("does-not-exist")


@pytest.mark.asyncio
async def test_get_item_detail_populates_worker_attempts_and_attention(
    service: TodoService, agent_tasks: FakeAgentTaskService,
) -> None:
    detail = await service.create_manual_todo(
        title="Investigate outage", description="", notes="", responsibility="agent",
        priority="high", due_at=None, idempotency_key=None, payload_for_hash={},
    )
    agent_tasks.tasks.append(
        FakeAgentTask(id="wa-1", status="needs_clarification", origin_type="todo", origin_id=detail.id, title="Worker")
    )
    fetched = await service.get_item_detail(detail.id)
    assert len(fetched.worker_attempts) == 1
    assert fetched.worker_attempts[0].attention is True
    assert fetched.attention.needs_attention is True
    assert fetched.attention.reason


@pytest.mark.asyncio
async def test_create_manual_todo_defaults_to_open_status_and_normalizes_legacy_priority(
    service: TodoService,
) -> None:
    detail = await service.create_manual_todo(
        title="Buy groceries", description="", notes="", responsibility="user", priority="medium",
        due_at=None, idempotency_key=None, payload_for_hash={},
    )
    assert detail.status == "open"
    assert detail.priority == "normal"


@pytest.mark.asyncio
async def test_create_manual_todo_idempotency_conflict_raises_transition_error(service: TodoService) -> None:
    await service.create_manual_todo(
        title="A", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key="dup-key", payload_for_hash={"title": "A"},
    )
    with pytest.raises(TodoTransitionError):
        await service.create_manual_todo(
            title="B", description="", notes="", responsibility="user", priority="normal", due_at=None,
            idempotency_key="dup-key", payload_for_hash={"title": "B"},
        )


@pytest.mark.asyncio
async def test_create_todo_from_agent_tool_sources_from_the_agent_task(service: TodoService) -> None:
    detail = await service.create_todo_from_agent_tool(
        title="Follow up with vendor", description="Details from the call", agent_task_id="task-1",
        tool_call_id="call-1", excerpt="Vendor call notes",
    )
    assert detail.created_by_kind == "agent"
    assert detail.sources[0].source_kind == "agent_task_tool"
    assert detail.sources[0].source_id == "task-1:call-1"


@pytest.mark.asyncio
async def test_promote_meeting_proposal_to_todo_is_idempotent_via_source_lookup(service: TodoService) -> None:
    first = await service.promote_meeting_proposal_to_todo(
        meeting_id="m1", filename="f1", proposal_id="p1", title="Follow up", description="", excerpt="",
    )
    existing = await service.repository.find_todo_by_source(
        source_kind="meeting_analysis_proposal", source_id="m1:f1:p1",
    )
    assert existing is not None
    assert existing.id == first.id


@pytest.mark.asyncio
async def test_promote_meeting_proposal_bounds_title_and_preserves_full_description(
    service: TodoService,
) -> None:
    long_title = "A" * 300
    description = "Full grouped To-Do detail remains intact."

    detail = await service.promote_meeting_proposal_to_todo(
        meeting_id="m1", filename="f1", proposal_id="p2", title=long_title,
        description=description, excerpt="Meeting source",
    )

    assert detail.title == "A" * 240
    assert len(detail.title) == 240
    assert detail.description == description
    assert detail.sources[0].source_id == "m1:f1:p2"


@pytest.mark.asyncio
async def test_promote_meeting_proposal_rejects_blank_title(service: TodoService) -> None:
    with pytest.raises(TodoTransitionError, match="must not be blank"):
        await service.promote_meeting_proposal_to_todo(
            meeting_id="m1", filename="f1", proposal_id="p3", title="  ", description="", excerpt="",
        )


@pytest.mark.asyncio
async def test_accept_dismiss_reopen_cancel_transitions(service: TodoService) -> None:
    detail, _created = await service.repository.create_todo_item_with_source(
        title="Candidate item", description="", notes="", responsibility="unspecified", priority="normal",
        due_at=None, status="candidate", created_by_kind="system", created_by_id=None,
        idempotency_key=None, idempotency_payload_hash=None, source_kind=None, source_id=None,
        source_locator=None, source_excerpt="",
    )
    dismissed = await service.dismiss_candidate(detail.id, detail.revision)
    assert dismissed.status == "dismissed"
    reopened = await service.reopen(dismissed.id, dismissed.revision)
    assert reopened.status == "open"
    cancelled = await service.cancel(reopened.id, reopened.revision)
    assert cancelled.status == "cancelled"


@pytest.mark.asyncio
async def test_accept_candidate_transitions_candidate_to_open(service: TodoService) -> None:
    detail, _ = await service.repository.create_todo_item_with_source(
        title="From a producer", description="", notes="", responsibility="unspecified", priority="normal",
        due_at=None, status="candidate", created_by_kind="system", created_by_id=None, idempotency_key=None,
        idempotency_payload_hash=None, source_kind=None, source_id=None, source_locator=None, source_excerpt="",
    )
    accepted = await service.accept_candidate(detail.id, detail.revision)
    assert accepted.status == "open"


@pytest.mark.asyncio
async def test_complete_succeeds_when_no_active_worker(service: TodoService) -> None:
    detail = await service.create_manual_todo(
        title="Simple task", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    completed = await service.complete(detail.id, detail.revision)
    assert completed.status == "completed"
    assert completed.completed_at is not None


@pytest.mark.asyncio
async def test_complete_preserves_an_existing_completion_timestamp_and_reopen_clears_it(service: TodoService) -> None:
    detail = await service.create_manual_todo(
        title="Historical completion", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    completed = await service.complete(detail.id, detail.revision)
    historical = await service.update_fields(
        completed.id,
        completed.revision,
        {"completed_at": "2025-12-24T09:30:00Z"},
    )
    assert historical.completed_at == "2025-12-24T09:30:00Z"
    cleared = await service.update_fields(historical.id, historical.revision, {"completed_at": None})
    assert cleared.completed_at is None
    reopened = await service.reopen(cleared.id, cleared.revision)
    assert reopened.status == "open"
    assert reopened.completed_at is None


@pytest.mark.asyncio
async def test_completed_date_is_only_mutable_on_completed_items(service: TodoService) -> None:
    detail = await service.create_manual_todo(
        title="Not complete", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    with pytest.raises(TodoTransitionError, match="Completed date can only"):
        await service.update_fields(
            detail.id,
            detail.revision,
            {"completed_at": "2025-12-24T09:30:00Z"},
        )


@pytest.mark.asyncio
async def test_complete_is_blocked_while_a_directly_sourced_worker_is_active(
    service: TodoService, agent_tasks: FakeAgentTaskService,
) -> None:
    detail = await service.create_manual_todo(
        title="Has an active worker", description="", notes="", responsibility="agent", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={},
    )
    agent_tasks.tasks.append(FakeAgentTask(id="w-1", status="processing", origin_type="todo", origin_id=detail.id))
    with pytest.raises(TodoTransitionError) as exc_info:
        await service.complete(detail.id, detail.revision)
    assert exc_info.value.detail is not None
    assert exc_info.value.detail.status == "open"  # unchanged


@pytest.mark.asyncio
async def test_delete_todo_hard_deletes_owned_rows_and_preserves_terminal_agent_task(
    service: TodoService, agent_tasks: FakeAgentTaskService,
) -> None:
    detail, _ = await service.repository.create_todo_item_with_source(
        title="Remove duplicate", description="", notes="", responsibility="user", priority="normal",
        due_at=None, status="open", created_by_kind="user", created_by_id=None, idempotency_key=None,
        idempotency_payload_hash=None, source_kind="manual_test", source_id="delete-1",
        source_locator={}, source_excerpt="Created incorrectly",
    )
    referenced = await service.add_reference(detail.id, "/tmp/remove-me.txt", detail.revision)
    agent_tasks.tasks.append(
        FakeAgentTask(
            id="preserved-agent-task",
            status="completed",
            origin_type="todo",
            origin_id=detail.id,
        )
    )

    await service.delete_todo_item(referenced.id, referenced.revision)

    with pytest.raises(TodoNotFoundError):
        await service.get_item_detail(detail.id)
    connection = service.repository._connection()
    try:
        assert connection.execute("SELECT COUNT(*) AS n FROM todo_sources WHERE todo_id = ?", (detail.id,)).fetchone()["n"] == 0
        assert connection.execute("SELECT COUNT(*) AS n FROM todo_references WHERE todo_id = ?", (detail.id,)).fetchone()["n"] == 0
        assert connection.execute("SELECT COUNT(*) AS n FROM todo_events WHERE todo_id = ?", (detail.id,)).fetchone()["n"] == 0
    finally:
        connection.close()
    assert [task.id for task in agent_tasks.tasks] == ["preserved-agent-task"]


@pytest.mark.asyncio
async def test_delete_todo_rejects_active_workers_and_stale_revisions(
    service: TodoService, agent_tasks: FakeAgentTaskService,
) -> None:
    detail = await service.create_manual_todo(
        title="Active worker", description="", notes="", responsibility="agent", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    agent_tasks.tasks.append(
        FakeAgentTask(id="active-worker", status="processing", origin_type="todo", origin_id=detail.id)
    )
    with pytest.raises(TodoTransitionError, match="Cannot delete while"):
        await service.delete_todo_item(detail.id, detail.revision)

    agent_tasks.tasks.clear()
    updated = await service.update_fields(detail.id, detail.revision, {"description": "Changed"})
    with pytest.raises(TodoConflictError):
        await service.delete_todo_item(updated.id, detail.revision)


@pytest.mark.asyncio
async def test_delete_todo_rejects_active_follow_up_from_its_root_origin(
    service: TodoService, agent_tasks: FakeAgentTaskService,
) -> None:
    detail = await service.create_manual_todo(
        title="Follow-up still running", description="", notes="", responsibility="agent", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={},
    )
    agent_tasks.root_status_by_origin[detail.id] = {
        "agent_task_id": "follow-up-worker",
        "status": "processing",
        "result_severity": None,
        "is_active": True,
        "updated_at": "2026-01-01T00:00:00Z",
    }

    with pytest.raises(TodoTransitionError, match="follow-up"):
        await service.delete_todo_item(detail.id, detail.revision)

    assert (await service.get_item_detail(detail.id)).id == detail.id


@pytest.mark.asyncio
async def test_update_fields_drops_none_values_and_normalizes_priority(service: TodoService) -> None:
    detail = await service.create_manual_todo(
        title="Original", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    updated = await service.update_fields(
        detail.id, detail.revision, {"title": None, "description": "New description", "priority": "medium"},
    )
    assert updated.title == "Original"  # None was dropped, not applied
    assert updated.description == "New description"
    assert updated.priority == "normal"


@pytest.mark.asyncio
async def test_replace_notes_conflict_returns_latest_item_in_the_error(service: TodoService) -> None:
    detail = await service.create_manual_todo(
        title="Notes item", description="", notes="v1", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    await service.replace_notes(detail.id, detail.revision, "v2")
    with pytest.raises(TodoConflictError) as exc_info:
        await service.replace_notes(detail.id, detail.revision, "v3-stale")  # stale expected_revision
    assert exc_info.value.detail.notes == "v2"


@pytest.mark.asyncio
async def test_add_and_remove_reference_normalize_only_path_syntax_and_enforce_revision(
    service: TodoService,
) -> None:
    detail = await service.create_manual_todo(
        title="Reference item", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    added = await service.add_reference(
        detail.id,
        "/tmp/project/../brief.pdf",
        detail.revision,
        actor_agent_task_id="agent-task-1",
    )
    assert [reference.path for reference in added.references] == ["/tmp/brief.pdf"]
    assert added.references[0].created_by_kind == "agent"
    with pytest.raises(TodoConflictError):
        await service.remove_reference(detail.id, added.references[0].id, detail.revision)
    removed = await service.remove_reference(detail.id, added.references[0].id, added.revision)
    assert removed.references == []


@pytest.mark.asyncio
async def test_add_reference_rejects_relative_blank_and_nul_paths_without_filesystem_access(service: TodoService) -> None:
    detail = await service.create_manual_todo(
        title="Invalid path item", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    for invalid_path in ("relative/file.txt", "   ", "/tmp/invalid\x00path"):
        with pytest.raises(TodoTransitionError):
            await service.add_reference(detail.id, invalid_path, detail.revision)
    fetched = await service.get_item_detail(detail.id)
    assert fetched.references == []


@pytest.mark.asyncio
async def test_worker_handoff_deduplicates_agent_source_task_ids_and_reference_paths(service: TodoService) -> None:
    detail = await service.create_todo_from_agent_tool(
        title="Agent-created", description="", agent_task_id="source-task-1", tool_call_id="call-1", excerpt="source",
    )
    added = await service.add_reference(detail.id, "/tmp/brief.pdf", detail.revision)
    handoff = service.worker_handoff(added)
    assert handoff == {
        "source_agent_task_ids": ["source-task-1"],
        "source_excerpts": {"source-task-1": "source"},
        "reference_paths": ["/tmp/brief.pdf"],
    }


@pytest.mark.asyncio
async def test_append_workspace_manager_note_hydrates_worker_attempts(
    service: TodoService, agent_tasks: FakeAgentTaskService,
) -> None:
    detail = await service.create_manual_todo(
        title="Workspace-noted item", description="", notes="", responsibility="agent", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={},
    )
    agent_tasks.tasks.append(FakeAgentTask(id="w-2", status="completed", origin_type="todo", origin_id=detail.id))
    updated = await service.append_workspace_manager_note(detail.id, "Found the invoice.", "manager-task-1")
    assert "Found the invoice." in updated.notes
    assert len(updated.worker_attempts) == 1


@pytest.mark.asyncio
async def test_launch_todo_worker_rejects_a_candidate(service: TodoService) -> None:
    detail, _ = await service.repository.create_todo_item_with_source(
        title="Candidate", description="", notes="", responsibility="unspecified", priority="normal",
        due_at=None, status="candidate", created_by_kind="system", created_by_id=None, idempotency_key=None,
        idempotency_payload_hash=None, source_kind=None, source_id=None, source_locator=None, source_excerpt="",
    )
    with pytest.raises(TodoTransitionError):
        await service.launch_todo_worker(todo_id=detail.id, expected_revision=detail.revision, launcher=None)


@pytest.mark.asyncio
async def test_launch_todo_worker_rejects_a_terminal_todo(service: TodoService) -> None:
    detail = await service.create_manual_todo(
        title="Already done", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    completed = await service.complete(detail.id, detail.revision)
    with pytest.raises(TodoTransitionError):
        await service.launch_todo_worker(todo_id=completed.id, expected_revision=completed.revision, launcher=None)


@pytest.mark.asyncio
async def test_launch_todo_worker_rejects_a_stale_expected_revision(service: TodoService) -> None:
    detail = await service.create_manual_todo(
        title="Open item", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    with pytest.raises(TodoConflictError):
        await service.launch_todo_worker(todo_id=detail.id, expected_revision=99, launcher=None)


@pytest.mark.asyncio
async def test_launch_todo_worker_invokes_the_injected_launcher(service: TodoService) -> None:
    detail = await service.create_manual_todo(
        title="Open item", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    calls = []

    async def fake_launcher(*, todo_id: str):
        calls.append(todo_id)
        return {"success": True, "agent_task_id": "worker-1"}

    result = await service.launch_todo_worker(todo_id=detail.id, expected_revision=detail.revision, launcher=fake_launcher)
    assert calls == [detail.id]
    assert result.item.id == detail.id
    assert result.agent_task_id == "worker-1"


@pytest.mark.asyncio
async def test_launch_todo_worker_surfaces_a_rejected_launcher(service: TodoService) -> None:
    detail = await service.create_manual_todo(
        title="Rejected worker", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )

    async def rejected_launcher(*, todo_id: str):
        return {"success": False, "error": "no eligible model"}

    with pytest.raises(TodoTransitionError, match="no eligible model"):
        await service.launch_todo_worker(
            todo_id=detail.id, expected_revision=detail.revision, launcher=rejected_launcher,
        )


@pytest.mark.asyncio
async def test_reconcile_todo_from_worker_tasks_returns_none_for_missing_todo(service: TodoService) -> None:
    assert await service.reconcile_todo_from_worker_tasks("does-not-exist") is None


@pytest.mark.asyncio
async def test_reconcile_todo_from_worker_tasks_is_a_noop_for_a_terminal_todo(
    service: TodoService, agent_tasks: FakeAgentTaskService,
) -> None:
    detail = await service.create_manual_todo(
        title="Already cancelled", description="", notes="", responsibility="user", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={},
    )
    cancelled = await service.cancel(detail.id, detail.revision)
    agent_tasks.tasks.append(FakeAgentTask(id="w-3", status="processing", origin_type="todo", origin_id=cancelled.id))
    result = await service.reconcile_todo_from_worker_tasks(cancelled.id)
    assert result.status == "cancelled"  # unchanged despite an "active" worker row


@pytest.mark.asyncio
async def test_reconcile_todo_from_worker_tasks_moves_open_to_in_progress_when_a_worker_is_active(
    service: TodoService, agent_tasks: FakeAgentTaskService,
) -> None:
    detail = await service.create_manual_todo(
        title="Has an active worker", description="", notes="", responsibility="agent", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={},
    )
    agent_tasks.tasks.append(FakeAgentTask(id="w-4", status="processing", origin_type="todo", origin_id=detail.id))
    result = await service.reconcile_todo_from_worker_tasks(detail.id)
    assert result.status == "in_progress"


@pytest.mark.asyncio
async def test_reconcile_todo_from_worker_tasks_moves_to_ready_for_review_when_a_worker_completed(
    service: TodoService, agent_tasks: FakeAgentTaskService,
) -> None:
    detail = await service.create_manual_todo(
        title="Worker finished", description="", notes="", responsibility="agent", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={},
    )
    agent_tasks.tasks.append(FakeAgentTask(id="w-5", status="completed", origin_type="todo", origin_id=detail.id))
    result = await service.reconcile_todo_from_worker_tasks(detail.id)
    assert result.status == "ready_for_review"


@pytest.mark.asyncio
async def test_reconcile_todo_from_worker_tasks_with_no_workers_is_a_noop(service: TodoService) -> None:
    detail = await service.create_manual_todo(
        title="No workers yet", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    result = await service.reconcile_todo_from_worker_tasks(detail.id)
    assert result.status == "open"


@pytest.mark.asyncio
async def test_reconcile_all_nonterminal_todo_workers_returns_count_of_reconciled_todos(
    service: TodoService, agent_tasks: FakeAgentTaskService,
) -> None:
    """Startup recovery includes a completed worker whose terminal callback
    was missed just before restart, as well as an in-flight worker."""
    open_a = await service.create_manual_todo(
        title="A", description="", notes="", responsibility="agent", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={"t": "a"},
    )
    open_b = await service.create_manual_todo(
        title="B", description="", notes="", responsibility="agent", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={"t": "b"},
    )
    await service.create_manual_todo(
        title="C (no worker)", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={"t": "c"},
    )
    agent_tasks.tasks.append(FakeAgentTask(id="w-a", status="processing", origin_type="todo", origin_id=open_a.id))
    agent_tasks.tasks.append(FakeAgentTask(id="w-b", status="completed", origin_type="todo", origin_id=open_b.id))

    count = await service.reconcile_all_nonterminal_todo_workers()
    assert count == 2
    reconciled_a = await service.get_item_detail(open_a.id)
    reconciled_b = await service.get_item_detail(open_b.id)
    assert reconciled_a.status == "in_progress"
    assert reconciled_b.status == "ready_for_review"
