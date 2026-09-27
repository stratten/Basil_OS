"""TodoAgentTaskBridge coverage: worker launch happy/failure paths, terminal
event routing for `origin_type == "todo"` vs `"todo_workspace"`, and proof
that a workspace-manager terminal result only broadcasts a correlated event
and never mutates the underlying To-Do absent an explicit tool call."""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

import api.services.todos.agent_task_bridge as agent_task_bridge
from api.services.todos.agent_task_bridge import TodoAgentTaskBridge
from api.services.todos.repository import TodoRepository
from api.services.todos.service import TodoService


class FakeAgentTaskLookup:
    def __init__(self) -> None:
        self.tasks: Dict[str, Any] = {}
        self._by_origin: List[Any] = []

    async def get_agent_task(self, agent_task_id: str):
        return self.tasks.get(agent_task_id)

    async def list_agent_tasks_by_origin(self, origin_type: str, origin_id: str, include_terminal: bool = True):
        return [
            t for t in self._by_origin
            if getattr(t, "origin_type", None) == origin_type and getattr(t, "origin_id", None) == origin_id
        ]

    async def list_nonterminal_agent_tasks_by_origin_type(self, origin_type: str):
        return []


class FakeAgentTaskSubmissionService:
    def __init__(self, *, result: Optional[Dict[str, Any]] = None, raise_exc: Optional[Exception] = None) -> None:
        self.result = result if result is not None else {"success": True}
        self.raise_exc = raise_exc
        self.calls: List[Dict[str, Any]] = []
        self.broadcasts: List[Dict[str, Any]] = []

    async def process_agent_task_direct(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_exc:
            raise self.raise_exc
        return self.result

    async def broadcast(self, event: Dict[str, Any]) -> None:
        self.broadcasts.append(event)


@pytest.fixture
def repository(tmp_path: Path) -> TodoRepository:
    return TodoRepository(str(tmp_path / "bridge.db"))


@pytest.fixture
def agent_tasks() -> FakeAgentTaskLookup:
    return FakeAgentTaskLookup()


@pytest.fixture
def todo_service(repository: TodoRepository, agent_tasks: FakeAgentTaskLookup) -> TodoService:
    return TodoService(repository=repository, agent_task_service=agent_tasks)


def test_callback_registration_uses_the_explicit_running_database_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered_callbacks = []

    class DatabaseService:
        def register_agent_task_callback(self, callback) -> None:
            registered_callbacks.append(callback)

    monkeypatch.setattr(agent_task_bridge, "_todo_callback_registered", False)

    agent_task_bridge.ensure_todo_agent_task_callback_registered(DatabaseService())

    assert registered_callbacks == [agent_task_bridge.handle_todo_agent_task_event]


@pytest.mark.asyncio
async def test_shutdown_drains_a_queued_terminal_callback_finalizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed_task_ids = []

    class CallbackBridge:
        async def handle_terminal_event(self, agent_task_id: str) -> None:
            await asyncio.sleep(0)
            completed_task_ids.append(agent_task_id)

    monkeypatch.setattr(agent_task_bridge, "_todo_bridge_singleton", CallbackBridge())
    monkeypatch.setattr(agent_task_bridge, "_todo_finalizer_tasks", set())

    agent_task_bridge.handle_todo_agent_task_event(
        type("Event", (), {"new_status": "completed", "agent_task_id": "manager-1"})()
    )

    await agent_task_bridge.shutdown_todo_agent_task_finalizers()

    assert completed_task_ids == ["manager-1"]


@pytest.mark.asyncio
async def test_launch_todo_item_agent_task_success_updates_status_and_appends_event(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    detail = await todo_service.create_manual_todo(
        title="Needs a worker", description="", notes="", responsibility="agent", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={},
    )
    submission_service = FakeAgentTaskSubmissionService(result={"success": True})
    bridge = TodoAgentTaskBridge(
        todo_service=todo_service, agent_task_service=agent_tasks, agent_task_submission_service=submission_service,
    )

    result = await bridge.launch_todo_item_agent_task(todo_id=detail.id)

    assert result["success"] is True
    assert submission_service.calls[0]["origin_type"] == "todo"
    assert submission_service.calls[0]["origin_id"] == detail.id
    refetched = await todo_service.get_item_detail(detail.id)
    assert refetched.status == "in_progress"


@pytest.mark.asyncio
async def test_launch_worker_persists_optional_source_handoff_without_forming_a_chain(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    detail = await todo_service.create_todo_from_agent_tool(
        title="Follow up on research",
        description="Use the evidence from the source task.",
        agent_task_id="source-task-1",
        tool_call_id="tool-call-1",
        excerpt="Research identified the required next step.",
    )

    handoff = {
        "source_agent_task_ids": ["source-task-1"],
        "source_excerpts": {"source-task-1": "Research identified the required next step."},
        "reference_paths": ["/tmp/source-report.md"],
    }

    async def worker_handoff(item):
        assert item.id == detail.id
        return handoff

    todo_service.worker_handoff = worker_handoff
    submission_service = FakeAgentTaskSubmissionService(result={"success": True})
    bridge = TodoAgentTaskBridge(
        todo_service=todo_service, agent_task_service=agent_tasks, agent_task_submission_service=submission_service,
    )

    result = await bridge.launch_todo_item_agent_task(todo_id=detail.id)

    assert result["success"] is True
    submitted = submission_service.calls[0]
    assert submitted["todo_worker_context"] is handoff
    assert submitted["reference_paths"] == ["/tmp/source-report.md"]
    assert "root_task_id" not in submitted
    assert "previous_task_id" not in submitted
    assert "Attached reference paths:\n- /tmp/source-report.md" in submitted["agent_task"]
    assert "Prior investigation handoff:" in submitted["agent_task"]
    assert "recall_agent_tasks(scope='detail', task_id='<source id>')" in submitted["agent_task"]


@pytest.mark.asyncio
async def test_launch_todo_item_agent_task_handles_submission_exception(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    detail = await todo_service.create_manual_todo(
        title="Submission will blow up", description="", notes="", responsibility="agent", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={},
    )
    submission_service = FakeAgentTaskSubmissionService(raise_exc=RuntimeError("provider unavailable"))
    bridge = TodoAgentTaskBridge(
        todo_service=todo_service, agent_task_service=agent_tasks, agent_task_submission_service=submission_service,
    )

    result = await bridge.launch_todo_item_agent_task(todo_id=detail.id)

    assert result["success"] is False
    assert "provider unavailable" in result["error"]
    refetched = await todo_service.get_item_detail(detail.id)
    assert refetched.status == "open"  # unchanged; the failure was recorded as an event, not a transition


@pytest.mark.asyncio
async def test_launch_todo_item_agent_task_handles_rejected_submission(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    detail = await todo_service.create_manual_todo(
        title="Submission rejected", description="", notes="", responsibility="agent", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={},
    )
    submission_service = FakeAgentTaskSubmissionService(
        result={"success": False, "operation": "error", "message": "rate limited"}
    )
    bridge = TodoAgentTaskBridge(
        todo_service=todo_service, agent_task_service=agent_tasks, agent_task_submission_service=submission_service,
    )

    result = await bridge.launch_todo_item_agent_task(todo_id=detail.id)

    assert result == {"success": False, "error": "rate limited"}


@pytest.mark.asyncio
async def test_launch_multiple_direct_origin_worker_agent_tasks_for_the_same_todo(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    """A single To-Do may require more than one worker Agent Task (retry
    after partial failure, or genuinely multi-step completion)."""
    detail = await todo_service.create_manual_todo(
        title="Needs two attempts", description="", notes="", responsibility="agent", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={},
    )
    submission_service = FakeAgentTaskSubmissionService(result={"success": True})
    bridge = TodoAgentTaskBridge(
        todo_service=todo_service, agent_task_service=agent_tasks, agent_task_submission_service=submission_service,
    )

    first = await bridge.launch_todo_item_agent_task(todo_id=detail.id)
    second = await bridge.launch_todo_item_agent_task(todo_id=detail.id)

    assert first["success"] is True
    assert second["success"] is True
    assert first["agent_task_id"] != second["agent_task_id"]
    assert len(submission_service.calls) == 2


@pytest.mark.asyncio
async def test_handle_terminal_event_for_todo_origin_reconciles_the_todo(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    detail = await todo_service.create_manual_todo(
        title="Worker finished", description="", notes="", responsibility="agent", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={},
    )

    class Task:
        id = "worker-1"
        status = "completed"
        origin_type = "todo"
        origin_id = detail.id
        result_data = {"message": "Done."}
        accumulated_artifacts = {}

    agent_tasks.tasks["worker-1"] = Task()
    agent_tasks._by_origin.append(Task())
    submission_service = FakeAgentTaskSubmissionService()
    bridge = TodoAgentTaskBridge(
        todo_service=todo_service, agent_task_service=agent_tasks, agent_task_submission_service=submission_service,
    )

    await bridge.handle_terminal_event("worker-1")

    refetched = await todo_service.get_item_detail(detail.id)
    assert refetched.status == "ready_for_review"
    assert submission_service.broadcasts == []  # todo-origin never broadcasts a workspace result


@pytest.mark.asyncio
async def test_handle_terminal_event_for_missing_agent_task_is_a_noop(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    submission_service = FakeAgentTaskSubmissionService()
    bridge = TodoAgentTaskBridge(
        todo_service=todo_service, agent_task_service=agent_tasks, agent_task_submission_service=submission_service,
    )
    await bridge.handle_terminal_event("does-not-exist")  # must not raise
    assert submission_service.broadcasts == []


@pytest.mark.asyncio
async def test_handle_terminal_event_for_todo_workspace_origin_broadcasts_and_does_not_mutate_any_todo(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    """Proves a workspace-manager terminal result is correlated to the
    correct workspace and request but never mutates a To-Do absent an
    explicit tool call: no `append_todo_note`/`delegate_todo_work` tool ran,
    so the selected To-Do's status/notes/revision must be unchanged."""
    selected = await todo_service.create_manual_todo(
        title="Selected in this workspace turn", description="", notes="original notes", responsibility="user",
        priority="normal", due_at=None, idempotency_key=None, payload_for_hash={},
    )

    class ManagerTask:
        id = "manager-1"
        status = "completed"
        origin_type = "todo_workspace"
        origin_id = "workspace-abc"
        result_data = {"message": "Here is the status you asked about."}
        accumulated_artifacts = {
            "todo_workspace_context": {
                "workspace_id": "workspace-abc",
                "request_id": "request-1",
                "selection_ids": [selected.id],
            }
        }

    agent_tasks.tasks["manager-1"] = ManagerTask()
    submission_service = FakeAgentTaskSubmissionService()
    bridge = TodoAgentTaskBridge(
        todo_service=todo_service, agent_task_service=agent_tasks, agent_task_submission_service=submission_service,
    )

    await bridge.handle_terminal_event("manager-1")

    assert len(submission_service.broadcasts) == 1
    broadcast = submission_service.broadcasts[0]
    assert broadcast["event_type"] == "todo_workspace_result"
    assert broadcast["workspace_id"] == "workspace-abc"
    assert broadcast["request_id"] == "request-1"
    assert broadcast["selected_todo_ids"] == [selected.id]
    assert broadcast["summary"] == "Here is the status you asked about."

    unchanged = await todo_service.get_item_detail(selected.id)
    assert unchanged.status == "open"
    assert unchanged.notes == "original notes"
    assert unchanged.revision == 1


@pytest.mark.asyncio
async def test_handle_terminal_event_for_todo_workspace_origin_without_context_does_not_broadcast(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    """A manager task somehow missing its `todo_workspace_context` (e.g.
    malformed accumulated_artifacts) must not crash or emit a malformed event."""

    class ManagerTask:
        id = "manager-2"
        status = "failed"
        origin_type = "todo_workspace"
        origin_id = "workspace-xyz"
        result_data = {}
        accumulated_artifacts = {}

    agent_tasks.tasks["manager-2"] = ManagerTask()
    submission_service = FakeAgentTaskSubmissionService()
    bridge = TodoAgentTaskBridge(
        todo_service=todo_service, agent_task_service=agent_tasks, agent_task_submission_service=submission_service,
    )

    await bridge.handle_terminal_event("manager-2")

    assert submission_service.broadcasts == []
