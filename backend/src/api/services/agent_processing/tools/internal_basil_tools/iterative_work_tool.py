"""Agent tool for durable iterative work sessions."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile

logger = logging.getLogger(__name__)


class IterativeWorkInput(BaseModel):
    """Input schema for the compact iterative-work action tool."""

    action: Literal[
        "start",
        "add_items",
        "claim_next",
        "update_items",
        "update_strategy",
        "summarize",
        "query",
        "get_evidence",
        "entity_context",
        "finish",
    ] = Field(description="Iterative-work action to dispatch.")
    session_id: Optional[str] = Field(default=None, description="Work-session id for non-start actions.")
    agent_task_id: Optional[str] = Field(default=None, description="Current agent task id when available.")
    goal: Optional[str] = Field(default=None, description="User-visible goal for a new work session.")
    collection_type: Optional[str] = Field(default=None, description="Type of collection, e.g. email, files, activities.")
    strategy: Optional[Dict[str, Any]] = Field(default=None, description="Batching/coverage strategy.")
    scope: Optional[Dict[str, Any]] = Field(default=None, description="Source scope, coverage, and retrieval bounds.")
    cursor: Optional[Dict[str, Any]] = Field(default=None, description="Cursor or pagination state.")
    summary_so_far: Optional[str] = Field(default=None, description="Compact durable summary of progress.")
    item_budget: Optional[int] = Field(default=None, description="Maximum number of items to consider.")
    token_budget: Optional[int] = Field(default=None, description="Approximate token budget for work.")
    items: Optional[List[Dict[str, Any]]] = Field(default=None, description="Lightweight item metadata for add_items.")
    updates: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description=(
            "Item updates for update_items. Include model-driven status, decision/reason, "
            "detail_summary, action_result, or error fields as appropriate."
        ),
    )
    statuses: Optional[List[str]] = Field(default=None, description="Statuses eligible for claim_next.")
    limit: Optional[int] = Field(default=5, description="Maximum items to claim or return.")
    batch_index: Optional[int] = Field(default=0, description="Batch index for add_items.")
    default_status: Optional[str] = Field(default="discovered", description="Status assigned to new items.")
    mark_status: Optional[str] = Field(default="in_progress", description="Status to assign claimed items.")
    status: Optional[str] = Field(default=None, description="Session status for update_strategy/finish.")
    external_id: Optional[str] = Field(default=None, description="Durable external entity id for focused queries.")
    item_id: Optional[str] = Field(default=None, description="Source-safe ledger entity id returned by query.")
    verification_status: Optional[str] = Field(default=None, description="Receipt verification status filter.")
    service: Optional[str] = Field(default=None, description="Receipt service filter.")
    method: Optional[str] = Field(default=None, description="Receipt method filter.")


async def _iterative_work_impl(
    action: str,
    session_id: Optional[str] = None,
    agent_task_id: Optional[str] = None,
    goal: Optional[str] = None,
    collection_type: Optional[str] = None,
    strategy: Optional[Dict[str, Any]] = None,
    scope: Optional[Dict[str, Any]] = None,
    cursor: Optional[Dict[str, Any]] = None,
    summary_so_far: Optional[str] = None,
    item_budget: Optional[int] = None,
    token_budget: Optional[int] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    updates: Optional[List[Dict[str, Any]]] = None,
    statuses: Optional[List[str]] = None,
    limit: int = 5,
    batch_index: int = 0,
    default_status: str = "discovered",
    mark_status: Optional[str] = "in_progress",
    status: Optional[str] = None,
    external_id: Optional[str] = None,
    item_id: Optional[str] = None,
    verification_status: Optional[str] = None,
    service: Optional[str] = None,
    method: Optional[str] = None,
) -> str:
    """Dispatch a durable iterative-work action and return compact JSON."""
    try:
        from api.dependencies import get_sqlite_knowledge_service
        from api.services.agent_processing.shared import get_current_agent_context
        from api.services.agent_processing.lifecycle.runtime.agent_work_ledger_service import (
            AgentWorkLedgerService,
        )

        knowledge_service = get_sqlite_knowledge_service()
        session_repository = knowledge_service.agent_work_session_repository
        item_repository = knowledge_service.agent_work_item_repository
        entity_repository = knowledge_service.agent_work_entity_repository
        event_repository = knowledge_service.agent_work_event_repository
        ledger = AgentWorkLedgerService(knowledge_service)
        normalized_action = (action or "").strip().lower()
        runtime_context = get_current_agent_context()
        runtime_agent_task_id = runtime_context.get("agent_task_id")
        if not agent_task_id and runtime_agent_task_id:
            agent_task_id = runtime_agent_task_id
        if agent_task_id:
            runtime_context = {**runtime_context, "agent_task_id": agent_task_id}

        if normalized_action == "start":
            if not goal or not collection_type:
                raise ValueError("start requires goal and collection_type")
            result = await ledger.ensure_session(
                context=runtime_context,
                goal=goal,
                collection_type=collection_type,
                scope=scope,
            )
            if result and (strategy or cursor or summary_so_far or item_budget or token_budget):
                result = await session_repository.update_strategy(
                    session_id=result["id"],
                    strategy=strategy,
                    cursor=cursor,
                    summary_so_far=summary_so_far,
                )
            payload = {"success": True, "action": normalized_action, "session": result}

        elif normalized_action == "add_items":
            session = await ledger.resolve_session(context=runtime_context, session_id=session_id)
            if not session:
                raise ValueError("add_items requires an accessible work session")
            result = await item_repository.add_items(
                session_id=session["id"],
                items=items or [],
                batch_index=batch_index or 0,
                default_status=default_status or "discovered",
            )
            payload = {"success": True, "action": normalized_action, **result}

        elif normalized_action == "claim_next":
            session = await ledger.resolve_session(context=runtime_context, session_id=session_id)
            if not session:
                raise ValueError("claim_next requires an accessible work session")
            result = await item_repository.claim_next(
                session_id=session["id"],
                statuses=statuses,
                limit=limit or 5,
                mark_status=mark_status,
            )
            payload = {"success": True, "action": normalized_action, "items": result, "count": len(result)}

        elif normalized_action == "update_items":
            session = await ledger.resolve_session(context=runtime_context, session_id=session_id)
            if not session:
                raise ValueError("update_items requires an accessible work session")
            result = await item_repository.update_items(session_id=session["id"], updates=updates or [])
            payload = {"success": True, "action": normalized_action, **result}

        elif normalized_action == "update_strategy":
            session = await ledger.resolve_session(context=runtime_context, session_id=session_id)
            if not session:
                raise ValueError("update_strategy requires an accessible work session")
            if scope is not None:
                await session_repository.update_scope(session["id"], scope)
            result = await session_repository.update_strategy(
                session_id=session["id"],
                strategy=strategy,
                cursor=cursor,
                summary_so_far=summary_so_far,
                status=status,
            )
            payload = {"success": bool(result), "action": normalized_action, "session": result}

        elif normalized_action == "summarize":
            session = await ledger.resolve_session(context=runtime_context, session_id=session_id)
            if not session:
                raise ValueError("summarize requires an accessible work session")
            payload = await session_repository.summarize(session["id"])
            payload["action"] = normalized_action

        elif normalized_action == "query":
            session = await ledger.resolve_session(context=runtime_context, session_id=session_id)
            if not session:
                raise ValueError("query requires an accessible work session")
            result = await item_repository.get_items(
                session_id=session["id"], statuses=statuses, external_id=external_id, limit=limit or 5,
            )
            payload = {"success": True, "action": normalized_action, "items": result, "count": len(result)}

        elif normalized_action == "get_evidence":
            session = await ledger.resolve_session(context=runtime_context, session_id=session_id)
            if not session:
                raise ValueError("get_evidence requires an accessible work session")
            if item_id:
                entity = await entity_repository.get_entity(
                    session_id=session["id"],
                    item_id=item_id,
                )
                items_for_evidence = [entity] if entity else []
            elif external_id:
                items_for_evidence = await entity_repository.find_by_external_id(
                    session_id=session["id"],
                    external_id=external_id,
                )
            else:
                return json.dumps(
                    {
                        "success": False,
                        "action": normalized_action,
                        "error": {
                            "code": "entity_reference_required",
                            "message": "get_evidence requires item_id or external_id.",
                        },
                    },
                    ensure_ascii=False,
                )
            if not items_for_evidence:
                return json.dumps(
                    {
                        "success": False,
                        "action": normalized_action,
                        "error": {
                            "code": "entity_not_found",
                            "message": "No entity matched the supplied reference.",
                        },
                    },
                    ensure_ascii=False,
                )
            if len(items_for_evidence) > 1:
                return json.dumps(
                    {
                        "success": False,
                        "action": normalized_action,
                        "error": {
                            "code": "ambiguous_external_id",
                            "message": "external_id resolved to multiple entities; use item_id.",
                            "entity_ids": [item["id"] for item in items_for_evidence],
                        },
                    },
                    ensure_ascii=False,
                )
            resolved_item_id = items_for_evidence[0]["id"]
            receipts = await knowledge_service.agent_work_receipt_repository.get_receipts(
                session_id=session["id"], item_id=resolved_item_id, verification_status=verification_status,
                service=service, method=method, limit=limit or 5, newest_first=True,
            )
            payload = {
                "success": True, "action": normalized_action, "items": items_for_evidence,
                "receipts": receipts, "count": len(receipts),
            }

        elif normalized_action == "entity_context":
            session = await ledger.resolve_session(context=runtime_context, session_id=session_id)
            if not session:
                raise ValueError("entity_context requires an accessible work session")
            if not item_id:
                raise ValueError("entity_context requires a source-safe item_id")
            entity = await entity_repository.get_entity(
                session_id=session["id"],
                item_id=item_id,
            )
            if not entity:
                return json.dumps(
                    {
                        "success": False,
                        "action": normalized_action,
                        "error": {
                            "code": "entity_not_found",
                            "message": "No entity matched item_id in this task chain.",
                        },
                    },
                    ensure_ascii=False,
                )
            payload = {
                "success": True,
                "action": normalized_action,
                "entity": entity,
                "relations": await entity_repository.get_relations(
                    session_id=session["id"],
                    item_id=item_id,
                ),
                "history": await event_repository.get_events(
                    session_id=session["id"],
                    item_id=item_id,
                ),
                "receipts": await knowledge_service.agent_work_receipt_repository.get_receipts(
                    session_id=session["id"],
                    item_id=item_id,
                    limit=limit or 5,
                    newest_first=True,
                ),
            }

        elif normalized_action == "finish":
            session = await ledger.resolve_session(context=runtime_context, session_id=session_id)
            if not session:
                raise ValueError("finish requires an accessible work session")
            result = await session_repository.finish(
                session_id=session["id"],
                summary_so_far=summary_so_far,
                status=status or "finished",
            )
            if isinstance(result, dict) and result.get("success") is False:
                payload = {"action": normalized_action, **result}
            else:
                payload = {"success": bool(result), "action": normalized_action, "session": result}

        else:
            raise ValueError(f"Unsupported iterative_work action: {action}")

        return json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.error("iterative_work failed: %s", exc, exc_info=True)
        return json.dumps(
            {"success": False, "action": action, "error": str(exc)},
            ensure_ascii=False,
        )


# Why this slim:
# - KEEPS: when to use (large/unknown-cardinality tasks; promote when scale or
#   context pressure is evident); the load-bearing finish invariant ('finish
#   only succeeds when claimable unresolved items are cleared, else returns
#   incomplete_coverage') because the agent will otherwise loop on a refused
#   finish; the hint that add_items should carry metadata/ids/summaries (not
#   bodies) since dumping bodies into the ledger is the most common misuse.
# - DROPS: per-action prose explanations (the schema's action Literal lists
#   the seven values; per-action required-fields are in the Pydantic field
#   descriptions); 'start simple first' framing (covered by the system
#   prompt's 'when to use a ledger' guidance); update_items status enumeration
#   (those are still strings; if we promote them to a Literal in a later pass
#   the schema will surface them).
SLIM_DESCRIPTION = (
    "Durable iterative-work ledger for large or unknown-cardinality tasks "
    "(many items, repeated per-item actions, long outputs, batches). "
    "Promote to this when scale or context pressure is evident; start simple "
    "for small tasks. Store metadata/ids/summaries via add_items, not bodies. "
    "finish only succeeds when claimable unresolved items are cleared - "
    "otherwise it returns an incomplete_coverage response and you must "
    "continue with claim_next, update_strategy, or explicitly finish as "
    "partial/blocked/budget_exhausted."
)

_FULL_DESCRIPTION = """Manage a durable iterative work session for large or unknown-cardinality tasks.

Use this when a task starts to look too large for one direct pass: many items, repeated
actions per item, long tool outputs, timeouts, or a need to preserve coverage across
batches. Start simple first when the task is small; promote to this ledger when scale
or context pressure is evident.

Actions:
- start: create a session with goal, collection_type, strategy, budgets, and cursor.
- add_items: store lightweight discovered items. Prefer metadata, ids, summaries, and
  references; do not store large bodies by default. For collection work, add the
  whole discovered set before discarding items from consideration.
- claim_next: get a small working set and optionally mark it in_progress.
- update_items: mark items needs_detail, candidate, expanded, acted_on, skipped,
  failed, or unresolved. Include a compact model-written reason/decision for skipped
  or deferred items; do not rely on hardcoded string matching or tool-specific skip rules.
- update_strategy: revise batch size, cursor, expansion criteria, or stopping condition.
- summarize: get compact durable progress for context management.
- finish: close the session with explicit coverage/remaining-work summary. A completed
  finish is only accepted when claimable unresolved items are cleared; otherwise the
  tool returns a corrective incomplete_coverage response so you can continue with
  claim_next, update_strategy, or explicitly finish as partial/blocked/budget_exhausted.
"""


def create_iterative_work_tool(profile=None) -> StructuredTool:
    """Create the LangChain tool for generic batching/ledger workflows.

    Under a slim rendering profile the description is swapped to the
    hand-authored ``SLIM_DESCRIPTION`` companion above; otherwise the full
    description flows through unchanged.
    """
    tool_description = select_description_for_profile(
        profile, _FULL_DESCRIPTION, SLIM_DESCRIPTION
    )
    return StructuredTool.from_function(
        func=_iterative_work_impl,
        name="iterative_work",
        description=tool_description,
        args_schema=IterativeWorkInput,
        coroutine=_iterative_work_impl,
    )
