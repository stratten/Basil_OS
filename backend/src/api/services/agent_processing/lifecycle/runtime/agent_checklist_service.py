"""Per-chain agent checklist orchestration: session resolution, model-facing operations, prompt block, and live updates."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_work.checklist_records import (
    MAX_NOTES_CHARS,
)

from .agent_checklist_notes_grounding import grounding_error, receipt_exists, ungrounded_claims
from .agent_checklist_prompt import (
    LEDGER_HINT_MIN_ITEMS,
    SHORT_ID_CHARS,
    build_checklist_prompt_section,
    build_ledger_hint,
    short_id,
)
from .agent_work_ledger_service import AgentWorkLedgerService

logger = logging.getLogger(__name__)

CHECKLIST_UPDATED_EVENT = "agent_checklist_updated"
MODEL_LIST_LIMIT = 40
MODEL_ADD_BATCH_LIMIT = 25
_BATCH_ENTRY_FIELDS = frozenset({"title", "detail", "status", "required", "note", "waiting_on", "recheck_at", "refs"})
MIN_ITEM_PREFIX_CHARS = 6
NOTES_NEAR_LIMIT_SHARE = 0.8
MAX_REQUIRED_SCAN = 500
CHECKLIST_GOAL_FALLBACK = "Agent task checklist"
_CHECKLIST_WRITE_ACTOR = "agent"


class ChecklistError(ValueError):
    """A checklist request the caller can correct, with a message safe to show the model or the user."""


def item_for_model(item: Dict[str, Any]) -> Dict[str, Any]:
    """A compact view of one item: short id, no step logs, references reduced to what the model can act on."""
    view: Dict[str, Any] = {
        "id": short_id(item["id"]),
        "title": item["title"],
        "status": item["status"],
        "required": item["required"],
    }
    for key in ("detail", "note", "waiting_on", "recheck_at", "done_basis"):
        if item.get(key):
            view[key] = item[key]
    if item.get("refs"):
        view["refs"] = [
            {key: ref[key] for key in ("role", "ref_kind", "source_system", "external_id", "label") if ref.get(key)}
            for ref in item["refs"]
        ]
    return view


class AgentChecklistService:
    """Everything that touches the checklist on behalf of a running agent or the UI routes."""

    def __init__(self, knowledge_service: Any) -> None:
        self._knowledge_service = knowledge_service
        self._items = knowledge_service.agent_checklist_repository
        self._notes = knowledge_service.agent_checklist_notes_repository
        self._sessions = knowledge_service.agent_work_session_repository
        self._ledger = AgentWorkLedgerService(knowledge_service)

    async def session_for_root(self, root_task_id: str, *, create: bool, goal: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """The work session of a chain root. Reads never create one; writes create it on demand."""
        if not root_task_id:
            return None
        if not create:
            return await self._sessions.get_latest_session_for_root(root_task_id)
        return await self._sessions.get_or_create_root_session(
            root_task_id=root_task_id,
            goal=goal or CHECKLIST_GOAL_FALLBACK,
            collection_type="agent_work",
        )

    async def session_for_context(self, context: Optional[Dict[str, Any]], *, create: bool) -> Optional[Dict[str, Any]]:
        root_task_id = AgentWorkLedgerService.root_task_id(context)
        if not root_task_id:
            return None
        goal = str((context or {}).get("user_agent_task") or "")[:200] or None
        session = await self.session_for_root(str(root_task_id), create=create, goal=goal)
        return session

    async def snapshot(self, session_id: str, *, include_archived: bool = False) -> Dict[str, Any]:
        items = await self._items.list_items(session_id, include_archived=include_archived)
        state = await self._items.get_state(session_id)
        notes = await self._notes.get_notes(session_id)
        last_actors = await self._items.last_actor_by_item(session_id)
        for item in items:
            item["last_actor"] = last_actors.get(item["id"])
        return {"session_id": session_id, "items": items, "counts": state["counts"], "closed_at": state["closed_at"], "notes": notes}

    async def prompt_section(self, context: Optional[Dict[str, Any]], *, prompt_budget_tokens: Optional[int]) -> str:
        """The bounded block for this turn. Any failure yields no block, because a prompt must never fail on its own bookkeeping."""
        try:
            session = await self.session_for_context(context, create=False)
            if session is None:
                return ""
            snapshot = await self.snapshot(session["id"])
            section = build_checklist_prompt_section(
                snapshot["items"], snapshot["counts"], snapshot["notes"],
                prompt_budget_tokens=prompt_budget_tokens, closed=bool(snapshot["closed_at"]),
            )
            if not section and not snapshot["counts"]["total"]:
                section = await self._ledger_hint(session["id"])
            return f"\n{section}" if section else ""
        except Exception:
            logger.warning("Could not build the checklist prompt block", exc_info=True)
            return ""

    async def _ledger_hint(self, session_id: str) -> str:
        """A nudge when the chain's coverage ledger holds records but the checklist is empty. It is read at turn start, so it covers the second and later turns of a chain."""
        records = await self._knowledge_service.agent_work_item_repository.get_items(
            session_id=session_id, limit=LEDGER_HINT_MIN_ITEMS,
        )
        return build_ledger_hint() if len(records) >= LEDGER_HINT_MIN_ITEMS else ""

    async def records_without_checklist(self, context: Optional[Dict[str, Any]]) -> bool:
        """True when the chain's coverage ledger holds a set of records and the checklist has no items. Never creates a session and never raises."""
        try:
            session = await self.session_for_context(context, create=False)
            if not session:
                return False
            state = await self._items.get_state(session["id"])
            if state["counts"]["total"]:
                return False
            records = await self._knowledge_service.agent_work_item_repository.get_items(
                session_id=session["id"], limit=LEDGER_HINT_MIN_ITEMS,
            )
            return len(records) >= LEDGER_HINT_MIN_ITEMS
        except Exception:
            logger.warning("Could not compare the coverage ledger with the checklist", exc_info=True)
            return False

    async def resolve_item(self, session_id: str, reference: str) -> Dict[str, Any]:
        """Find an item by full id or by an unambiguous id prefix of at least six characters."""
        wanted = str(reference or "").strip()
        if not wanted:
            raise ChecklistError("item is required: pass the id shown in the checklist")
        exact = await self._items.get_item(session_id, wanted)
        if exact:
            return exact
        if len(wanted) >= MIN_ITEM_PREFIX_CHARS:
            matches = [item for item in await self._items.list_items(session_id, include_archived=True) if item["id"].startswith(wanted)]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise ChecklistError(f"The id '{wanted}' matches {len(matches)} items. Use more characters of the id.")
        raise ChecklistError(f"No checklist item matches '{wanted}'. Use checklist list to see current ids.")

    async def publish(self, session_id: str, context_or_ids: Dict[str, Any]) -> None:
        """Tell connected windows that a checklist changed, so they refetch. Never raises."""
        try:
            from api.services.agent_processing.lifecycle.submission.agent_task_event_broadcaster import (
                AgentTaskEventBroadcaster,
            )

            state = await self._items.get_state(session_id)
            await AgentTaskEventBroadcaster().broadcast({
                "event_type": CHECKLIST_UPDATED_EVENT,
                "root_task_id": context_or_ids.get("root_task_id"),
                "agent_task_id": context_or_ids.get("agent_task_id"),
                "counts": state["counts"],
                "closed_at": state["closed_at"],
            })
        except Exception:
            logger.debug("Checklist update broadcast failed", exc_info=True)

    def _ids(self, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        root = AgentWorkLedgerService.root_task_id(context)
        return {"root_task_id": root, "agent_task_id": (context or {}).get("agent_task_id")}

    async def _write_session(self, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        session = await self.session_for_context(context, create=True)
        if session is None:
            raise ChecklistError("The checklist needs a running task. There is none in this context.")
        return session

    async def model_list(self, context: Optional[Dict[str, Any]], *, include_closed: bool = False, status: Optional[str] = None) -> Dict[str, Any]:
        session = await self.session_for_context(context, create=False)
        if session is None:
            return {"success": True, "items": [], "counts": {"total": 0, "done": 0}, "message": "The checklist is empty."}
        statuses = [status] if status else (None if include_closed else ["pending", "in_progress", "waiting_external", "waiting_user"])
        items = await self._items.list_items(session["id"], statuses=statuses, limit=MODEL_LIST_LIMIT + 1)
        state = await self._items.get_state(session["id"])
        payload: Dict[str, Any] = {"success": True, "items": [item_for_model(item) for item in items[:MODEL_LIST_LIMIT]], "counts": state["counts"]}
        if len(items) > MODEL_LIST_LIMIT:
            payload["truncated"] = f"Showing the first {MODEL_LIST_LIMIT}. Narrow with status or use find."
        return payload

    async def model_add(self, context: Optional[Dict[str, Any]], **fields: Any) -> Dict[str, Any]:
        session = await self._write_session(context)
        ids = self._ids(context)
        result = await self._items.add_item(
            session_id=session["id"], origin="agent", actor=_CHECKLIST_WRITE_ACTOR, agent_task_id=ids["agent_task_id"], **fields,
        )
        if result.get("rejected"):
            return {"success": False, "error": result["rejected"]}
        if result.get("duplicate"):
            return {"success": True, "created": False, "message": "An item with that reference already exists; update it instead.", "item": item_for_model(result["item"])}
        await self.publish(session["id"], ids)
        return {"success": True, "created": True, "item": item_for_model(result["item"])}

    async def model_add_many(self, context: Optional[Dict[str, Any]], entries: List[Any]) -> Dict[str, Any]:
        """Add several items in one call. A bad entry is reported and the rest are still added; the live update is published once."""
        if not entries:
            raise ValueError("items needs at least one entry")
        if len(entries) > MODEL_ADD_BATCH_LIMIT:
            raise ValueError(f"items holds at most {MODEL_ADD_BATCH_LIMIT} entries per call; add the rest in another call")
        session = await self._write_session(context)
        ids = self._ids(context)
        created: List[Dict[str, Any]] = []
        already_tracked: List[Dict[str, Any]] = []
        errors: List[str] = []
        for position, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                errors.append(f"items[{position}] is not an object with a title")
                continue
            fields = {key: value for key, value in entry.items() if key in _BATCH_ENTRY_FIELDS and value is not None}
            title = fields.pop("title", "")
            try:
                result = await self._items.add_item(
                    session_id=session["id"], title=title, origin="agent", actor=_CHECKLIST_WRITE_ACTOR,
                    agent_task_id=ids["agent_task_id"], **fields,
                )
            except ValueError as error:
                errors.append(f"items[{position}]: {error}")
                continue
            if result.get("rejected"):
                errors.append(f"items[{position}] and after were not added: {result['rejected']}")
                break
            if result.get("duplicate"):
                already_tracked.append(item_for_model(result["item"]))
            else:
                created.append(item_for_model(result["item"]))
        if created:
            await self.publish(session["id"], ids)
        payload: Dict[str, Any] = {"success": bool(created or already_tracked), "created": len(created), "items": created}
        if already_tracked:
            payload["already_tracked"] = already_tracked
        if errors:
            payload["errors"] = errors
        return payload

    async def model_update(
        self,
        context: Optional[Dict[str, Any]],
        *,
        item: str,
        changes: Dict[str, Any],
        ref: Optional[Dict[str, Any]] = None,
        event_text: str = "",
    ) -> Dict[str, Any]:
        session = await self._write_session(context)
        ids = self._ids(context)
        target = await self.resolve_item(session["id"], item)
        updated: Optional[Dict[str, Any]] = target
        if changes:
            result = await self._items.update_item(
                session_id=session["id"], item_id=target["id"], changes=changes, actor=_CHECKLIST_WRITE_ACTOR,
                agent_task_id=ids["agent_task_id"], event_text=event_text,
            )
            updated = (result or {}).get("item") or target
        if ref:
            updated = await self._items.add_ref(
                session_id=session["id"], item_id=target["id"], ref=ref, added_by=_CHECKLIST_WRITE_ACTOR, agent_task_id=ids["agent_task_id"],
            ) or updated
        await self.publish(session["id"], ids)
        return {"success": True, "item": item_for_model(updated)}

    async def model_find(self, context: Optional[Dict[str, Any]], **criteria: Any) -> Dict[str, Any]:
        session = await self.session_for_context(context, create=False)
        if session is None:
            return {"success": True, "items": []}
        found = await self._items.find_items(session["id"], **criteria)
        return {"success": True, "items": [item_for_model(item) for item in found]}

    async def open_required_items(self, context: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Required items of this chain that are not done or dropped, in list order. Reads never create a session."""
        session = await self.session_for_context(context, create=False)
        if session is None:
            return []
        state = await self._items.get_state(session["id"])
        if not state["counts"]["required_open"]:
            return []
        open_items = await self._items.list_items(
            session["id"], statuses=["pending", "in_progress", "waiting_external", "waiting_user"], limit=MAX_REQUIRED_SCAN,
        )
        return [item for item in open_items if item["required"]]

    async def model_notes(
        self,
        context: Optional[Dict[str, Any]],
        *,
        action: str,
        text: Optional[str] = None,
        find: Optional[str] = None,
        replace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Read, append to, or edit the chain's working notes. Text that claims tool outcomes the chain never produced is refused."""
        normalized = (action or "").strip().lower()
        if normalized == "read":
            session = await self.session_for_context(context, create=False)
            notes = await self._notes.get_notes(session["id"]) if session else {"content": "", "revision": 0}
            return {"success": True, **self._notes_summary(notes), "content": notes["content"]}
        if normalized not in ("append", "edit"):
            raise ChecklistError(f"Unknown action '{action}'. Use read, append, or edit.")
        if normalized == "append" and not str(text or "").strip():
            raise ChecklistError("text is required for append")
        if normalized == "edit" and not find:
            raise ChecklistError("find is required for edit: copy the exact text to replace from a read")
        session = await self._write_session(context)
        added = text if normalized == "append" else replace
        missing = await ungrounded_claims(
            str(added or ""), lambda service, method: receipt_exists(self._knowledge_service, session["id"], service, method),
        )
        if missing:
            return {"success": False, "error": grounding_error(missing)}
        if normalized == "append":
            result = await self._notes.append_notes(session["id"], str(text), actor=_CHECKLIST_WRITE_ACTOR)
        else:
            result = await self._notes.edit_notes(session["id"], str(find), str(replace or ""), actor=_CHECKLIST_WRITE_ACTOR)
        if not result.get("ok"):
            current = result.get("current") or {"content": "", "revision": 0}
            return {"success": False, "error": result.get("error", "The notes could not be changed."), **self._notes_summary(current)}
        if result.get("changed"):
            await self.publish(session["id"], self._ids(context))
        return {"success": True, "changed": bool(result.get("changed")), **self._notes_summary(result["notes"])}

    @staticmethod
    def _notes_summary(notes: Dict[str, Any]) -> Dict[str, Any]:
        used = len(notes.get("content") or "")
        summary: Dict[str, Any] = {"revision": notes.get("revision", 0), "characters_used": used, "limit": MAX_NOTES_CHARS}
        if used >= MAX_NOTES_CHARS * NOTES_NEAR_LIMIT_SHARE:
            summary["hint"] = "The notes are close to the limit. Condense them with an edit: they hold the current state, not a history."
        return summary

    async def carry_over(
        self,
        *,
        from_root_task_id: str,
        to_root_task_id: str,
        goal: Optional[str] = None,
        agent_task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Seed a new chain with the open and waiting items (and the notes) of an earlier chain. Done and dropped items stay behind."""
        source = await self.session_for_root(from_root_task_id, create=False)
        if source is None or from_root_task_id == to_root_task_id:
            return {"copied": 0, "notes_carried": False}
        source_notes = await self._notes.get_notes(source["id"])
        source_items = await self._items.list_items(source["id"], statuses=["pending", "in_progress", "waiting_external", "waiting_user"], limit=1)
        if not source_items and not source_notes["content"]:
            return {"copied": 0, "notes_carried": False}
        target = await self.session_for_root(to_root_task_id, create=True, goal=goal)
        copied = await self._items.copy_carryable_items(
            from_session_id=source["id"], to_session_id=target["id"], agent_task_id=agent_task_id,
        )
        notes_carried = False
        if source_notes["content"] and not (await self._notes.get_notes(target["id"]))["content"]:
            written = await self._notes.set_notes(
                target["id"], source_notes["content"], actor="system", carried_from_task_id=from_root_task_id,
            )
            notes_carried = bool(written.get("ok") and written.get("changed"))
        if copied or notes_carried:
            await self.publish(target["id"], {"root_task_id": to_root_task_id, "agent_task_id": agent_task_id})
        return {"copied": copied, "notes_carried": notes_carried}

    async def step_log(self, session_id: str, item_id: str) -> List[Dict[str, Any]]:
        return await self._items.list_events(session_id, item_id)


__all__ = ["AgentChecklistService", "ChecklistError", "SHORT_ID_CHARS", "item_for_model"]
