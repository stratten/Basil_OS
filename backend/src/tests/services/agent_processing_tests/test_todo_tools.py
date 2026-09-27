"""To-Do Agent Task tool coverage: generic creation, workspace-scoped
note/delegate authorization (in-selection vs. out-of-selection vs. no
workspace context at all), and rejection of generic (non-workspace) mutation
attempts."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from api.services.agent_processing.lifecycle.execution_graph.service_tooling.optional_tool_registry import (
    register_optional_tools,
)
from api.services.todos.repository import TodoRepository
from api.services.todos.service import TodoService
from api.services.todos.tools import create_todo_tools


class _RegistryLogger:
    def info(self, *args: Any, **kwargs: Any) -> None:
        pass

    def warning(self, *args: Any, **kwargs: Any) -> None:
        pass


class FakeAgentTaskLookup:
    def __init__(self) -> None:
        self.tasks: Dict[str, Any] = {}

    async def list_agent_tasks_by_origin(self, origin_type: str, origin_id: str, include_terminal: bool = True):
        return []

    async def list_nonterminal_agent_tasks_by_origin_type(self, origin_type: str):
        return []

    async def get_agent_task(self, agent_task_id: str):
        return self.tasks.get(agent_task_id)


class GenericAgentTask:
    """A normal (non-workspace) Agent Task: no `todo_workspace_context`."""

    origin_type = None
    accumulated_artifacts: Dict[str, Any] = {}


class DirectOriginWorkerAgentTask:
    """A direct-origin ("todo") worker Agent Task, launched for exactly one To-Do."""

    def __init__(self, origin_id: str) -> None:
        self.origin_type = "todo"
        self.origin_id = origin_id
        self.accumulated_artifacts: Dict[str, Any] = {}


class WorkspaceAgentTask:
    def __init__(self, selection_ids: List[str]) -> None:
        self.origin_type = "todo_workspace"
        self.accumulated_artifacts = {
            "todo_workspace_context": {
                "workspace_id": "ws-1", "request_id": "req-1", "selection_ids": selection_ids,
            }
        }


@pytest.fixture
def agent_tasks() -> FakeAgentTaskLookup:
    return FakeAgentTaskLookup()


@pytest.fixture
def todo_service(tmp_path: Path, agent_tasks: FakeAgentTaskLookup) -> TodoService:
    return TodoService(repository=TodoRepository(str(tmp_path / "tools.db")), agent_task_service=agent_tasks)


def test_optional_registry_uses_todo_service_agent_task_lookup(
    todo_service: TodoService,
) -> None:
    tools = []
    tool_map = {}
    optional_warnings = []
    factory = SimpleNamespace(
        logger=_RegistryLogger(),
        profile=None,
        todo_service=todo_service,
        current_agent_task_id="manager-1",
        agent_task_submission_service=SimpleNamespace(),
    )

    register_optional_tools(factory, tools, tool_map, optional_warnings)

    assert tool_map["todos.append_todo_note"].name == "append_todo_note"
    assert not any("To-Do tools" in warning for warning in optional_warnings)


async def _successful_launcher(*, todo_id: str) -> Dict[str, Any]:
    return {"success": True, "agent_task_id": "worker-99"}


@pytest.mark.asyncio
async def test_create_todos_tool_creates_an_open_todo_when_an_agent_task_context_exists(
    todo_service: TodoService,
) -> None:
    tools = create_todo_tools(
        todo_service=todo_service, agent_task_id="task-1", agent_task_provider=None, launcher=None,
    )
    create_tool = next(t for t in tools if t.name == "create_todos")

    result = await create_tool.ainvoke({"title": "Follow up on invoice", "description": "From the call"})

    assert result["success"] is True
    assert result["title"] == "Follow up on invoice"
    listed = await todo_service.list_item_summaries(status=None, limit=10, cursor=None)
    assert listed[0][0].title == "Follow up on invoice"


@pytest.mark.asyncio
async def test_create_todos_tool_creates_a_candidate_from_a_workspace_manager(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    agent_tasks.tasks["manager-creation"] = WorkspaceAgentTask(selection_ids=["selected-todo"])
    tools = create_todo_tools(
        todo_service=todo_service, agent_task_id="manager-creation", agent_task_provider=agent_tasks, launcher=None,
    )
    create_tool = next(t for t in tools if t.name == "create_todos")

    result = await create_tool.ainvoke({"title": "Confirm the proposed follow-up"})

    assert result["success"] is True
    assert result["status"] == "candidate"


@pytest.mark.asyncio
async def test_create_todos_tool_creates_a_candidate_from_an_empty_workspace_selection(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    agent_tasks.tasks["manager-empty-selection"] = WorkspaceAgentTask(selection_ids=[])
    tools = create_todo_tools(
        todo_service=todo_service,
        agent_task_id="manager-empty-selection",
        agent_task_provider=agent_tasks,
        launcher=None,
    )
    create_tool = next(tool for tool in tools if tool.name == "create_todos")

    result = await create_tool.ainvoke({"title": "Review attached action items"})

    assert result["success"] is True
    assert result["title"] == "Review attached action items"
    assert result["status"] == "candidate"


@pytest.mark.asyncio
async def test_create_todos_tool_without_an_active_agent_task_context_fails_cleanly(
    todo_service: TodoService,
) -> None:
    tools = create_todo_tools(todo_service=todo_service, agent_task_id=None, agent_task_provider=None, launcher=None)
    create_tool = next(t for t in tools if t.name == "create_todos")

    result = await create_tool.ainvoke({"title": "No context"})

    assert result["success"] is False
    assert "active Agent Task context" in result["error"]


@pytest.mark.asyncio
async def test_list_todos_tool_filters_by_status(todo_service: TodoService) -> None:
    await todo_service.create_manual_todo(
        title="Open one", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    tools = create_todo_tools(todo_service=todo_service, agent_task_id="task-1", agent_task_provider=None, launcher=None)
    list_tool = next(t for t in tools if t.name == "list_todos")

    result = await list_tool.ainvoke({"status": "open"})

    assert len(result["items"]) == 1
    assert result["items"][0]["status"] == "open"


@pytest.mark.asyncio
async def test_inspect_todo_tool_returns_full_detail(todo_service: TodoService) -> None:
    detail = await todo_service.create_manual_todo(
        title="Inspect me", description="details", notes="some notes", responsibility="user", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={},
    )
    tools = create_todo_tools(todo_service=todo_service, agent_task_id="task-1", agent_task_provider=None, launcher=None)
    inspect_tool = next(t for t in tools if t.name == "inspect_todo")

    result = await inspect_tool.ainvoke({"todo_id": detail.id})

    assert result["id"] == detail.id
    assert result["notes"] == "some notes"


@pytest.mark.asyncio
async def test_append_todo_note_tool_succeeds_for_a_todo_in_the_current_workspace_selection(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    detail = await todo_service.create_manual_todo(
        title="Selected item", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    agent_tasks.tasks["manager-1"] = WorkspaceAgentTask(selection_ids=[detail.id])
    tools = create_todo_tools(
        todo_service=todo_service, agent_task_id="manager-1", agent_task_provider=agent_tasks, launcher=None,
    )
    note_tool = next(t for t in tools if t.name == "append_todo_note")

    result = await note_tool.ainvoke({"todo_id": detail.id, "note_markdown": "Found the invoice."})

    assert result["success"] is True
    assert "Found the invoice." in result["notes"]


@pytest.mark.asyncio
async def test_append_todo_note_tool_rejects_a_todo_outside_the_current_selection(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    selected = await todo_service.create_manual_todo(
        title="Selected", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={"t": "selected"},
    )
    outside = await todo_service.create_manual_todo(
        title="Not selected", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={"t": "outside"},
    )
    agent_tasks.tasks["manager-2"] = WorkspaceAgentTask(selection_ids=[selected.id])
    tools = create_todo_tools(
        todo_service=todo_service, agent_task_id="manager-2", agent_task_provider=agent_tasks, launcher=None,
    )
    note_tool = next(t for t in tools if t.name == "append_todo_note")

    result = await note_tool.ainvoke({"todo_id": outside.id, "note_markdown": "Should be rejected."})

    assert result["success"] is False
    assert "not in this turn's selected" in result["error"]
    unchanged = await todo_service.get_item_detail(outside.id)
    assert unchanged.notes == ""


@pytest.mark.asyncio
async def test_append_todo_note_tool_rejects_a_generic_non_workspace_agent_task(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    """A regular (non-workspace) Agent Task must never be able to append a
    workspace-scoped note, even to a To-Do it happens to know the id of."""
    detail = await todo_service.create_manual_todo(
        title="Some item", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    agent_tasks.tasks["generic-task-1"] = GenericAgentTask()
    tools = create_todo_tools(
        todo_service=todo_service, agent_task_id="generic-task-1", agent_task_provider=agent_tasks, launcher=None,
    )
    note_tool = next(t for t in tools if t.name == "append_todo_note")

    result = await note_tool.ainvoke({"todo_id": detail.id, "note_markdown": "Should be rejected."})

    assert result["success"] is False
    assert "only available from a To-Do workspace turn or a direct-origin To-Do worker" in result["error"]


@pytest.mark.asyncio
async def test_append_todo_note_tool_succeeds_for_a_direct_origin_worker_on_its_own_todo(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    detail = await todo_service.create_manual_todo(
        title="Worker's own item", description="", notes="", responsibility="agent", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={},
    )
    agent_tasks.tasks["worker-1"] = DirectOriginWorkerAgentTask(origin_id=detail.id)
    tools = create_todo_tools(
        todo_service=todo_service, agent_task_id="worker-1", agent_task_provider=agent_tasks, launcher=None,
    )
    note_tool = next(t for t in tools if t.name == "append_todo_note")

    result = await note_tool.ainvoke({"todo_id": detail.id, "note_markdown": "Attempted findings appended directly."})

    assert result["success"] is True
    assert "Attempted findings appended directly." in result["notes"]


@pytest.mark.asyncio
async def test_append_todo_note_tool_rejects_a_direct_origin_worker_targeting_a_different_todo(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    own_todo = await todo_service.create_manual_todo(
        title="Worker's own item", description="", notes="", responsibility="agent", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={"t": "own"},
    )
    other_todo = await todo_service.create_manual_todo(
        title="A different item", description="", notes="", responsibility="agent", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={"t": "other"},
    )
    agent_tasks.tasks["worker-2"] = DirectOriginWorkerAgentTask(origin_id=own_todo.id)
    tools = create_todo_tools(
        todo_service=todo_service, agent_task_id="worker-2", agent_task_provider=agent_tasks, launcher=None,
    )
    note_tool = next(t for t in tools if t.name == "append_todo_note")

    result = await note_tool.ainvoke({"todo_id": other_todo.id, "note_markdown": "Should be rejected."})

    assert result["success"] is False
    assert "is not the To-Do this Agent Task was launched for" in result["error"]
    unchanged = await todo_service.get_item_detail(other_todo.id)
    assert unchanged.notes == ""


@pytest.mark.asyncio
async def test_attach_todo_reference_tool_succeeds_for_a_todo_in_current_workspace_selection(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    detail = await todo_service.create_manual_todo(
        title="Selected item", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    agent_tasks.tasks["reference-manager"] = WorkspaceAgentTask(selection_ids=[detail.id])
    tools = create_todo_tools(
        todo_service=todo_service, agent_task_id="reference-manager", agent_task_provider=agent_tasks, launcher=None,
    )
    attach_tool = next(tool for tool in tools if tool.name == "attach_todo_reference")

    result = await attach_tool.ainvoke({"todo_id": detail.id, "path": "/tmp/project/brief.pdf"})

    assert result["success"] is True
    assert result["references"][0]["path"] == "/tmp/project/brief.pdf"


@pytest.mark.asyncio
async def test_attach_todo_reference_tool_rejects_generic_and_out_of_selection_agent_tasks(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    selected = await todo_service.create_manual_todo(
        title="Selected", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={"t": "selected"},
    )
    outside = await todo_service.create_manual_todo(
        title="Outside", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={"t": "outside"},
    )
    agent_tasks.tasks["generic-reference"] = GenericAgentTask()
    generic_tools = create_todo_tools(
        todo_service=todo_service, agent_task_id="generic-reference", agent_task_provider=agent_tasks, launcher=None,
    )
    generic_result = await next(tool for tool in generic_tools if tool.name == "attach_todo_reference").ainvoke(
        {"todo_id": selected.id, "path": "/tmp/project/brief.pdf"}
    )
    agent_tasks.tasks["selection-reference"] = WorkspaceAgentTask(selection_ids=[selected.id])
    selection_tools = create_todo_tools(
        todo_service=todo_service, agent_task_id="selection-reference", agent_task_provider=agent_tasks, launcher=None,
    )
    selection_result = await next(tool for tool in selection_tools if tool.name == "attach_todo_reference").ainvoke(
        {"todo_id": outside.id, "path": "/tmp/project/brief.pdf"}
    )

    assert generic_result["success"] is False
    assert "only available from a To-Do workspace turn or a direct-origin To-Do worker" in generic_result["error"]
    assert selection_result["success"] is False
    assert "not in this turn's selected" in selection_result["error"]


@pytest.mark.asyncio
async def test_attach_todo_reference_tool_allows_direct_worker_only_on_its_own_todo(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    own_todo = await todo_service.create_manual_todo(
        title="Worker's own item", description="", notes="", responsibility="agent", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={"t": "own"},
    )
    other_todo = await todo_service.create_manual_todo(
        title="Other item", description="", notes="", responsibility="agent", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={"t": "other"},
    )
    agent_tasks.tasks["reference-worker"] = DirectOriginWorkerAgentTask(origin_id=own_todo.id)
    tools = create_todo_tools(
        todo_service=todo_service, agent_task_id="reference-worker", agent_task_provider=agent_tasks, launcher=None,
    )
    attach_tool = next(tool for tool in tools if tool.name == "attach_todo_reference")

    own_result = await attach_tool.ainvoke({"todo_id": own_todo.id, "path": "/tmp/project/brief.pdf"})
    other_result = await attach_tool.ainvoke({"todo_id": other_todo.id, "path": "/tmp/project/other.pdf"})

    assert own_result["success"] is True
    assert other_result["success"] is False
    assert "is not the To-Do this Agent Task was launched for" in other_result["error"]


@pytest.mark.asyncio
async def test_delegate_todo_work_tool_succeeds_for_a_selected_todo_and_invokes_the_launcher(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    detail = await todo_service.create_manual_todo(
        title="Delegate me", description="", notes="", responsibility="agent", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    agent_tasks.tasks["manager-3"] = WorkspaceAgentTask(selection_ids=[detail.id])
    tools = create_todo_tools(
        todo_service=todo_service, agent_task_id="manager-3", agent_task_provider=agent_tasks,
        launcher=_successful_launcher,
    )
    delegate_tool = next(t for t in tools if t.name == "delegate_todo_work")

    result = await delegate_tool.ainvoke({"todo_id": detail.id})

    assert result["success"] is True
    assert result["agent_task_id"] == "worker-99"


@pytest.mark.asyncio
async def test_delegate_todo_work_tool_rejects_a_todo_outside_the_current_selection(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    selected = await todo_service.create_manual_todo(
        title="Selected", description="", notes="", responsibility="agent", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={"t": "sel"},
    )
    outside = await todo_service.create_manual_todo(
        title="Not selected", description="", notes="", responsibility="agent", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={"t": "out"},
    )
    agent_tasks.tasks["manager-4"] = WorkspaceAgentTask(selection_ids=[selected.id])
    tools = create_todo_tools(
        todo_service=todo_service, agent_task_id="manager-4", agent_task_provider=agent_tasks,
        launcher=_successful_launcher,
    )
    delegate_tool = next(t for t in tools if t.name == "delegate_todo_work")

    result = await delegate_tool.ainvoke({"todo_id": outside.id})

    assert result["success"] is False
    assert "not in this turn's selected" in result["error"]


@pytest.mark.asyncio
async def test_delegate_todo_work_tool_surfaces_a_launcher_failure(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    detail = await todo_service.create_manual_todo(
        title="Delegate but fails", description="", notes="", responsibility="agent", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={},
    )
    agent_tasks.tasks["manager-5"] = WorkspaceAgentTask(selection_ids=[detail.id])

    async def failing_launcher(*, todo_id: str) -> Dict[str, Any]:
        return {"success": False, "error": "no provider available"}

    tools = create_todo_tools(
        todo_service=todo_service, agent_task_id="manager-5", agent_task_provider=agent_tasks,
        launcher=failing_launcher,
    )
    delegate_tool = next(t for t in tools if t.name == "delegate_todo_work")

    result = await delegate_tool.ainvoke({"todo_id": detail.id})

    assert result["success"] is False
    assert result["error"] == "no provider available"


@pytest.mark.asyncio
async def test_create_todos_tool_with_malformed_args_is_rejected_by_the_schema(todo_service: TodoService) -> None:
    """`title` is required by `CreateTodosArgs`; a missing title must be
    rejected by LangChain's Pydantic validation before the closure runs."""
    tools = create_todo_tools(todo_service=todo_service, agent_task_id="task-1", agent_task_provider=None, launcher=None)
    create_tool = next(t for t in tools if t.name == "create_todos")

    with pytest.raises(Exception):
        await create_tool.ainvoke({})
