"""Constants, normalizers, and row mappers shared by the agent checklist repositories."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

CHECKLIST_STATUSES = ("pending", "in_progress", "waiting_external", "waiting_user", "done", "dropped")
OPEN_CHECKLIST_STATUSES = ("pending", "in_progress", "waiting_external", "waiting_user")
CARRYABLE_CHECKLIST_STATUSES = ("pending", "in_progress", "waiting_external", "waiting_user")
CHECKLIST_ORIGINS = ("agent", "user", "carried")
CHECKLIST_ACTORS = ("agent", "user", "system")
CHECKLIST_REF_ROLES = ("origin", "delegated_to", "produced", "related")

MAX_ITEMS_PER_SESSION = 500
MAX_REFS_PER_ITEM = 12
MAX_EVENTS_PER_ITEM = 200
MAX_TITLE_CHARS = 500
MAX_DETAIL_CHARS = 2000
MAX_ITEM_NOTE_CHARS = 600
MAX_WAITING_ON_CHARS = 200
MAX_REF_LABEL_CHARS = 120
MAX_REF_FIELD_CHARS = 300
MAX_EVENT_TEXT_CHARS = 400
MAX_NOTES_CHARS = 4000

# Fields a caller may change on an existing item. Everything else is owned by the repository.
EDITABLE_ITEM_FIELDS = (
    "title",
    "detail",
    "status",
    "required",
    "note",
    "waiting_on",
    "recheck_at",
    "sort_order",
)


def clip(value: Any, limit: int) -> str:
    """Return a stripped string no longer than limit characters."""
    text = str(value if value is not None else "").strip()
    return text[:limit]


def normalize_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status not in CHECKLIST_STATUSES:
        raise ValueError(f"status must be one of {', '.join(CHECKLIST_STATUSES)}")
    return status


def normalize_actor(value: Any) -> str:
    actor = str(value or "agent").strip().lower()
    return actor if actor in CHECKLIST_ACTORS else "agent"


def normalize_ref(raw: Dict[str, Any], *, added_by: str) -> Dict[str, str]:
    """Validate one reference pointer. References are pointers for display and lookup, never permissions."""
    external_id = clip(raw.get("external_id"), MAX_REF_FIELD_CHARS)
    ref_kind = clip(raw.get("ref_kind"), 60)
    if not external_id or not ref_kind:
        raise ValueError("a reference needs ref_kind and external_id")
    role = str(raw.get("role") or "related").strip().lower()
    return {
        "role": role if role in CHECKLIST_REF_ROLES else "related",
        "ref_kind": ref_kind,
        "source_system": clip(raw.get("source_system"), 80),
        "source_scope": clip(raw.get("source_scope"), MAX_REF_FIELD_CHARS),
        "external_id": external_id,
        "label": clip(raw.get("label"), MAX_REF_LABEL_CHARS),
        "open_url": clip(raw.get("open_url"), 500),
        "added_by": added_by if added_by in ("agent", "user", "capture") else "agent",
        "last_known_status": clip(raw.get("last_known_status"), 80),
    }


def row_to_item(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "origin": row["origin"],
        "title": row["title"],
        "detail": row["detail"],
        "status": row["status"],
        "done_basis": row["done_basis"],
        "required": bool(row["required"]),
        "note": row["note"],
        "waiting_on": row["waiting_on"],
        "recheck_at": row["recheck_at"],
        "sort_order": row["sort_order"],
        "work_item_id": row["work_item_id"],
        "carried_from_item_id": row["carried_from_item_id"],
        "archived_at": row["archived_at"],
        "revision": row["revision"],
        "created_by_task_id": row["created_by_task_id"],
        "updated_by_task_id": row["updated_by_task_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "refs": [],
    }


def row_to_ref(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "item_id": row["item_id"],
        "role": row["role"],
        "ref_kind": row["ref_kind"],
        "source_system": row["source_system"],
        "source_scope": row["source_scope"],
        "external_id": row["external_id"],
        "label": row["label"],
        "open_url": row["open_url"],
        "added_by": row["added_by"],
        "last_known_status": row["last_known_status"],
        "last_known_at": row["last_known_at"],
    }


def row_to_event(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "item_id": row["item_id"],
        "agent_task_id": row["agent_task_id"],
        "kind": row["kind"],
        "actor": row["actor"],
        "text": row["text"],
        "created_at": row["created_at"],
    }


def counts_from_rows(rows: list[sqlite3.Row]) -> Dict[str, int]:
    """Summarize (status, required) rows. The counter excludes archived and dropped items."""
    counts = {"total": 0, "done": 0, "open": 0, "waiting_user": 0, "waiting_external": 0, "required_open": 0}
    for row in rows:
        status = row["status"]
        if status == "dropped":
            continue
        counts["total"] += 1
        if status == "done":
            counts["done"] += 1
            continue
        counts["open"] += 1
        if status == "waiting_user":
            counts["waiting_user"] += 1
        elif status == "waiting_external":
            counts["waiting_external"] += 1
        if row["required"]:
            counts["required_open"] += 1
    return counts


def optional_text(value: Optional[Any]) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None
