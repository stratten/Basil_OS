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
from api.services.agent_processing.tools.safety import execution_approval_service
from api.services.todos import agent_approval, tools as todo_tools_module
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
async def test_append_todo_note_tool_lets_a_regular_agent_task_note_an_existing_todo(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    """A regular (non-workspace) Agent Task may record progress on an existing To-Do instead of creating a duplicate."""
    detail = await todo_service.create_manual_todo(
        title="Some item", description="", notes="", responsibility="user", priority="normal", due_at=None,
        idempotency_key=None, payload_for_hash={},
    )
    agent_tasks.tasks["generic-task-1"] = GenericAgentTask()
    tools = create_todo_tools(
        todo_service=todo_service, agent_task_id="generic-task-1", agent_task_provider=agent_tasks, launcher=None,
    )
    note_tool = next(t for t in tools if t.name == "append_todo_note")

    result = await note_tool.ainvoke({"todo_id": detail.id, "note_markdown": "Sent the email; waiting on a reply."})

    assert result["success"] is True
    assert "Sent the email; waiting on a reply." in result["notes"]


@pytest.mark.asyncio
async def test_append_todo_note_tool_reports_a_missing_todo_and_a_missing_task_context(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    agent_tasks.tasks["generic-task-2"] = GenericAgentTask()
    tools = create_todo_tools(
        todo_service=todo_service, agent_task_id="generic-task-2", agent_task_provider=agent_tasks, launcher=None,
    )
    missing = await next(t for t in tools if t.name == "append_todo_note").ainvoke(
        {"todo_id": "no-such-todo", "note_markdown": "Hello"}
    )
    no_context_tools = create_todo_tools(todo_service=todo_service, agent_task_id=None, agent_task_provider=None, launcher=None)
    no_context = await next(t for t in no_context_tools if t.name == "append_todo_note").ainvoke(
        {"todo_id": "no-such-todo", "note_markdown": "Hello"}
    )

    assert missing == {"success": False, "error": "To-Do no-such-todo was not found"}
    assert no_context["success"] is False
    assert "active Agent Task context" in no_context["error"]


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
async def test_attach_todo_reference_tool_allows_generic_tasks_but_keeps_workspace_selection_scope(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup, tmp_path: Path,
) -> None:
    brief = tmp_path / "brief.pdf"
    brief.write_text("brief")
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
        {"todo_id": selected.id, "path": str(brief)}
    )
    agent_tasks.tasks["selection-reference"] = WorkspaceAgentTask(selection_ids=[selected.id])
    selection_tools = create_todo_tools(
        todo_service=todo_service, agent_task_id="selection-reference", agent_task_provider=agent_tasks, launcher=None,
    )
    selection_result = await next(tool for tool in selection_tools if tool.name == "attach_todo_reference").ainvoke(
        {"todo_id": outside.id, "path": str(brief)}
    )

    assert generic_result["success"] is True
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


async def _todo(todo_service: TodoService, title: str = "Follow up on the order", **extra: Any):
    return await todo_service.create_manual_todo(
        title=title, description="Original description", notes="", responsibility="user", priority="normal",
        due_at=None, idempotency_key=None, payload_for_hash={"t": title}, **extra,
    )


def _tools_for(todo_service: TodoService, agent_tasks: FakeAgentTaskLookup, task_id: str = "generic-edit", task: Any = None):
    agent_tasks.tasks[task_id] = task or GenericAgentTask()
    tools = create_todo_tools(
        todo_service=todo_service, agent_task_id=task_id, agent_task_provider=agent_tasks, launcher=None,
    )
    return {tool.name: tool for tool in tools}


@pytest.fixture
def approval_requests(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    """Replaces the user approval with a scripted answer and records what was asked."""
    state: Dict[str, Any] = {"answer": True, "calls": []}

    async def fake_request(*, todo_id: str, title: str, status: str, agent_task_id: Optional[str]):
        state["calls"].append({"todo_id": todo_id, "title": title, "status": status, "agent_task_id": agent_task_id})
        return state["answer"], "The user approved." if state["answer"] else "The user did not approve (denied), so the To-Do was not changed."

    monkeypatch.setattr(todo_tools_module, "request_todo_status_approval", fake_request)
    return state


@pytest.mark.asyncio
async def test_update_todo_edits_only_the_fields_passed_and_records_the_agent_as_the_actor(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    detail = await _todo(todo_service)
    tools = _tools_for(todo_service, agent_tasks)

    result = await tools["update_todo"].ainvoke(
        {"todo_id": detail.id, "title": "Confirm the phone number", "priority": "high", "due_at": "2026-11-09"}
    )

    assert result["success"] is True
    assert result["title"] == "Confirm the phone number"
    assert result["priority"] == "high"
    assert result["due_at"] == "2026-11-09"
    assert result["description"] == "Original description"
    stored = await todo_service.get_item_detail(detail.id)
    assert stored.title == "Confirm the phone number"
    assert stored.description == "Original description"
    with todo_service.repository._connection() as connection:
        actors = [row[0] for row in connection.execute("SELECT actor_kind FROM todo_events WHERE todo_id = ? AND event_kind = 'updated'", (detail.id,))]
    assert actors == ["agent"]


@pytest.mark.asyncio
async def test_update_todo_can_clear_the_due_date_and_rejects_empty_or_invalid_edits(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    detail = await _todo(todo_service)
    tools = _tools_for(todo_service, agent_tasks)
    await tools["update_todo"].ainvoke({"todo_id": detail.id, "due_at": "2026-11-09"})

    cleared = await tools["update_todo"].ainvoke({"todo_id": detail.id, "due_at": ""})
    nothing = await tools["update_todo"].ainvoke({"todo_id": detail.id})
    bad_priority = await tools["update_todo"].ainvoke({"todo_id": detail.id, "priority": "urgent-ish"})
    missing = await tools["update_todo"].ainvoke({"todo_id": "no-such-todo", "title": "x"})

    assert cleared["success"] is True and cleared["due_at"] is None
    assert nothing["success"] is False and "at least one of" in nothing["error"]
    assert bad_priority["success"] is False
    assert missing == {"success": False, "error": "To-Do no-such-todo was not found"}
    assert (await todo_service.get_item_detail(detail.id)).priority == "normal"


@pytest.mark.asyncio
async def test_update_todo_keeps_workspace_and_worker_scope(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup,
) -> None:
    selected = await _todo(todo_service, "Selected")
    outside = await _todo(todo_service, "Outside")
    workspace = _tools_for(todo_service, agent_tasks, "ws-edit", WorkspaceAgentTask(selection_ids=[selected.id]))
    worker = _tools_for(todo_service, agent_tasks, "worker-edit", DirectOriginWorkerAgentTask(origin_id=selected.id))

    assert (await workspace["update_todo"].ainvoke({"todo_id": selected.id, "title": "Renamed"}))["success"] is True
    blocked = await workspace["update_todo"].ainvoke({"todo_id": outside.id, "title": "Nope"})
    worker_blocked = await worker["update_todo"].ainvoke({"todo_id": outside.id, "title": "Nope"})

    assert "not in this turn's selected" in blocked["error"]
    assert "not the To-Do this Agent Task was launched for" in worker_blocked["error"]
    assert (await todo_service.get_item_detail(outside.id)).title == "Outside"


@pytest.mark.asyncio
async def test_set_todo_status_applies_working_states_without_asking(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup, approval_requests: Dict[str, Any],
) -> None:
    detail = await _todo(todo_service)
    tools = _tools_for(todo_service, agent_tasks)

    started = await tools["set_todo_status"].ainvoke({"todo_id": detail.id, "status": "in_progress"})
    review = await tools["set_todo_status"].ainvoke({"todo_id": detail.id, "status": " Ready_For_Review "})
    same = await tools["set_todo_status"].ainvoke({"todo_id": detail.id, "status": "ready_for_review"})

    assert started == {"success": True, "todo_id": detail.id, "status": "in_progress", "changed": True}
    assert review["status"] == "ready_for_review" and review["changed"] is True
    assert same["changed"] is False
    assert approval_requests["calls"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "dismissed", "canceled"])
async def test_set_todo_status_asks_before_closing_out_and_applies_it_once_approved(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup, approval_requests: Dict[str, Any], status: str,
) -> None:
    detail = await _todo(todo_service)
    tools = _tools_for(todo_service, agent_tasks)

    result = await tools["set_todo_status"].ainvoke({"todo_id": detail.id, "status": status})

    assert result == {"success": True, "todo_id": detail.id, "status": status, "changed": True}
    assert approval_requests["calls"] == [
        {"todo_id": detail.id, "title": "Follow up on the order", "status": status, "agent_task_id": "generic-edit"}
    ]
    stored = await todo_service.get_item_detail(detail.id)
    assert stored.status == status
    if status == "completed":
        assert stored.completed_at
    with todo_service.repository._connection() as connection:
        actors = [row[0] for row in connection.execute("SELECT actor_kind FROM todo_events WHERE todo_id = ? AND event_kind = 'status_set'", (detail.id,))]
    assert actors == ["agent"]


@pytest.mark.asyncio
async def test_set_todo_status_leaves_the_todo_alone_when_the_user_declines(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup, approval_requests: Dict[str, Any],
) -> None:
    detail = await _todo(todo_service)
    approval_requests["answer"] = False
    tools = _tools_for(todo_service, agent_tasks)

    result = await tools["set_todo_status"].ainvoke({"todo_id": detail.id, "status": "completed"})

    assert result["success"] is False and result["approved"] is False
    assert "did not approve" in result["error"]
    assert (await todo_service.get_item_detail(detail.id)).status == "open"


@pytest.mark.asyncio
async def test_set_todo_status_rejects_unknown_statuses_and_out_of_scope_todos(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup, approval_requests: Dict[str, Any],
) -> None:
    selected = await _todo(todo_service, "Selected")
    outside = await _todo(todo_service, "Outside")
    workspace = _tools_for(todo_service, agent_tasks, "ws-status", WorkspaceAgentTask(selection_ids=[selected.id]))
    generic = _tools_for(todo_service, agent_tasks, "generic-status")

    candidate = await generic["set_todo_status"].ainvoke({"todo_id": selected.id, "status": "candidate"})
    nonsense = await generic["set_todo_status"].ainvoke({"todo_id": selected.id, "status": "finished-ish"})
    blocked = await workspace["set_todo_status"].ainvoke({"todo_id": outside.id, "status": "completed"})

    assert candidate["success"] is False and "status must be one of" in candidate["error"]
    assert nonsense["success"] is False
    assert "not in this turn's selected" in blocked["error"]
    assert approval_requests["calls"] == []
    assert (await todo_service.get_item_detail(outside.id)).status == "open"


@pytest.mark.asyncio
async def test_a_closed_todo_can_be_reopened_without_asking(
    todo_service: TodoService, agent_tasks: FakeAgentTaskLookup, approval_requests: Dict[str, Any],
) -> None:
    detail = await _todo(todo_service)
    tools = _tools_for(todo_service, agent_tasks)
    await tools["set_todo_status"].ainvoke({"todo_id": detail.id, "status": "completed"})
    approval_requests["calls"].clear()

    reopened = await tools["set_todo_status"].ainvoke({"todo_id": detail.id, "status": "open"})

    assert reopened["status"] == "open"
    assert approval_requests["calls"] == []
    assert (await todo_service.get_item_detail(detail.id)).completed_at is None


def test_the_approval_card_names_the_action_and_the_todo() -> None:
    command = agent_approval.todo_status_approval_command("abc-123", "Follow up\n  on   the order " + "x" * 200, "dismissed")

    assert command.startswith('Basil To-Do: dismiss "Follow up on the order xxx')
    assert command.endswith('" (abc-123)')
    assert "\n" not in command
    assert len(command) < 200


class _FakeApprovalService:
    answers: Dict[str, Any] = {}
    seen: List[Any] = []

    def __init__(self, websocket_manager: Any = None) -> None:
        self.websocket_manager = websocket_manager

    async def request_approval_with_outcome(self, command: str, context: Optional[Dict[str, Any]] = None):
        _FakeApprovalService.seen.append((command, dict(context or {})))
        return _FakeApprovalService.answers["outcome"]


@pytest.mark.asyncio
async def test_the_approval_request_uses_the_shared_approval_flow_and_is_never_rememberable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.services.agent_processing.tools.safety.models import ExecutionApprovalOutcome

    monkeypatch.setattr(execution_approval_service, "ExecutionApprovalService", _FakeApprovalService)
    _FakeApprovalService.seen = []
    _FakeApprovalService.answers["outcome"] = ExecutionApprovalOutcome(approved=True)

    approved, reason = await agent_approval.request_todo_status_approval(
        todo_id="abc-123", title="Order", status="completed", agent_task_id="task-9",
    )

    assert approved is True and reason == "The user approved."
    command, context = _FakeApprovalService.seen[0]
    assert command == 'Basil To-Do: complete "Order" (abc-123)'
    assert context["execution_type"] == agent_approval.APPROVAL_EXECUTION_TYPE
    assert context["agent_task_id"] == "task-9"
    assert context["source"] == "todo_tools"
    assert context["purpose"] == 'The agent wants to complete your To-Do "Order". Nothing changes on the To-Do unless you approve.'
    assert context["purpose_source"] == "basil"

    _FakeApprovalService.answers["outcome"] = ExecutionApprovalOutcome(approved=False, status="approval_timed_out")
    denied, denied_reason = await agent_approval.request_todo_status_approval(
        todo_id="abc-123", title="Order", status="canceled", agent_task_id="task-9",
    )
    assert denied is False
    assert "approval_timed_out" in denied_reason


@pytest.mark.asyncio
async def test_an_approval_flow_that_raises_denies_instead_of_changing_the_todo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Raising(_FakeApprovalService):
        async def request_approval_with_outcome(self, command, context=None):
            raise RuntimeError("socket closed")

    monkeypatch.setattr(execution_approval_service, "ExecutionApprovalService", _Raising)

    approved, reason = await agent_approval.request_todo_status_approval(
        todo_id="abc-123", title="Order", status="dismissed", agent_task_id="task-9",
    )

    assert approved is False
    assert "was not changed" in reason


def test_the_registry_exposes_the_new_tools_and_the_family_catalog_names_them(todo_service: TodoService) -> None:
    from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_family_catalog import get_family_definitions

    tools: list = []
    tool_map: dict = {}
    factory = SimpleNamespace(
        logger=_RegistryLogger(), profile=None, todo_service=todo_service, current_agent_task_id="t-1",
        agent_task_submission_service=SimpleNamespace(),
    )
    register_optional_tools(factory, tools, tool_map, [])

    registered = {name.split(".", 1)[1] for name in tool_map if name.startswith("todos.")}
    family = next(family for family in get_family_definitions() if family.name == "todos")
    assert {"update_todo", "set_todo_status", "attach_todo_reference"} <= registered
    assert registered <= set(family.tool_names)
