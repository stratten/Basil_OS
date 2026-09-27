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

from ..infrastructure.connection import get_sync_connection
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
                    self._serialize_args(arguments),
                    result_classification,
                    error_kind,
                    error_message,
                    content_preview,
                    started_at.isoformat(),
                    completed_at.isoformat() if completed_at else None,
                    agent_task_id,
                ),
            )
            conn.commit()
        record = await self.get_call(call_id)
        if record is None:
            raise RuntimeError("Failed to load freshly recorded MCP call")
        return record

    async def get_call(self, call_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM mcp_call_log WHERE id = ?",
                (call_id,),
            ).fetchone()
        return self._row_to_call(row) if row else None

    async def list_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
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

    async def list_by_connection(
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

    async def delete_for_connection(self, connection_id: str) -> int:
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
