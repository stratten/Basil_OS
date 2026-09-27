"""Structured Agent Task tools for the To-Do domain, built as LangChain
`StructuredTool`s via closures over per-call context (todo_service,
agent_task_id, launcher), mirroring `service_tooling/memory_tools.py`."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CreateTodosArgs(BaseModel):
    title: str = Field(min_length=1, max_length=240, description="Short, action-oriented title for the To-Do.")
    description: str = Field(default="", max_length=12000, description="Optional longer description or context.")


class ListTodosArgs(BaseModel):
    status: Optional[str] = Field(
        default=None,
        description="Optional status filter: candidate, open, in_progress, ready_for_review, completed, dismissed, or cancelled.",
    )


class InspectTodoArgs(BaseModel):
    todo_id: str = Field(description="The To-Do id to inspect.")


class AppendTodoNoteArgs(BaseModel):
    todo_id: str = Field(description="The To-Do id to append a note to. Must be in this turn's selection.")
    note_markdown: str = Field(min_length=1, max_length=12000, description="Markdown note text to append.")


class AttachTodoReferenceArgs(BaseModel):
    todo_id: str = Field(description="The To-Do id to attach the local path to. Must be in this turn's selection.")
    path: str = Field(description="Absolute local file or folder path to retain as a reference.")


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
    """Build the five To-Do tools for one Agent Task's tool set. `agent_task_id`
    and `agent_task_provider` are captured by closure so each tool call reads
    the *current* persisted Agent Task row (its `accumulated_artifacts` may
    change between tool calls within the same task, e.g. once workspace
    context is attached), rather than a snapshot taken at tool-creation time.
    """

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
        agent_task = await _current_agent_task(agent_task_provider, agent_task_id)
        direct_todo_id = _direct_origin_todo_id(agent_task) if agent_task else None
        if direct_todo_id is not None:
            if todo_id != direct_todo_id:
                return {"success": False, "error": f"{todo_id} is not the To-Do this Agent Task was launched for"}
        else:
            selection = _workspace_selection_ids(agent_task) if agent_task else None
            if selection is None:
                return {
                    "success": False,
                    "error": "append_todo_note is only available from a To-Do workspace turn or a direct-origin To-Do worker",
                }
            if todo_id not in selection:
                return {"success": False, "error": f"{todo_id} is not in this turn's selected To-Dos"}
        detail = await todo_service.append_workspace_manager_note(todo_id, note_markdown, agent_task_id)
        return {"success": True, "todo_id": detail.id, "notes": detail.notes}

    async def attach_todo_reference(todo_id: str, path: str) -> Dict[str, Any]:
        agent_task = await _current_agent_task(agent_task_provider, agent_task_id)
        direct_todo_id = _direct_origin_todo_id(agent_task) if agent_task else None
        if direct_todo_id is not None:
            if todo_id != direct_todo_id:
                return {"success": False, "error": f"{todo_id} is not the To-Do this Agent Task was launched for"}
        else:
            selection = _workspace_selection_ids(agent_task) if agent_task else None
            if selection is None:
                return {
                    "success": False,
                    "error": "attach_todo_reference is only available from a To-Do workspace turn or a direct-origin To-Do worker",
                }
            if todo_id not in selection:
                return {"success": False, "error": f"{todo_id} is not in this turn's selected To-Dos"}
        detail = await todo_service.add_reference(todo_id, path, actor_agent_task_id=agent_task_id)
        return {
            "success": True,
            "todo_id": detail.id,
            "references": [reference.model_dump() for reference in detail.references],
        }

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
                "Append a timestamped note to a To-Do. Usable in two contexts: (1) from a To-Do "
                "workspace turn, for any To-Do in the current selection; or (2) from a direct-origin "
                "worker Agent Task, for exactly the one To-Do it was launched for."
            ),
            args_schema=AppendTodoNoteArgs,
        ),
        StructuredTool.from_function(
            func=attach_todo_reference, coroutine=attach_todo_reference, name="attach_todo_reference",
            description=(
                "Attach an absolute local file or folder path only when it is materially useful for the selected "
                "To-Do work. This retains a path reference and does not grant access outside normal file-tool "
                "safety controls, allowed roots, or approval requirements."
            ),
            args_schema=AttachTodoReferenceArgs,
        ),
        StructuredTool.from_function(
            func=delegate_todo_work, coroutine=delegate_todo_work, name="delegate_todo_work",
            description=(
                "Launch a direct-origin worker Agent Task for one selected To-Do. Only available "
                "from the To-Do workspace, and only for To-Dos in the current selection. Never "
                "completes, dismisses, or reopens a To-Do."
            ),
            args_schema=DelegateTodoWorkArgs,
        ),
    ]
