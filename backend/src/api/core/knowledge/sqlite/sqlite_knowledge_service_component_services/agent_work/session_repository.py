"""Agent work session lifecycle persistence."""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from ..infrastructure.connection import get_sync_connection, run_write_transaction
from .records import (
    _get_item_counts_from_connection,
    _get_unresolved_item_counts,
    _json_dump,
    _normalize_status,
    _row_to_item,
    _row_to_session,
)


class AgentWorkSessionRepository:
    """CRUD and lifecycle helpers for durable iterative work sessions."""

    COMPLETE_SESSION_STATUSES = {"completed", "finished"}
    INCOMPLETE_SESSION_STATUSES = {"partial", "budget_exhausted", "user_stopped", "blocked"}

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def create_session(
        self,
        *,
        goal: str,
        collection_type: str,
        agent_task_id: Optional[str] = None,
        root_task_id: Optional[str] = None,
        scope: Optional[Dict[str, Any]] = None,
        strategy: Optional[Dict[str, Any]] = None,
        cursor: Optional[Dict[str, Any]] = None,
        summary_so_far: Optional[str] = None,
        item_budget: Optional[int] = None,
        token_budget: Optional[int] = None,
    ) -> Dict[str, Any]:
        session_id = str(uuid.uuid4())
        with get_sync_connection(self.db_path) as conn:
            if agent_task_id:
                existing_task = conn.execute(
                    "SELECT 1 FROM agent_tasks WHERE id = ?",
                    (agent_task_id,),
                ).fetchone()
                if not existing_task:
                    agent_task_id = None
            conn.execute(
                """
                INSERT INTO agent_work_sessions (
                    id, agent_task_id, root_task_id, goal, collection_type, scope_json, strategy_json,
                    cursor_json, summary_so_far, item_budget, token_budget
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    agent_task_id,
                    root_task_id,
                    goal,
                    collection_type,
                    _json_dump(scope),
                    _json_dump(strategy),
                    _json_dump(cursor),
                    summary_so_far,
                    item_budget,
                    token_budget,
                ),
            )
            conn.commit()
        created = await self.get_session(session_id)
        if not created:
            raise RuntimeError("Failed to load created work session")
        return created

    async def get_latest_session_for_root(
        self,
        root_task_id: str,
    ) -> Optional[Dict[str, Any]]:
        with get_sync_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_work_sessions
                WHERE root_task_id = ?
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (root_task_id,),
            ).fetchone()
        return _row_to_session(row) if row else None

    async def get_or_create_root_session(
        self,
        *,
        root_task_id: str,
        goal: str,
        collection_type: str,
        agent_task_id: Optional[str] = None,
        scope: Optional[Dict[str, Any]] = None,
        strategy: Optional[Dict[str, Any]] = None,
        cursor: Optional[Dict[str, Any]] = None,
        summary_so_far: Optional[str] = None,
        item_budget: Optional[int] = None,
        token_budget: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Atomically return one durable session for a root task."""
        if not str(root_task_id or "").strip():
            raise ValueError("root_task_id is required for an atomic root session.")
        def _get_or_create(conn: sqlite3.Connection) -> Dict[str, Any]:
            resolved_agent_task_id = agent_task_id
            row = conn.execute(
                """
                SELECT * FROM agent_work_sessions
                WHERE root_task_id = ?
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """,
                (root_task_id,),
            ).fetchone()
            if row:
                return _row_to_session(row)

            if resolved_agent_task_id and not conn.execute(
                "SELECT 1 FROM agent_tasks WHERE id = ?",
                (resolved_agent_task_id,),
            ).fetchone():
                resolved_agent_task_id = None
            session_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO agent_work_sessions (
                    id, agent_task_id, root_task_id, goal, collection_type, scope_json,
                    strategy_json, cursor_json, summary_so_far, item_budget, token_budget
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    resolved_agent_task_id,
                    root_task_id,
                    goal,
                    collection_type,
                    _json_dump(scope),
                    _json_dump(strategy),
                    _json_dump(cursor),
                    summary_so_far,
                    item_budget,
                    token_budget,
                ),
            )
            row = conn.execute(
                "SELECT * FROM agent_work_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            return _row_to_session(row)

        return run_write_transaction(
            self.db_path,
            "get_or_create_agent_work_session",
            _get_or_create,
        )

    async def update_scope(
        self,
        session_id: str,
        scope: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        with get_sync_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE agent_work_sessions
                SET scope_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (_json_dump(scope), session_id),
            )
            conn.commit()
        return await self.get_session(session_id)

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with get_sync_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM agent_work_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        return _row_to_session(row)

    async def update_strategy(
        self,
        *,
        session_id: str,
        strategy: Optional[Dict[str, Any]] = None,
        cursor: Optional[Dict[str, Any]] = None,
        summary_so_far: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        updates = ["updated_at = CURRENT_TIMESTAMP"]
        params: List[Any] = []
        if strategy is not None:
            updates.append("strategy_json = ?")
            params.append(_json_dump(strategy))
        if cursor is not None:
            updates.append("cursor_json = ?")
            params.append(_json_dump(cursor))
        if summary_so_far is not None:
            updates.append("summary_so_far = ?")
            params.append(summary_so_far)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        params.append(session_id)

        with get_sync_connection(self.db_path) as conn:
            conn.execute(
                f"UPDATE agent_work_sessions SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()
        return await self.get_session(session_id)

    async def summarize(self, session_id: str) -> Dict[str, Any]:
        session = await self.get_session(session_id)
        if not session:
            return {"success": False, "error": "Work session not found"}
        with get_sync_connection(self.db_path) as conn:
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
            sample_rows = conn.execute(
                """
                SELECT *
                FROM agent_work_items
                WHERE session_id = ?
                ORDER BY updated_at DESC
                LIMIT 10
                """,
                (session_id,),
            ).fetchall()
        counts = {row["status"]: row["count"] for row in rows}
        return {
            "success": True,
            "session": session,
            "item_counts": counts,
            "total_items": sum(counts.values()),
            "recent_items": [_row_to_item(row) for row in sample_rows],
        }

    async def finish(
        self,
        *,
        session_id: str,
        summary_so_far: Optional[str] = None,
        status: str = "finished",
    ) -> Optional[Dict[str, Any]]:
        with get_sync_connection(self.db_path) as conn:
            session_row = conn.execute(
                "SELECT * FROM agent_work_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if not session_row:
                return None

            normalized_status = _normalize_status(status)
            counts = _get_item_counts_from_connection(conn, session_id)
            unresolved_counts = _get_unresolved_item_counts(counts)
            if normalized_status in self.COMPLETE_SESSION_STATUSES and unresolved_counts:
                return {
                    "success": False,
                    "reason": "incomplete_coverage",
                    "error": "Cannot mark work session complete while unresolved claimable items remain.",
                    "session": _row_to_session(session_row),
                    "item_counts": counts,
                    "unresolved_counts": unresolved_counts,
                    "total_items": sum(counts.values()),
                    "allowed_incomplete_statuses": sorted(self.INCOMPLETE_SESSION_STATUSES),
                    "suggested_next_actions": ["claim_next", "update_strategy", "finish_as_partial"],
                }

            conn.execute(
                """
                UPDATE agent_work_sessions
                SET status = ?, summary_so_far = COALESCE(?, summary_so_far),
                    finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, summary_so_far, session_id),
            )
            conn.commit()
        return await self.get_session(session_id)
