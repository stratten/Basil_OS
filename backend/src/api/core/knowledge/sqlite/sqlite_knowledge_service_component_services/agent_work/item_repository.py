"""Agent work item persistence."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from ..infrastructure.connection import get_sync_connection
from .records import _json_dump, _resolve_item_id, _row_to_item


class AgentWorkItemRepository:
    """Query, add, claim, and update helpers for agent work items."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def get_items(
        self,
        *,
        session_id: str,
        statuses: Optional[List[str]] = None,
        external_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        conditions = ["session_id = ?"]
        params: List[Any] = [session_id]
        if statuses:
            conditions.append(f"status IN ({','.join('?' for _ in statuses)})")
            params.extend(statuses)
        if external_id:
            conditions.append("external_id = ?")
            params.append(external_id)
        params.append(min(max(int(limit or 1), 1), 50))
        with get_sync_connection(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM agent_work_items
                WHERE {' AND '.join(conditions)}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_row_to_item(row) for row in rows]

    async def add_items(
        self,
        *,
        session_id: str,
        items: List[Dict[str, Any]],
        batch_index: int = 0,
        default_status: str = "discovered",
    ) -> Dict[str, Any]:
        inserted = 0
        updated = 0
        with get_sync_connection(self.db_path) as conn:
            for item in items:
                provided_item_id = item.get("id")
                external_id = item.get("external_id")
                if external_id is None and provided_item_id is not None:
                    external_id = provided_item_id
                existing = None
                if external_id:
                    existing = conn.execute(
                        """
                        SELECT id FROM agent_work_items
                        WHERE session_id = ? AND external_id = ?
                        """,
                        (session_id, str(external_id)),
                    ).fetchone()

                item_id = existing["id"] if existing else str(uuid.uuid4())
                status = item.get("status") or default_status
                metadata = item.get("metadata") or {}
                decision = item.get("decision") or {}
                action_result = item.get("action_result") or {}
                detail_summary = item.get("detail_summary")
                error_message = item.get("error_message")

                if existing:
                    conn.execute(
                        """
                        UPDATE agent_work_items
                        SET batch_index = ?, status = ?, metadata_json = ?,
                            decision_json = ?, detail_summary = ?,
                            action_result_json = ?, error_message = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            batch_index,
                            status,
                            _json_dump(metadata),
                            _json_dump(decision),
                            detail_summary,
                            _json_dump(action_result),
                            error_message,
                            item_id,
                        ),
                    )
                    updated += 1
                else:
                    conn.execute(
                        """
                        INSERT INTO agent_work_items (
                            id, session_id, external_id, batch_index, status,
                            metadata_json, decision_json, detail_summary,
                            action_result_json, error_message
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item_id,
                            session_id,
                            str(external_id) if external_id is not None else None,
                            batch_index,
                            status,
                            _json_dump(metadata),
                            _json_dump(decision),
                            detail_summary,
                            _json_dump(action_result),
                            error_message,
                        ),
                    )
                    inserted += 1
            conn.execute(
                "UPDATE agent_work_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (session_id,),
            )
            conn.commit()
        return {"inserted": inserted, "updated": updated, "count": inserted + updated}

    async def claim_next(
        self,
        *,
        session_id: str,
        statuses: Optional[List[str]] = None,
        limit: int = 5,
        mark_status: Optional[str] = "in_progress",
    ) -> List[Dict[str, Any]]:
        statuses = statuses or ["discovered", "selected", "expanded", "failed"]
        placeholders = ",".join("?" for _ in statuses)
        limit = min(max(int(limit or 1), 1), 50)
        params: List[Any] = [session_id, *statuses, limit]
        with get_sync_connection(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM agent_work_items
                WHERE session_id = ?
                  AND status IN ({placeholders})
                ORDER BY batch_index ASC, created_at ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
            item_ids = [row["id"] for row in rows]
            if item_ids and mark_status:
                update_placeholders = ",".join("?" for _ in item_ids)
                conn.execute(
                    f"""
                    UPDATE agent_work_items
                    SET status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id IN ({update_placeholders})
                    """,
                    [mark_status, *item_ids],
                )
                rows = conn.execute(
                    f"SELECT * FROM agent_work_items WHERE id IN ({update_placeholders})",
                    item_ids,
                ).fetchall()
            conn.commit()
        return [_row_to_item(row) for row in rows]

    async def update_items(self, *, session_id: str, updates: List[Dict[str, Any]]) -> Dict[str, Any]:
        changed = 0
        with get_sync_connection(self.db_path) as conn:
            for update in updates:
                item_id = update.get("id")
                external_id = update.get("external_id")
                item_id = _resolve_item_id(conn, session_id, item_id, external_id)
                if not item_id:
                    continue

                assignments = ["updated_at = CURRENT_TIMESTAMP"]
                params: List[Any] = []
                field_map = {
                    "status": "status",
                    "metadata": "metadata_json",
                    "decision": "decision_json",
                    "detail_summary": "detail_summary",
                    "action_result": "action_result_json",
                    "error_message": "error_message",
                }
                for input_key, column in field_map.items():
                    if input_key not in update:
                        continue
                    assignments.append(f"{column} = ?")
                    value = update[input_key]
                    if input_key in {"metadata", "decision", "action_result"}:
                        value = _json_dump(value)
                    params.append(value)

                params.extend([session_id, item_id])
                conn.execute(
                    f"""
                    UPDATE agent_work_items
                    SET {', '.join(assignments)}
                    WHERE session_id = ? AND id = ?
                    """,
                    params,
                )
                changed += 1
            conn.execute(
                "UPDATE agent_work_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (session_id,),
            )
            conn.commit()
        return {"updated": changed}

