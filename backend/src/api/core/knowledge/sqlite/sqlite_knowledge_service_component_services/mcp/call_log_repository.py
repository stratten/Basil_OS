"""Persistence for the MCP connector audit log.

Mirrors the structure of ``scheduled_agent_task_repository.py``: this class is
the data-access layer only — every row inserted here represents a single
``external_catalog.call_tool`` dispatch (or a denied/skipped attempt at
one). Higher-level orchestration, normalization, and approval policy live
one layer up in ``api.services.mcp_connectors.*``.

Each row is intentionally cheap to insert: callers are encouraged to
record both successes and failures so the Settings → Connections audit
view can show users a complete history of what their agent did on their
behalf via remote connectors.
"""

from __future__ import annotations

import json
import logging
import sqlite3

from ..infrastructure.connection import run_in_worker_thread, get_sync_connection
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MCPCallLogRepository:
    """CRUD/query helpers for the ``mcp_call_log`` audit table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        return get_sync_connection(self.db_path)

    @staticmethod
    def _serialize_args(args: Optional[Dict[str, Any]]) -> Optional[str]:
        if args is None:
            return None
        try:
            return json.dumps(args)
        except (TypeError, ValueError):
            return json.dumps({"_unserializable": True, "_repr": repr(args)[:500]})

    @staticmethod
    def _row_to_call(row: sqlite3.Row) -> Dict[str, Any]:
        raw_args = row["arguments_json"]
        try:
            args = json.loads(raw_args) if raw_args else None
        except Exception:
            args = None
        return {
            "id": row["id"],
            "connection_id": row["connection_id"],
            "server_url": row["server_url"],
            "tool_name": row["tool_name"],
            "arguments": args,
            "result_classification": row["result_classification"],
            "error_kind": row["error_kind"],
            "error_message": row["error_message"],
            "content_preview": row["content_preview"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "agent_task_id": row["agent_task_id"],
        }

    @run_in_worker_thread
    def _insert_call_row(
        self,
        call_id: str,
        connection_id: str,
        server_url: str,
        tool_name: str,
        arguments_json: Optional[str],
        result_classification: str,
        error_kind: Optional[str],
        error_message: Optional[str],
        content_preview: Optional[str],
        started_at_iso: str,
        completed_at_iso: Optional[str],
        agent_task_id: Optional[str],
    ) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO mcp_call_log (
                    id, connection_id, server_url, tool_name, arguments_json,
                    result_classification, error_kind, error_message, content_preview,
                    started_at, completed_at, agent_task_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call_id,
                    connection_id,
                    server_url,
                    tool_name,
                    arguments_json,
                    result_classification,
                    error_kind,
                    error_message,
                    content_preview,
                    started_at_iso,
                    completed_at_iso,
                    agent_task_id,
                ),
            )
            conn.commit()

    async def record_call(
        self,
        *,
        connection_id: str,
        server_url: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]],
        result_classification: str,
        started_at: datetime,
        completed_at: Optional[datetime] = None,
        error_kind: Optional[str] = None,
        error_message: Optional[str] = None,
        content_preview: Optional[str] = None,
        agent_task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert one audit-log row and return the persisted record.

        ``result_classification`` must be one of ``success``, ``error``,
        ``denied``, ``skipped``. The free-form ``error_kind`` carries the
        normalized envelope kind (e.g. ``auth_expired``, ``rate_limited``,
        ``permission_denied``) when classification is not ``success``.
        """
        call_id = str(uuid.uuid4())
        await self._insert_call_row(
            call_id,
            connection_id,
            server_url,
            tool_name,
            self._serialize_args(arguments),
            result_classification,
            error_kind,
            error_message,
            content_preview,
            started_at.isoformat(),
            completed_at.isoformat() if completed_at else None,
            agent_task_id,
        )
        record = await self.get_call(call_id)
        if record is None:
            raise RuntimeError("Failed to load freshly recorded MCP call")
        return record

    @run_in_worker_thread
    def get_call(self, call_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM mcp_call_log WHERE id = ?",
                (call_id,),
            ).fetchone()
        return self._row_to_call(row) if row else None

    @run_in_worker_thread
    def list_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM mcp_call_log
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_call(row) for row in rows]

    @run_in_worker_thread
    def list_by_connection(
        self,
        connection_id: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM mcp_call_log
                WHERE connection_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (connection_id, limit),
            ).fetchall()
        return [self._row_to_call(row) for row in rows]

    @run_in_worker_thread
    def list_successful_calls_for_item(
        self,
        connection_id: str,
        tool_names: List[str],
        item_argument: str,
        item_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Successful calls to any of ``tool_names`` on one connection whose ``item_argument`` equals ``item_id``, newest first.

        ``item_argument`` is a top-level argument name such as ``threadId``. It is bound as a JSON path
        parameter, never interpolated, so it cannot alter the statement.
        """
        if not tool_names or not item_id:
            return []
        placeholders = ", ".join("?" for _ in tool_names)
        with self._get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM mcp_call_log
                WHERE connection_id = ?
                  AND result_classification = 'success'
                  AND tool_name IN ({placeholders})
                  AND json_extract(arguments_json, ?) = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (connection_id, *tool_names, f"$.{item_argument}", item_id, limit),
            ).fetchall()
        return [self._row_to_call(row) for row in rows]

    @run_in_worker_thread
    def list_successful_calls_for_task(
        self,
        connection_id: str,
        tool_names: List[str],
        agent_task_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Successful calls to any of ``tool_names`` on one connection made by one agent task, newest first."""
        if not tool_names or not agent_task_id:
            return []
        placeholders = ", ".join("?" for _ in tool_names)
        with self._get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM mcp_call_log
                WHERE connection_id = ?
                  AND result_classification = 'success'
                  AND tool_name IN ({placeholders})
                  AND agent_task_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (connection_id, *tool_names, agent_task_id, limit),
            ).fetchall()
        return [self._row_to_call(row) for row in rows]

    @run_in_worker_thread
    def delete_for_connection(self, connection_id: str) -> int:
        """Hard-delete every audit row tied to ``connection_id``.

        Used by the Settings UI when a user removes a connection so the
        audit list shown to other users of the machine doesn't retain
        history for an account they no longer have access to.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM mcp_call_log WHERE connection_id = ?",
                (connection_id,),
            )
            conn.commit()
            return cursor.rowcount
