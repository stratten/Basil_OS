"""Agent tool for the task's working notes, the short current-state document beside its checklist."""

from __future__ import annotations

import json
import logging
from typing import Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile

logger = logging.getLogger(__name__)

SLIM_DESCRIPTION = (
    "Working notes for this task: a short document, shown to the user, that says where things stand right now. "
    "Actions: read, append (text), edit (find the exact text, replace it). "
    "Keep it to current facts and what you learned, not a history; condense it when it nears the limit. "
    "Do not write that a tool call succeeded unless it did."
)

_FULL_DESCRIPTION = """Read and update this task's working notes: one short document, visible to the user, that describes where things stand right now. It survives follow-up turns and, when the schedule allows it, carries into the next run.

Use it for what a later turn would otherwise have to rediscover: decisions made, what you learned about the people and systems involved, constraints (for example "the clinic answers on Fridays"), and what to check next. Put the status of individual steps in the checklist, not here.

The notes are the current state, never a history. Do not log what happened turn by turn. When something is no longer true, edit it out. The notes have a hard size limit; a change that would exceed it is refused, so condense first.

Never record that a tool call succeeded, a message was sent, or an action was completed unless a tool actually reported that in this task. A note that claims an outcome the task has no record of is refused.

Actions:
- read: return the notes and how much of the limit they use.
- append: add text (one or a few lines) at the end.
- edit: replace find, which must appear exactly once in the notes, with replace. Use an empty replace to delete text. Read first and copy find exactly.
"""


class ChecklistNotesInput(BaseModel):
    """Input schema for the checklist_notes tool."""

    action: Literal["read", "append", "edit"] = Field(description="Notes action.")
    text: Optional[str] = Field(default=None, description="Text to add for append.")
    find: Optional[str] = Field(default=None, description="Exact text to replace for edit. Must appear exactly once.")
    replace: Optional[str] = Field(default=None, description="Replacement text for edit. Empty deletes the found text.")


async def _checklist_notes_impl(
    action: str,
    text: Optional[str] = None,
    find: Optional[str] = None,
    replace: Optional[str] = None,
) -> str:
    """Dispatch a notes action and return compact JSON. Corrections are returned as errors the model can act on."""
    from api.dependencies import get_sqlite_knowledge_service
    from api.services.agent_processing.lifecycle.runtime.agent_checklist_service import AgentChecklistService
    from api.services.agent_processing.shared import get_current_agent_context

    normalized = (action or "").strip().lower()
    try:
        service = AgentChecklistService(get_sqlite_knowledge_service())
        payload = await service.model_notes(get_current_agent_context(), action=normalized, text=text, find=find, replace=replace)
        payload["action"] = normalized
    except ValueError as error:
        payload = {"success": False, "action": normalized, "error": str(error)}
    except Exception as error:
        logger.warning("Checklist notes action failed: %s", error, exc_info=True)
        payload = {"success": False, "action": normalized, "error": f"The notes are unavailable right now: {error}"}
    return json.dumps(payload, ensure_ascii=False, default=str)


def create_checklist_notes_tool(profile=None) -> StructuredTool:
    """Create the checklist_notes tool. Small models get the slim description."""
    return StructuredTool.from_function(
        func=_checklist_notes_impl,
        name="checklist_notes",
        description=select_description_for_profile(profile, _FULL_DESCRIPTION, SLIM_DESCRIPTION),
        args_schema=ChecklistNotesInput,
        coroutine=_checklist_notes_impl,
    )
