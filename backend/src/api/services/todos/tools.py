"""Structured Agent Task tools for the To-Do domain, built as LangChain
`StructuredTool`s via closures over per-call context (todo_service,
agent_task_id, launcher), mirroring `service_tooling/memory_tools.py`."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from .agent_approval import APPROVAL_REQUIRED_TODO_STATUSES, request_todo_status_approval
from .service import TodoConflictError, TodoNotFoundError, TodoTransitionError

logger = logging.getLogger(__name__)

_AGENT_SETTABLE_PRIORITIES = frozenset({"low", "normal", "medium", "high"})

# Statuses an Agent Task may set. `candidate` is left out because it only means a suggestion the user has not accepted yet.
_AGENT_SETTABLE_STATUSES = frozenset({"open", "in_progress", "ready_for_review", "completed", "dismissed", "canceled"})


class CreateTodosArgs(BaseModel):
    title: str = Field(min_length=1, max_length=240, description="Short, action-oriented title for the To-Do.")
    description: str = Field(default="", max_length=12000, description="Optional longer description or context.")


class ListTodosArgs(BaseModel):
    status: Optional[str] = Field(
        default=None,
        description="Optional status filter: candidate, open, in_progress, ready_for_review, completed, dismissed, or canceled.",
    )


class InspectTodoArgs(BaseModel):
    todo_id: str = Field(description="The To-Do id to inspect.")


class AppendTodoNoteArgs(BaseModel):
    todo_id: str = Field(description="The To-Do id to append a note to. In a To-Do workspace turn it must be in the selection.")
    note_markdown: str = Field(min_length=1, max_length=12000, description="Markdown note text to append.")


class AttachTodoReferenceArgs(BaseModel):
    todo_id: str = Field(description="The To-Do id to attach the local path to. In a To-Do workspace turn it must be in the selection.")
    path: str = Field(description="Absolute local file or folder path to retain as a reference.")


class UpdateTodoArgs(BaseModel):
    todo_id: str = Field(description="The To-Do id to edit.")
    title: Optional[str] = Field(default=None, min_length=1, max_length=240, description="New title. Omit to keep the current one.")
    description: Optional[str] = Field(default=None, max_length=12000, description="New description, which replaces the current one. Omit to keep it.")
    priority: Optional[str] = Field(default=None, description="New priority: low, normal, or high. Omit to keep it.")
    due_at: Optional[str] = Field(default=None, description="New due date or date-time in ISO 8601 form, or an empty string to clear the due date. Omit to keep it.")


class SetTodoStatusArgs(BaseModel):
    todo_id: str = Field(description="The To-Do id whose status to change.")
    status: str = Field(
        description=(
            "New status: open, in_progress, ready_for_review, completed, dismissed, or canceled. "
            "completed, dismissed, and canceled each ask the user to approve first."
        ),
    )


class DelegateTodoWorkArgs(BaseModel):
    todo_id: str = Field(description="The To-Do id to launch a direct-origin worker Agent Task for. Must be in this turn's selection.")


def _workspace_selection_ids(agent_task: Any) -> Optional[List[str]]:
    artifacts = getattr(agent_task, "accumulated_artifacts", None) or {}
    if not isinstance(artifacts, dict):
        return None
    if getattr(agent_task, "origin_type", None) != "todo_workspace":
        return None
    context = artifacts.get("todo_workspace_context")
    if not isinstance(context, dict):
        return None
    selection = context.get("selection_ids")
    return selection if isinstance(selection, list) else None


def _direct_origin_todo_id(agent_task: Any) -> Optional[str]:
    """The one To-Do a direct-origin ("todo") worker Agent Task was spawned
    for, if any. Distinct from `_workspace_selection_ids`: a direct worker
    may act on exactly this one To-Do, never an arbitrary id it merely
    knows, and never any other To-Do."""
    if getattr(agent_task, "origin_type", None) != "todo":
        return None
    origin_id = getattr(agent_task, "origin_id", None)
    return origin_id if isinstance(origin_id, str) and origin_id else None


async def _current_agent_task(agent_task_provider: Any, agent_task_id: Optional[str]) -> Any:
    if agent_task_provider is None or not agent_task_id:
        return None
    return await agent_task_provider.get_agent_task(agent_task_id)


def create_todo_tools(
    *, todo_service: Any, agent_task_id: Optional[str], agent_task_provider: Any, launcher: Any,
) -> List[BaseTool]:
    """Build the To-Do tools for one Agent Task's tool set. `agent_task_id`
    and `agent_task_provider` are captured by closure so each tool call reads
    the *current* persisted Agent Task row (its `accumulated_artifacts` may
    change between tool calls within the same task, e.g. once workspace
    context is attached), rather than a snapshot taken at tool-creation time.
    """

    async def _scope_error(todo_id: str, tool_name: str) -> Optional[str]:
        """Why this Agent Task may not change that To-Do, or None when it may.

        A To-Do workspace turn may change only its selected To-Dos, and a direct-origin worker only the one it was launched for. Any other Agent Task may change any existing To-Do the user has, so a task that finds the To-Do it is working on can update it instead of creating a duplicate.
        """
        if not agent_task_id:
            return f"{tool_name} requires an active Agent Task context"
        agent_task = await _current_agent_task(agent_task_provider, agent_task_id)
        direct_todo_id = _direct_origin_todo_id(agent_task) if agent_task else None
        if direct_todo_id is not None:
            if todo_id != direct_todo_id:
                return f"{todo_id} is not the To-Do this Agent Task was launched for"
        else:
            selection = _workspace_selection_ids(agent_task) if agent_task else None
            if selection is not None and todo_id not in selection:
                return f"{todo_id} is not in this turn's selected To-Dos"
        try:
            await todo_service.get_item_detail(todo_id)
        except TodoNotFoundError:
            return f"To-Do {todo_id} was not found"
        return None

    async def create_todos(title: str, description: str = "") -> Dict[str, Any]:
        if not agent_task_id:
            return {"success": False, "error": "create_todos requires an active Agent Task context"}
        agent_task = await _current_agent_task(agent_task_provider, agent_task_id)
        status = "candidate" if _workspace_selection_ids(agent_task) is not None else "open"
        detail = await todo_service.create_todo_from_agent_tool(
            title=title, description=description, agent_task_id=agent_task_id,
            tool_call_id=f"call_{uuid.uuid4()}", excerpt=description[:500], status=status,
        )
        return {"success": True, "todo_id": detail.id, "title": detail.title, "status": detail.status}

    async def list_todos(status: Optional[str] = None) -> Dict[str, Any]:
        items, _cursor = await todo_service.list_item_summaries(status=status, limit=50, cursor=None)
        return {"items": [item.model_dump() for item in items]}

    async def inspect_todo(todo_id: str) -> Dict[str, Any]:
        detail = await todo_service.get_item_detail(todo_id)
        return detail.model_dump()

    async def append_todo_note(todo_id: str, note_markdown: str) -> Dict[str, Any]:
        error = await _scope_error(todo_id, "append_todo_note")
        if error:
            return {"success": False, "error": error}
        detail = await todo_service.append_workspace_manager_note(todo_id, note_markdown, agent_task_id)
        return {"success": True, "todo_id": detail.id, "notes": detail.notes}

    async def attach_todo_reference(todo_id: str, path: str) -> Dict[str, Any]:
        error = await _scope_error(todo_id, "attach_todo_reference")
        if error:
            return {"success": False, "error": error}
        detail = await todo_service.add_reference(todo_id, path, actor_agent_task_id=agent_task_id)
        return {
            "success": True,
            "todo_id": detail.id,
            "references": [reference.model_dump() for reference in detail.references],
        }

    async def update_todo(
        todo_id: str, title: Optional[str] = None, description: Optional[str] = None,
        priority: Optional[str] = None, due_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        error = await _scope_error(todo_id, "update_todo")
        if error:
            return {"success": False, "error": error}
        fields: Dict[str, Any] = {}
        if title is not None:
            fields["title"] = title
        if description is not None:
            fields["description"] = description
        if priority is not None:
            if priority.strip().lower() not in _AGENT_SETTABLE_PRIORITIES:
                return {"success": False, "error": "priority must be one of: high, low, normal"}
            fields["priority"] = priority
        if due_at is not None:
            fields["due_at"] = due_at.strip() or None
        if not fields:
            return {"success": False, "error": "update_todo needs at least one of title, description, priority, or due_at"}
        try:
            current = await todo_service.get_item_detail(todo_id)
            detail = await todo_service.update_fields(
                todo_id, current.revision, fields, actor_kind="agent", actor_id=agent_task_id,
            )
        except (TodoConflictError, TodoTransitionError, TodoNotFoundError, ValueError) as exc:
            return {"success": False, "error": str(exc)}
        return {
            "success": True, "todo_id": detail.id, "title": detail.title, "description": detail.description,
            "priority": detail.priority, "due_at": detail.due_at,
        }

    async def set_todo_status(todo_id: str, status: str) -> Dict[str, Any]:
        wanted = (status or "").strip().lower()
        if wanted not in _AGENT_SETTABLE_STATUSES:
            return {
                "success": False,
                "error": f"status must be one of: {', '.join(sorted(_AGENT_SETTABLE_STATUSES))}",
            }
        error = await _scope_error(todo_id, "set_todo_status")
        if error:
            return {"success": False, "error": error}
        try:
            current = await todo_service.get_item_detail(todo_id)
            if current.status == wanted:
                return {"success": True, "todo_id": current.id, "status": current.status, "changed": False}
            if wanted in APPROVAL_REQUIRED_TODO_STATUSES:
                approved, reason = await request_todo_status_approval(
                    todo_id=current.id, title=current.title, status=wanted, agent_task_id=agent_task_id,
                )
                if not approved:
                    return {"success": False, "approved": False, "error": reason}
                current = await todo_service.get_item_detail(todo_id)
            detail = await todo_service.set_status(
                todo_id, current.revision, wanted, actor_kind="agent", actor_id=agent_task_id,
            )
        except (TodoConflictError, TodoTransitionError, TodoNotFoundError) as exc:
            return {"success": False, "error": str(exc)}
        return {"success": True, "todo_id": detail.id, "status": detail.status, "changed": True}

    async def delegate_todo_work(todo_id: str) -> Dict[str, Any]:
        agent_task = await _current_agent_task(agent_task_provider, agent_task_id)
        selection = _workspace_selection_ids(agent_task) if agent_task else None
        if selection is None:
            return {"success": False, "error": "delegate_todo_work is only available from a To-Do workspace turn"}
        if todo_id not in selection:
            return {"success": False, "error": f"{todo_id} is not in this turn's selected To-Dos"}
        if launcher is None:
            return {"success": False, "error": "To-Do worker launcher is unavailable"}
        detail = await todo_service.get_item_detail(todo_id)
        result = await launcher(todo_id=todo_id)
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "delegation failed")}
        return {"success": True, "todo_id": detail.id, "agent_task_id": result.get("agent_task_id")}

    return [
        StructuredTool.from_function(
            func=create_todos, coroutine=create_todos, name="create_todos",
            description=(
                "Create one or more open To-Dos when the user explicitly asked to capture "
                "action items, or when your source material explicitly calls for it. "
                "Do not call this speculatively for every task you happen to perform."
            ),
            args_schema=CreateTodosArgs,
        ),
        StructuredTool.from_function(
            func=list_todos, coroutine=list_todos, name="list_todos",
            description="List current To-Dos, optionally filtered by status.",
            args_schema=ListTodosArgs,
        ),
        StructuredTool.from_function(
            func=inspect_todo, coroutine=inspect_todo, name="inspect_todo",
            description="Return one To-Do's current state, notes, sources, and worker history.",
            args_schema=InspectTodoArgs,
        ),
        StructuredTool.from_function(
            func=append_todo_note, coroutine=append_todo_note, name="append_todo_note",
            description=(
                "Append a timestamped note to an existing To-Do, for example to record progress or what is left "
                "to do, instead of creating a second To-Do about the same work. Use list_todos or inspect_todo "
                "first to find it. From a To-Do workspace turn it works on the selected To-Dos, and from a "
                "direct-origin worker on the one To-Do it was launched for."
            ),
            args_schema=AppendTodoNoteArgs,
        ),
        StructuredTool.from_function(
            func=attach_todo_reference, coroutine=attach_todo_reference, name="attach_todo_reference",
            description=(
                "Attach an absolute local file or folder path to an existing To-Do only when it is materially useful for that "
                "To-Do's work. This retains a path reference and does not grant access outside normal file-tool "
                "safety controls, allowed roots, or approval requirements."
            ),
            args_schema=AttachTodoReferenceArgs,
        ),
        StructuredTool.from_function(
            func=update_todo, coroutine=update_todo, name="update_todo",
            description=(
                "Edit an existing To-Do's title, description, priority, or due date, for example when the work "
                "has changed. Only the fields you pass change. Prefer this, or append_todo_note, to creating a "
                "duplicate To-Do. The change is recorded as made by this Agent Task."
            ),
            args_schema=UpdateTodoArgs,
        ),
        StructuredTool.from_function(
            func=set_todo_status, coroutine=set_todo_status, name="set_todo_status",
            description=(
                "Change an existing To-Do's status. open, in_progress, and ready_for_review take effect "
                "immediately. completed, dismissed, and canceled first ask the user to approve; if they decline "
                "or do not respond, the To-Do is left as it was, so report that instead of retrying. Only mark a "
                "To-Do completed when its work is actually done."
            ),
            args_schema=SetTodoStatusArgs,
        ),
        StructuredTool.from_function(
            func=delegate_todo_work, coroutine=delegate_todo_work, name="delegate_todo_work",
            description=(
                "Launch a direct-origin worker Agent Task for one selected To-Do. Only available "
                "from the To-Do workspace, and only for To-Dos in the current selection. Launching "
                "a worker does not complete, dismiss, or reopen a To-Do."
            ),
            args_schema=DelegateTodoWorkArgs,
        ),
    ]
