"""Append-only history for durable agent work entities and sessions."""

from __future__ import annotations

import json
import sqlite3

from ..infrastructure.connection import get_sync_connection
import uuid
from typing import Any, Dict, List, Optional

from api.services.agent_processing.lifecycle.runtime.ledger_json import (
    to_ledger_json_value,
)


class AgentWorkEventRepository:
    """Write and read immutable ledger events in deterministic order."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        return get_sync_connection(self.db_path)

    @staticmethod
    def _json_dump(value: Any) -> str:
        return json.dumps(
            to_ledger_json_value(value if value is not None else {}),
            ensure_ascii=False,
            sort_keys=True,
        )

    @staticmethod
    def _json_load(raw: Optional[str]) -> Dict[str, Any]:
        try:
            return json.loads(raw) if raw else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    @classmethod
    def _row_to_event(cls, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "item_id": row["item_id"],
            "agent_task_id": row["agent_task_id"],
            "event_kind": row["event_kind"],
            "payload": cls._json_load(row["payload_json"]),
            "created_at": row["created_at"],
        }

    async def add_event(
        self,
        *,
        session_id: str,
        event_kind: str,
        payload: Optional[Dict[str, Any]] = None,
        item_id: Optional[str] = None,
        agent_task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not str(event_kind or "").strip():
            raise ValueError("event_kind is required.")
        event_id = str(uuid.uuid4())
        with self._get_connection() as conn:
            if agent_task_id and not conn.execute(
                "SELECT 1 FROM agent_tasks WHERE id = ?",
                (agent_task_id,),
            ).fetchone():
                agent_task_id = None
            conn.execute(
                """
                INSERT INTO agent_work_events (
                    id, session_id, item_id, agent_task_id, event_kind, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    session_id,
                    item_id,
                    agent_task_id,
                    event_kind,
                    self._json_dump(payload),
                ),
            )
            row = conn.execute(
                "SELECT * FROM agent_work_events WHERE id = ?",
                (event_id,),
            ).fetchone()
            conn.commit()
        return self._row_to_event(row)

    async def get_events(
        self,
        *,
        session_id: str,
        item_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        conditions = ["session_id = ?"]
        params: List[Any] = [session_id]
        if item_id:
            conditions.append("item_id = ?")
            params.append(item_id)
        params.append(min(max(int(limit or 1), 1), 500))
        with self._get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM agent_work_events
                WHERE {' AND '.join(conditions)}
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_event(row) for row in rows]
