"""Agent tool for the task's durable checklist."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile

logger = logging.getLogger(__name__)

SLIM_DESCRIPTION = (
    "This task's durable checklist of what still needs to happen; it survives follow-ups and is shown to the user. "
    "An item is an outcome (a reply sent, a decision made, a problem resolved), never your own action such as reading or drafting. "
    "Add outcomes the request states or implies and those your findings reveal, set status (pending, in_progress, waiting_external, waiting_user, done, dropped) as they move, and mark done only when the outcome has really happened; a proposal or draft leaves the item waiting_user. "
    "Actions: list, add, update (item = id from the checklist), find (by external_id). "
    "Attach refs (ref_kind, external_id, label) for the email thread, request, or deployment an item concerns. When you review or act on a set of records (for example several emails), add one item per record for the outcome it needs as soon as you have the set (one batch item only if more than about 10), all in one call with items, and keep each item waiting_user until the user decides or the action happens."
)

_FULL_DESCRIPTION = """Manage this task's checklist: a durable, user-visible list of what still needs to happen as a result of the request and of what you or the user find along the way. It survives follow-up turns and scheduled runs. It is not a log of your own steps: an item is an outcome that still has to occur (a reply sent, a decision made, a problem resolved), never an action of yours such as reading, searching, drafting, or proposing.

Use it when the request states or implies outcomes to be reached, when your findings or the user's replies reveal more (for example a referral you did not know was needed), when something waits on another person or system, or when the user must decide something. Do not use it for a single quick action.

Keep it current: add outcomes as you learn of them, set the status as they move, and keep an item open until the outcome has really happened. A proposal, draft, or recommendation does not complete an item; set it to waiting_user. Mark done only when the outcome is complete, such as the reply sent, the decision made, or the user saying nothing is needed, and add a new item when finishing one reveals more to do. The status waiting_user means the user has to act; set waiting_on to say what you need from them. The status waiting_external means someone else has to act; set recheck_at (ISO time) when you know when to look again. Mark an item dropped when it no longer applies.

Items can carry references to the things they concern, for example a Gmail thread, a Speakeasy request, or a Salesforce deployment. Pass refs (a list) when adding, or ref (one) when updating, each with ref_kind, external_id, and optionally source_system, source_scope, label, open_url, and role (origin, delegated_to, produced, or related). Use find with external_id to see whether a thread or request is already tracked before adding it.

When a request reviews or acts on a set of records, such as the five most recent emails or a list of requests, add one item per record for the outcome that record needs (handled, decided, or followed up) as soon as you have the set, with a ref to each thread or record, all in one call with items. Use a single batch item only if the set is larger than about 10. A record is handled when the action happened, the user decided, or the user said nothing is needed, so proposing a reply or a deletion leaves the item waiting_user with what you need in waiting_on. Update each item as its outcome moves.

Actions:
- list: open items (include_closed for done and dropped items too).
- add: create an item. title is required; required=true makes the item block a clean finish. To add several at once, pass items (a list of entries, each with title and optionally detail, status, waiting_on, required, refs) instead of title; one call adds up to 25.
- update: change an item named by item (the short id shown in the checklist). Pass any of title, detail, status, required, note, waiting_on, recheck_at, plus event_text, a short reason that is kept in the item's step log.
- find: look up items by external_id (with optional ref_kind) or by a title query.
"""


class ChecklistInput(BaseModel):
    """Input schema for the checklist tool."""

    action: Literal["list", "add", "update", "find"] = Field(description="Checklist action.")
    item: Optional[str] = Field(default=None, description="Item id (as shown in the checklist) for update.")
    title: Optional[str] = Field(default=None, description="Item title for add, or a new title for update.")
    detail: Optional[str] = Field(default=None, description="Longer description of the item.")
    status: Optional[str] = Field(default=None, description="pending, in_progress, waiting_external, waiting_user, done, or dropped.")
    required: Optional[bool] = Field(default=None, description="True when the task is not complete until this item is done or dropped.")
    note: Optional[str] = Field(default=None, description="Short current note about the item.")
    waiting_on: Optional[str] = Field(default=None, description="Who or what the item waits on (for waiting statuses).")
    recheck_at: Optional[str] = Field(default=None, description="ISO time when an external wait should be checked again.")
    event_text: Optional[str] = Field(default=None, description="Short reason for this change, kept in the item's step log.")
    refs: Optional[List[Dict[str, Any]]] = Field(default=None, description="References for add: ref_kind, external_id, source_system, source_scope, label, open_url, role.")
    items: Optional[List[Dict[str, Any]]] = Field(default=None, description="For add, several items in one call instead of title: each entry has title (required) and optionally detail, status, required, note, waiting_on, recheck_at, and refs. At most 25 per call.")
    ref: Optional[Dict[str, Any]] = Field(default=None, description="One reference to attach to the item on update.")
    external_id: Optional[str] = Field(default=None, description="External id to look up with find.")
    ref_kind: Optional[str] = Field(default=None, description="Reference kind filter for find.")
    query: Optional[str] = Field(default=None, description="Title text to look up with find.")
    include_closed: Optional[bool] = Field(default=False, description="Include done and dropped items in list.")


_ADD_FIELDS = ("detail", "status", "required", "note", "waiting_on", "recheck_at")
_UPDATE_FIELDS = ("title", "detail", "status", "required", "note", "waiting_on", "recheck_at")


async def _checklist_impl(
    action: str,
    item: Optional[str] = None,
    title: Optional[str] = None,
    detail: Optional[str] = None,
    status: Optional[str] = None,
    required: Optional[bool] = None,
    note: Optional[str] = None,
    waiting_on: Optional[str] = None,
    recheck_at: Optional[str] = None,
    event_text: Optional[str] = None,
    refs: Optional[List[Dict[str, Any]]] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    ref: Optional[Dict[str, Any]] = None,
    external_id: Optional[str] = None,
    ref_kind: Optional[str] = None,
    query: Optional[str] = None,
    include_closed: Optional[bool] = False,
) -> str:
    """Dispatch a checklist action and return compact JSON. Corrections are returned as errors the model can act on."""
    from api.dependencies import get_sqlite_knowledge_service
    from api.services.agent_processing.shared import get_current_agent_context
    from api.services.agent_processing.lifecycle.runtime.agent_checklist_service import (
        AgentChecklistService,
        ChecklistError,
    )

    given = {
        "title": title, "detail": detail, "status": status, "required": required, "note": note,
        "waiting_on": waiting_on, "recheck_at": recheck_at,
    }
    try:
        service = AgentChecklistService(get_sqlite_knowledge_service())
        context = get_current_agent_context()
        normalized = (action or "").strip().lower()
        if normalized == "list":
            payload = await service.model_list(context, include_closed=bool(include_closed), status=status)
        elif normalized == "add" and items:
            if title:
                raise ChecklistError("add takes either title or items, not both")
            payload = await service.model_add_many(context, items)
        elif normalized == "add":
            fields = {key: given[key] for key in _ADD_FIELDS if given[key] is not None}
            payload = await service.model_add(context, title=title or "", refs=refs or [], **fields)
        elif normalized == "update":
            changes = {key: given[key] for key in _UPDATE_FIELDS if given[key] is not None}
            if not changes and not ref:
                raise ChecklistError("update needs at least one field to change or a ref to attach")
            payload = await service.model_update(context, item=item or "", changes=changes, ref=ref, event_text=event_text or "")
        elif normalized == "find":
            if not (external_id or query):
                raise ChecklistError("find needs external_id or query")
            payload = await service.model_find(context, external_id=external_id, ref_kind=ref_kind, query=query)
        else:
            raise ChecklistError(f"Unknown action '{action}'. Use list, add, update, or find.")
        payload["action"] = normalized
    except ValueError as error:
        payload = {"success": False, "action": (action or "").strip().lower(), "error": str(error)}
    except Exception as error:
        logger.warning("Checklist action failed: %s", error, exc_info=True)
        payload = {"success": False, "action": (action or "").strip().lower(), "error": f"The checklist is unavailable right now: {error}"}
    return json.dumps(payload, ensure_ascii=False, default=str)


def create_checklist_tool(profile=None) -> StructuredTool:
    """Create the checklist tool. Small models get the slim description."""
    return StructuredTool.from_function(
        func=_checklist_impl,
        name="checklist",
        description=select_description_for_profile(profile, _FULL_DESCRIPTION, SLIM_DESCRIPTION),
        args_schema=ChecklistInput,
        coroutine=_checklist_impl,
    )
