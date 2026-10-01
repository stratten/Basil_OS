"""Durable agent-requested follow-up checks that resume an Agent Task chain later."""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, TypeVar

from ..infrastructure.connection import run_read_transaction, run_write_transaction_async

MAX_PENDING_FOLLOW_UPS_PER_ROOT = 5
MAX_TOTAL_FOLLOW_UPS_PER_ROOT = 50

_COLUMNS = (
    "id, root_task_id, source_agent_task_id, instructions, reason, due_at, status, "
    "defer_count, follow_up_agent_task_id, error_message, created_at, updated_at"
)
_FINISH_STATUSES = frozenset({"failed", "missed", "canceled"})

T = TypeVar("T")


class FollowUpLimitExceeded(ValueError):
    """Raised when a task chain already holds the maximum number of follow-ups."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


class AgentTaskFollowUpRepository:
    """Row-level persistence for ``agent_task_follow_ups``."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def _write(self, operation_name: str, body: Callable[[sqlite3.Connection], T]) -> T:
        return await run_write_transaction_async(self.db_path, operation_name, body, ensure_schema=False)

    async def _read(self, body: Callable[[sqlite3.Connection], T]) -> T:
        return await asyncio.to_thread(run_read_transaction, self.db_path, body, ensure_schema=False)

    async def create_follow_up(
        self,
        *,
        root_task_id: str,
        source_agent_task_id: str,
        instructions: str,
        reason: str,
        due_at: str,
    ) -> Dict[str, Any]:
        follow_up_id = str(uuid.uuid4())
        now = utc_now_iso()

        def _body(conn: sqlite3.Connection) -> Dict[str, Any]:
            pending = conn.execute(
                "SELECT COUNT(*) FROM agent_task_follow_ups WHERE root_task_id = ? AND status IN ('scheduled', 'dispatching')",
                (root_task_id,),
            ).fetchone()[0]
            if pending >= MAX_PENDING_FOLLOW_UPS_PER_ROOT:
                raise FollowUpLimitExceeded(
                    f"This task already has {pending} pending follow-ups (limit {MAX_PENDING_FOLLOW_UPS_PER_ROOT}). Cancel one or ask the user before scheduling more."
                )
            total = conn.execute(
                "SELECT COUNT(*) FROM agent_task_follow_ups WHERE root_task_id = ?",
                (root_task_id,),
            ).fetchone()[0]
            if total >= MAX_TOTAL_FOLLOW_UPS_PER_ROOT:
                raise FollowUpLimitExceeded(
                    f"This task has already used {total} follow-ups (limit {MAX_TOTAL_FOLLOW_UPS_PER_ROOT}). Ask the user whether to keep checking."
                )
            conn.execute(
                """
                INSERT INTO agent_task_follow_ups (
                    id, root_task_id, source_agent_task_id, instructions, reason,
                    due_at, status, defer_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'scheduled', 0, ?, ?)
                """,
                (follow_up_id, root_task_id, source_agent_task_id, instructions, reason, due_at, now, now),
            )
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM agent_task_follow_ups WHERE id = ?",
                (follow_up_id,),
            ).fetchone()
            return _row_to_dict(row)

        return await self._write("agent_follow_up_create", _body)

    async def get_follow_up(self, follow_up_id: str) -> Optional[Dict[str, Any]]:
        def _body(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM agent_task_follow_ups WHERE id = ?",
                (follow_up_id,),
            ).fetchone()
            return _row_to_dict(row) if row is not None else None

        return await self._read(_body)

    async def list_for_root(self, root_task_id: str) -> List[Dict[str, Any]]:
        def _body(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM agent_task_follow_ups WHERE root_task_id = ? ORDER BY created_at ASC, id ASC",
                (root_task_id,),
            ).fetchall()
            return [_row_to_dict(row) for row in rows]

        return await self._read(_body)

    async def claim_due_follow_ups(self, *, now_iso: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Atomically move due ``scheduled`` rows to ``dispatching`` and return them."""

        def _body(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM agent_task_follow_ups WHERE status = 'scheduled' AND due_at <= ? ORDER BY due_at ASC, id ASC LIMIT ?",
                (now_iso, int(limit)),
            ).fetchall()
            claimed: List[Dict[str, Any]] = []
            for row in rows:
                updated = conn.execute(
                    "UPDATE agent_task_follow_ups SET status = 'dispatching', updated_at = ? WHERE id = ? AND status = 'scheduled'",
                    (now_iso, row["id"]),
                ).rowcount
                if updated:
                    record = _row_to_dict(row)
                    record["status"] = "dispatching"
                    claimed.append(record)
            return claimed

        return await self._write("agent_follow_up_claim", _body)

    async def mark_submitted(self, follow_up_id: str, *, follow_up_agent_task_id: str) -> bool:
        now = utc_now_iso()

        def _body(conn: sqlite3.Connection) -> bool:
            return bool(
                conn.execute(
                    "UPDATE agent_task_follow_ups SET status = 'submitted', follow_up_agent_task_id = ?, error_message = NULL, updated_at = ? WHERE id = ? AND status = 'dispatching'",
                    (follow_up_agent_task_id, now, follow_up_id),
                ).rowcount
            )

        return await self._write("agent_follow_up_mark_submitted", _body)

    async def finish_without_submission(self, follow_up_id: str, *, status: str, error_message: str) -> bool:
        if status not in _FINISH_STATUSES:
            raise ValueError(f"Unsupported follow-up finish status: {status!r}")
        now = utc_now_iso()

        def _body(conn: sqlite3.Connection) -> bool:
            return bool(
                conn.execute(
                    "UPDATE agent_task_follow_ups SET status = ?, error_message = ?, updated_at = ? WHERE id = ? AND status = 'dispatching'",
                    (status, error_message, now, follow_up_id),
                ).rowcount
            )

        return await self._write("agent_follow_up_finish", _body)

    async def defer_follow_up(self, follow_up_id: str, *, due_at: str, reason: str) -> bool:
        now = utc_now_iso()

        def _body(conn: sqlite3.Connection) -> bool:
            return bool(
                conn.execute(
                    "UPDATE agent_task_follow_ups SET status = 'scheduled', due_at = ?, defer_count = defer_count + 1, error_message = ?, updated_at = ? WHERE id = ? AND status = 'dispatching'",
                    (due_at, reason, now, follow_up_id),
                ).rowcount
            )

        return await self._write("agent_follow_up_defer", _body)

    async def cancel_pending_for_root(self, root_task_id: str, *, reason: str) -> int:
        now = utc_now_iso()

        def _body(conn: sqlite3.Connection) -> int:
            return int(
                conn.execute(
                    "UPDATE agent_task_follow_ups SET status = 'canceled', error_message = ?, updated_at = ? WHERE root_task_id = ? AND status = 'scheduled'",
                    (reason, now, root_task_id),
                ).rowcount
            )

        return await self._write("agent_follow_up_cancel_for_root", _body)

    async def recover_interrupted_dispatches(self) -> int:
        """Return rows a previous process claimed but never finished to ``scheduled``."""
        now = utc_now_iso()

        def _body(conn: sqlite3.Connection) -> int:
            return int(
                conn.execute(
                    "UPDATE agent_task_follow_ups SET status = 'scheduled', updated_at = ? WHERE status = 'dispatching'",
                    (now,),
                ).rowcount
            )

        return await self._write("agent_follow_up_recover", _body)


__all__ = [
    "AgentTaskFollowUpRepository",
    "FollowUpLimitExceeded",
    "MAX_PENDING_FOLLOW_UPS_PER_ROOT",
    "MAX_TOTAL_FOLLOW_UPS_PER_ROOT",
    "utc_now_iso",
]
