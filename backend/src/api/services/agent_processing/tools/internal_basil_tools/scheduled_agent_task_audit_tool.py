"""Agent tool for reviewing Basil's scheduled agent tasks and pausing one that should stop running."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile
from api.services.scheduled_agent_tasks.scheduled_agent_task_service import ScheduledAgentTaskService

logger = logging.getLogger(__name__)

TOOL_NAME = "manage_scheduled_agent_tasks"
TEXT_PREVIEW_LIMIT = 300

SLIM_DESCRIPTION = (
    "manage_scheduled_agent_tasks(action, scheduled_agent_task_id?) - review Basil's scheduled agent tasks. "
    "list shows every schedule with its timing, whether it is active, and how its last run went. "
    "pause stops one schedule from running until the user turns it back on in Basil. "
    "You cannot resume, edit or delete a schedule; tell the user to do that in Basil's schedule list."
)

_FULL_DESCRIPTION = """Review the scheduled agent tasks Basil runs on its own, and pause one that should stop.

Actions:
- list: every schedule, with its id, title, a preview of what it does, when it next runs, whether it is active, and the status of its last run.
- pause: set one schedule inactive so it stops running. Pass scheduled_agent_task_id from list. The schedule is kept, and the user can turn it back on in Basil's schedule list.

You cannot resume, edit, run or delete a schedule with this tool. Creating a new schedule is a different tool, create_scheduled_agent_task_from_prompt. After pausing, tell the user which schedule you paused and why."""


class ScheduledAgentTaskAuditInput(BaseModel):
    """Input schema for reviewing and pausing scheduled agent tasks."""

    action: Literal["list", "pause"] = Field(description="list or pause.")
    scheduled_agent_task_id: Optional[str] = Field(default=None, description="For pause: the id of the schedule to pause, from list.")


def _json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _summary(item: Dict[str, Any]) -> Dict[str, Any]:
    text = str(item.get("agent_task_text") or "")
    preview = text if len(text) <= TEXT_PREVIEW_LIMIT else text[:TEXT_PREVIEW_LIMIT] + "..."
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "what_it_does": preview,
        "schedule_type": item.get("schedule_type"),
        "timezone": item.get("timezone"),
        "is_active": bool(item.get("is_active")),
        "next_run_at": item.get("next_run_at"),
        "last_run_at": item.get("last_run_at"),
        "last_status": item.get("last_status"),
    }


async def _manage_scheduled_agent_tasks_impl(action: str, scheduled_agent_task_id: Optional[str] = None) -> str:
    """Dispatch a list or pause request to the scheduled agent task service."""
    try:
        service = ScheduledAgentTaskService()
        if action == "list":
            items = await service.list_scheduled_agent_tasks(include_inactive=True)
            return _json({"success": True, "scheduled_agent_tasks": [_summary(item) for item in items]})
        if action == "pause":
            if not scheduled_agent_task_id:
                return _json({"success": False, "error": "pause needs scheduled_agent_task_id. Call list first."})
            existing = await service.get_scheduled_agent_task(scheduled_agent_task_id)
            if not existing:
                return _json({"success": False, "error": f"No scheduled agent task has the id {scheduled_agent_task_id}. Call list for the current ids."})
            if not existing.get("is_active"):
                return _json({"success": True, "changed": False, "scheduled_agent_task": _summary(existing), "note": "It was already paused."})
            updated = await service.update_scheduled_agent_task(scheduled_agent_task_id, {"is_active": False})
            if not updated:
                return _json({"success": False, "error": "The schedule could not be paused. It may have just been deleted."})
            return _json({"success": True, "changed": True, "scheduled_agent_task": _summary(updated)})
        return _json({"success": False, "error": f"Unknown action {action!r}. Use list or pause."})
    except Exception as exc:
        logger.error("Scheduled agent task review failed: %s", exc, exc_info=True)
        return _json({"success": False, "error": str(exc)})


def create_scheduled_agent_task_audit_tool(profile=None) -> StructuredTool:
    """Build the schedule review tool, with the slim description under a slim rendering profile."""
    return StructuredTool.from_function(
        func=_manage_scheduled_agent_tasks_impl,
        name=TOOL_NAME,
        description=select_description_for_profile(profile, _FULL_DESCRIPTION, SLIM_DESCRIPTION),
        args_schema=ScheduledAgentTaskAuditInput,
        coroutine=_manage_scheduled_agent_tasks_impl,
    )
