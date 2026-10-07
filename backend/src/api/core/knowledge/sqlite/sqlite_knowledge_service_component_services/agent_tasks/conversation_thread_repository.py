"""Per-task copies of the agent's model conversation, used to seed follow-up turns."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Sequence, TypeVar

from ..infrastructure.connection import run_read_transaction, run_write_transaction_async

_COLUMNS = (
    "agent_task_id, root_task_id, model_family, model_id, format_version, "
    "message_count, messages_json, created_at, updated_at"
)

T = TypeVar("T")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AgentConversationThreadRepository:
    """Row-level persistence for ``agent_conversation_threads``."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def _write(self, operation_name: str, body: Callable[[sqlite3.Connection], T]) -> T:
        return await run_write_transaction_async(self.db_path, operation_name, body, ensure_schema=False)

    async def _read(self, body: Callable[[sqlite3.Connection], T]) -> T:
        return await asyncio.to_thread(run_read_transaction, self.db_path, body, ensure_schema=False)

    async def save_thread(
        self,
        *,
        agent_task_id: str,
        root_task_id: str,
        model_family: str,
        model_id: str,
        format_version: int,
        message_count: int,
        messages_json: str,
    ) -> None:
        now = utc_now_iso()

        def _body(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO agent_conversation_threads (
                    agent_task_id, root_task_id, model_family, model_id, format_version,
                    message_count, messages_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_task_id) DO UPDATE SET
                    root_task_id = excluded.root_task_id,
                    model_family = excluded.model_family,
                    model_id = excluded.model_id,
                    format_version = excluded.format_version,
                    message_count = excluded.message_count,
                    messages_json = excluded.messages_json,
                    updated_at = excluded.updated_at
                """,
                (
                    agent_task_id,
                    root_task_id,
                    model_family,
                    model_id,
                    int(format_version),
                    int(message_count),
                    messages_json,
                    now,
                    now,
                ),
            )

        await self._write("agent_conversation_thread_save", _body)

    async def get_thread(self, agent_task_id: str) -> Optional[Dict[str, Any]]:
        def _body(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM agent_conversation_threads WHERE agent_task_id = ?",
                (agent_task_id,),
            ).fetchone()
            return {key: row[key] for key in row.keys()} if row is not None else None

        return await self._read(_body)

    async def delete_threads(self, agent_task_ids: Sequence[str]) -> int:
        ids = [str(task_id) for task_id in agent_task_ids if task_id]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)

        def _body(conn: sqlite3.Connection) -> int:
            return conn.execute(
                f"DELETE FROM agent_conversation_threads WHERE agent_task_id IN ({placeholders})",
                ids,
            ).rowcount

        return await self._write("agent_conversation_thread_delete", _body)
