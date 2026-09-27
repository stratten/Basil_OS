"""TodoWorkspaceTurnManager coverage: single/multi-item selection, dismissed
or cancelled To-Dos are rejected from selection, duplicate ids are
deduplicated, an empty selection is rejected, and submission-service
rejection surfaces as an exception."""

from pathlib import Path
from typing import Any, Dict, List

import pytest

from api.services.todos.repository import TodoRepository
from api.services.todos.service import TodoService
from api.services.todos.workspace_turn_manager import TodoWorkspaceTurnManager, TodoWorkspaceValidationError


class FakeAgentTaskLookup:
    async def list_agent_tasks_by_origin(self, origin_type: str, origin_id: str, include_terminal: bool = True):
        return []

    async def list_nonterminal_agent_tasks_by_origin_type(self, origin_type: str):
        return []


class FakeAgentTaskSubmissionService:
    def __init__(self, *, result: Dict[str, Any] = None) -> None:
        self.result = result if result is not None else {"success": True}
        self.calls: List[Dict[str, Any]] = []

    async def process_agent_task_direct(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


@pytest.fixture
def todo_service(tmp_path: Path) -> TodoService:
    return TodoService(repository=TodoRepository(str(tmp_path / "workspace.db")), agent_task_service=FakeAgentTaskLookup())


@pytest.mark.asyncio
async def test_submit_turn_with_a_single_selected_item(todo_service: TodoService) -> None:
    item = await todo_service.create_manual_todo(
        title="Single item", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    submission_service = FakeAgentTaskSubmissionService()
    manager = TodoWorkspaceTurnManager(todo_service=todo_service, agent_task_submission_service=submission_service)

    result = await manager.submit_turn(
        workspace_id="ws-1", request_id="req-1", message="What's the status?", transcript=[],
        selected_todo_ids=[item.id], reference_paths=[], model_id=None,
    )

    assert "agent_task_id" in result
    context = submission_service.calls[0]["todo_workspace_context"]
    assert context["selection_ids"] == [item.id]
    assert submission_service.calls[0]["origin_type"] == "todo_workspace"
    assert submission_service.calls[0]["origin_id"] == "ws-1"


@pytest.mark.asyncio
async def test_submit_turn_with_multiple_selected_items_and_deduplication(todo_service: TodoService) -> None:
    first = await todo_service.create_manual_todo(
        title="First", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={"t": "1"},
    )
    second = await todo_service.create_manual_todo(
        title="Second", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={"t": "2"},
    )
    submission_service = FakeAgentTaskSubmissionService()
    manager = TodoWorkspaceTurnManager(todo_service=todo_service, agent_task_submission_service=submission_service)

    await manager.submit_turn(
        workspace_id="ws-2", request_id="req-2", message="Summarize both",
        transcript=[], selected_todo_ids=[first.id, second.id, first.id], reference_paths=[], model_id=None,
    )

    context = submission_service.calls[0]["todo_workspace_context"]
    assert context["selection_ids"] == [first.id, second.id]


@pytest.mark.asyncio
async def test_submit_turn_with_empty_selection_creates_an_intake_manager_task(
    todo_service: TodoService,
    tmp_path: Path,
) -> None:
    submission_service = FakeAgentTaskSubmissionService()
    manager = TodoWorkspaceTurnManager(todo_service=todo_service, agent_task_submission_service=submission_service)
    reference_paths = [str(tmp_path / "notes.txt")]

    result = await manager.submit_turn(
        workspace_id="ws-3", request_id="req-3", message="Create candidates from the attachment.", transcript=[],
        selected_todo_ids=[], reference_paths=reference_paths, model_id=None,
    )

    assert "agent_task_id" in result
    assert submission_service.calls[0]["todo_workspace_context"]["selection_ids"] == []
    assert submission_service.calls[0]["todo_workspace_context"]["reference_paths"] == reference_paths
    assert submission_service.calls[0]["reference_paths"] == reference_paths
    assert "intake mode" in submission_service.calls[0]["agent_task"].lower()
    assert "reference paths" in submission_service.calls[0]["agent_task"].lower()


@pytest.mark.asyncio
async def test_submit_turn_rejects_a_dismissed_selected_item(todo_service: TodoService) -> None:
    item, _created = await todo_service.repository.create_todo_item_with_source(
        title="Will be dismissed", description="", notes="", responsibility="user", priority="normal",
        due_at=None, status="candidate", created_by_kind="system", created_by_id=None,
        idempotency_key=None, idempotency_payload_hash=None, source_kind=None, source_id=None,
        source_locator=None, source_excerpt="",
    )
    dismissed = await todo_service.dismiss_candidate(item.id, item.revision)
    submission_service = FakeAgentTaskSubmissionService()
    manager = TodoWorkspaceTurnManager(todo_service=todo_service, agent_task_submission_service=submission_service)

    with pytest.raises(TodoWorkspaceValidationError):
        await manager.submit_turn(
            workspace_id="ws-4", request_id="req-4", message="hi", transcript=[],
        selected_todo_ids=[dismissed.id], reference_paths=[], model_id=None,
        )


@pytest.mark.asyncio
async def test_submit_turn_rejects_a_cancelled_selected_item(todo_service: TodoService) -> None:
    item = await todo_service.create_manual_todo(
        title="Will be cancelled", description="", notes="", responsibility="user", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={},
    )
    cancelled = await todo_service.cancel(item.id, item.revision)
    submission_service = FakeAgentTaskSubmissionService()
    manager = TodoWorkspaceTurnManager(todo_service=todo_service, agent_task_submission_service=submission_service)

    with pytest.raises(TodoWorkspaceValidationError):
        await manager.submit_turn(
            workspace_id="ws-5", request_id="req-5", message="hi", transcript=[],
        selected_todo_ids=[cancelled.id], reference_paths=[], model_id=None,
        )


@pytest.mark.asyncio
async def test_submit_turn_builds_a_transcript_digest_bounded_by_the_last_twenty_messages(
    todo_service: TodoService,
) -> None:
    item = await todo_service.create_manual_todo(
        title="Chatty item", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    submission_service = FakeAgentTaskSubmissionService()
    manager = TodoWorkspaceTurnManager(todo_service=todo_service, agent_task_submission_service=submission_service)
    long_transcript = [{"role": "user", "content": f"message {i}"} for i in range(30)]

    await manager.submit_turn(
        workspace_id="ws-6", request_id="req-6", message="latest", transcript=long_transcript,
        selected_todo_ids=[item.id], reference_paths=[], model_id=None,
    )

    context = submission_service.calls[0]["todo_workspace_context"]
    assert "message 29" in context["transcript_digest"]
    assert "message 0" not in context["transcript_digest"]  # older than the last 20 messages
    assert "message 29" in submission_service.calls[0]["agent_task"]


@pytest.mark.asyncio
async def test_submit_turn_raises_when_submission_service_rejects_the_manager_task(
    todo_service: TodoService,
) -> None:
    item = await todo_service.create_manual_todo(
        title="Rejected manager task", description="", notes="", responsibility="user", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={},
    )
    submission_service = FakeAgentTaskSubmissionService(
        result={"success": False, "operation": "error", "message": "no model available"}
    )
    manager = TodoWorkspaceTurnManager(todo_service=todo_service, agent_task_submission_service=submission_service)

    with pytest.raises(RuntimeError, match="no model available"):
        await manager.submit_turn(
            workspace_id="ws-7", request_id="req-7", message="hi", transcript=[],
            selected_todo_ids=[item.id], reference_paths=[], model_id=None,
        )
