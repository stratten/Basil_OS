"""Shared JSON, row mapping, count, and item identity helpers."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Optional

CLAIMABLE_ITEM_STATUSES = {
    "discovered",
    "selected",
    "expanded",
    "in_progress",
    "failed",
    "needs_detail",
}

def _json_dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)

def _json_load(raw: Optional[str]) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}

def _row_to_session(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "agent_task_id": row["agent_task_id"],
        "root_task_id": row["root_task_id"],
        "goal": row["goal"],
        "collection_type": row["collection_type"],
        "scope": _json_load(row["scope_json"]),
        "strategy": _json_load(row["strategy_json"]),
        "cursor": _json_load(row["cursor_json"]),
        "status": row["status"],
        "summary_so_far": row["summary_so_far"],
        "item_budget": row["item_budget"],
        "token_budget": row["token_budget"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "finished_at": row["finished_at"],
    }

def _row_to_item(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "external_id": row["external_id"],
        "entity_type": row["entity_type"],
        "source_system": row["source_system"],
        "source_scope": _json_load(row["source_scope_json"]),
        "identity_quality": row["identity_quality"],
        "batch_index": row["batch_index"],
        "status": row["status"],
        "metadata": _json_load(row["metadata_json"]),
        "decision": _json_load(row["decision_json"]),
        "detail_summary": row["detail_summary"],
        "action_result": _json_load(row["action_result_json"]),
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

def _normalize_status(status: Optional[str]) -> str:
    return (status or "").strip().lower()

def _get_item_counts_from_connection(conn: sqlite3.Connection, session_id: str) -> Dict[str, int]:
    rows = conn.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM agent_work_items
        WHERE session_id = ?
        GROUP BY status
        ORDER BY status
        """,
        (session_id,),
    ).fetchall()
    return {row["status"]: row["count"] for row in rows}

def _get_unresolved_item_counts(counts: Dict[str, int]) -> Dict[str, int]:
    return {
        status: count
        for status, count in counts.items()
        if _normalize_status(status) in CLAIMABLE_ITEM_STATUSES and count > 0
    }

def _resolve_item_id(conn: sqlite3.Connection, session_id: str, item_id: Optional[Any], external_id: Optional[Any]) -> Optional[str]:
    if item_id is not None:
        row = conn.execute(
            """
            SELECT id FROM agent_work_items
            WHERE session_id = ? AND id = ?
            """,
            (session_id, str(item_id)),
        ).fetchone()
        if row:
            return row["id"]

        row = conn.execute(
            """
            SELECT id FROM agent_work_items
            WHERE session_id = ? AND external_id = ?
            """,
            (session_id, str(item_id)),
        ).fetchone()
        if row:
            return row["id"]

    if external_id is not None:
        row = conn.execute(
            """
            SELECT id FROM agent_work_items
            WHERE session_id = ? AND external_id = ?
            """,
            (session_id, str(external_id)),
        ).fetchone()
        return row["id"] if row else None

    return None
