"""Durable generic execution approvals for shell and AppleScript tools."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Mapping, Optional

from ..infrastructure.connection import get_sync_connection, run_write_transaction


class ExecutionApprovalPersistenceError(RuntimeError):
    """Base error for execution-approval persistence failures."""


class ExecutionApprovalConflictError(ExecutionApprovalPersistenceError):
    """Stale revision, unknown approval, or invalid task preconditions."""


TERMINAL_APPROVAL_STATUSES = {"approved", "denied", "canceled"}


class ExecutionApprovalRepository:
    """Persist durable generic tool execution approvals linked to one Agent Task."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        return get_sync_connection(self.db_path)

    @staticmethod
    def _utcnow() -> str:
        return datetime.utcnow().isoformat()

    @staticmethod
    def _require_nonblank(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ExecutionApprovalPersistenceError(f"{field_name} must be a nonblank string")
        return value.strip()

    @staticmethod
    def _json_dump(value: Any) -> str:
        return json.dumps(value if value is not None else {}, ensure_ascii=False)

    @staticmethod
    def _json_load(raw: Optional[str]) -> Any:
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {}

    @classmethod
    def _row_to_approval(cls, row: sqlite3.Row | None) -> dict[str, object] | None:
        if row is None:
            return None
        return {
            "id": row["id"],
            "agent_task_id": row["agent_task_id"],
            "root_task_id": row["root_task_id"],
            "execution_type": row["execution_type"],
            "command": row["command"],
            "script_content": row["script_content"],
            "reason": row["reason"],
            "risk_level": row["risk_level"],
            "generalized_pattern": row["generalized_pattern"],
            "render_context": cls._json_load(row["render_context_json"]),
            "status": row["status"],
            "remember_choice": bool(row["remember_choice"]),
            "pattern_type": row["pattern_type"],
            "revision": row["revision"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "resolved_at": row["resolved_at"],
        }

    async def create_pending_approval(
        self,
        *,
        agent_task_id: str,
        root_task_id: str,
        execution_type: str,
        command: str,
        reason: str,
        risk_level: str,
        generalized_pattern: str,
        render_context: Mapping[str, Any],
        script_content: Optional[str] = None,
    ) -> dict[str, object]:
        task_id = self._require_nonblank(agent_task_id, "agent_task_id")
        root_id = self._require_nonblank(root_task_id, "root_task_id")
        cleaned_command = self._require_nonblank(command, "command")
        cleaned_reason = self._require_nonblank(reason, "reason")
        cleaned_pattern = self._require_nonblank(generalized_pattern, "generalized_pattern")
        approval_id = str(uuid.uuid4())
        timestamp = self._utcnow()

        def _body(conn: sqlite3.Connection) -> str:
            if not conn.execute(
                "SELECT 1 FROM agent_tasks WHERE id = ?",
                (task_id,),
            ).fetchone():
                raise ExecutionApprovalConflictError(f"agent task {task_id!r} does not exist")
            conn.execute(
                """
                INSERT INTO execution_approvals (
                    id, agent_task_id, root_task_id, execution_type, command, script_content,
                    reason, risk_level, generalized_pattern, render_context_json,
                    status, remember_choice, pattern_type, revision, created_at, updated_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, NULL, 0, ?, ?, NULL)
                """,
                (
                    approval_id,
                    task_id,
                    root_id,
                    execution_type,
                    cleaned_command,
                    script_content,
                    cleaned_reason,
                    risk_level,
                    cleaned_pattern,
                    self._json_dump(dict(render_context)),
                    timestamp,
                    timestamp,
                ),
            )
            task_update = conn.execute(
                """
                UPDATE agent_tasks
                SET status = 'awaiting_user_input', updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status NOT IN ('completed', 'failed', 'canceled')
                """,
                (task_id,),
            )
            if task_update.rowcount != 1:
                raise ExecutionApprovalConflictError(
                    f"agent task {task_id!r} is terminal and cannot await approval"
                )
            return approval_id

        try:
            created_id = run_write_transaction(
                self.db_path,
                "create_pending_execution_approval",
                _body,
            )
        except sqlite3.IntegrityError as exc:
            raise ExecutionApprovalConflictError(
                f"execution approval could not be created for agent task {task_id!r}"
            ) from exc

        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM execution_approvals WHERE id = ?",
                (created_id,),
            ).fetchone()
        if row is None:
            raise ExecutionApprovalPersistenceError("failed to load created execution approval")
        return self._row_to_approval(row)  # type: ignore[return-value]

    async def get_approval(self, approval_id: str) -> dict[str, object] | None:
        clean_id = self._require_nonblank(approval_id, "approval_id")
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM execution_approvals WHERE id = ?",
                (clean_id,),
            ).fetchone()
        return self._row_to_approval(row)

    async def list_pending_approvals_for_agent_task(
        self,
        agent_task_id: str,
    ) -> list[dict[str, object]]:
        """Return every pending approval for one task in presentation order."""
        task_id = self._require_nonblank(agent_task_id, "agent_task_id")
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM execution_approvals
                WHERE agent_task_id = ? AND status = 'pending'
                ORDER BY created_at ASC, id ASC
                """,
                (task_id,),
            ).fetchall()
        return [
            approval
            for row in rows
            if (approval := self._row_to_approval(row)) is not None
        ]

    async def get_pending_approval_for_agent_task(
        self,
        agent_task_id: str,
    ) -> dict[str, object] | None:
        task_id = self._require_nonblank(agent_task_id, "agent_task_id")
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM execution_approvals
                WHERE agent_task_id = ? AND status = 'pending'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        return self._row_to_approval(row)

    async def resolve_pending_approval(
        self,
        *,
        approval_id: str,
        agent_task_id: str,
        expected_revision: int,
        approved: bool,
        remember_choice: bool = False,
        pattern_type: Optional[str] = None,
    ) -> dict[str, object]:
        clean_id = self._require_nonblank(approval_id, "approval_id")
        task_id = self._require_nonblank(agent_task_id, "agent_task_id")
        if type(expected_revision) is not int:
            raise ExecutionApprovalPersistenceError("expected_revision must be an integer")
        next_status = "approved" if approved else "denied"
        timestamp = self._utcnow()

        def _body(conn: sqlite3.Connection) -> None:
            row = conn.execute(
                "SELECT * FROM execution_approvals WHERE id = ?",
                (clean_id,),
            ).fetchone()
            if row is None:
                raise ExecutionApprovalConflictError(f"execution approval {clean_id!r} does not exist")
            if row["agent_task_id"] != task_id:
                raise ExecutionApprovalConflictError(
                    f"execution approval {clean_id!r} does not belong to agent task {task_id!r}"
                )
            if row["revision"] != expected_revision:
                raise ExecutionApprovalConflictError(
                    f"execution approval {clean_id!r} revision mismatch: expected "
                    f"{expected_revision}, got {row['revision']}"
                )
            if row["status"] != "pending":
                raise ExecutionApprovalConflictError(
                    f"execution approval {clean_id!r} is not pending (status={row['status']!r})"
                )
            updated = conn.execute(
                """
                UPDATE execution_approvals
                SET status = ?, remember_choice = ?, pattern_type = ?,
                    updated_at = ?, resolved_at = ?, revision = revision + 1
                WHERE id = ? AND status = 'pending' AND revision = ?
                """,
                (
                    next_status,
                    1 if remember_choice else 0,
                    pattern_type,
                    timestamp,
                    timestamp,
                    clean_id,
                    expected_revision,
                ),
            )
            if updated.rowcount != 1:
                raise ExecutionApprovalConflictError(
                    f"execution approval {clean_id!r} could not transition to {next_status!r}"
                )
            remaining_pending = conn.execute(
                """
                SELECT 1 FROM execution_approvals
                WHERE agent_task_id = ? AND status = 'pending'
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()
            if remaining_pending is None:
                task_update = conn.execute(
                    """
                    UPDATE agent_tasks
                    SET status = 'processing', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status = 'awaiting_user_input'
                    """,
                    (task_id,),
                )
                if task_update.rowcount != 1:
                    raise ExecutionApprovalConflictError(
                        f"agent task {task_id!r} is no longer awaiting approval"
                    )

        run_write_transaction(self.db_path, "resolve_pending_execution_approval", _body)

        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM execution_approvals WHERE id = ?",
                (clean_id,),
            ).fetchone()
        if row is None:
            raise ExecutionApprovalPersistenceError("failed to load resolved execution approval")
        return self._row_to_approval(row)  # type: ignore[return-value]

    async def cancel_pending_approval(
        self,
        *,
        approval_id: str,
        expected_revision: int,
    ) -> dict[str, object]:
        clean_id = self._require_nonblank(approval_id, "approval_id")
        if type(expected_revision) is not int:
            raise ExecutionApprovalPersistenceError("expected_revision must be an integer")
        timestamp = self._utcnow()

        def _body(conn: sqlite3.Connection) -> None:
            row = conn.execute(
                "SELECT * FROM execution_approvals WHERE id = ?",
                (clean_id,),
            ).fetchone()
            if row is None:
                raise ExecutionApprovalConflictError(f"execution approval {clean_id!r} does not exist")
            if row["revision"] != expected_revision:
                raise ExecutionApprovalConflictError(
                    f"execution approval {clean_id!r} revision mismatch: expected "
                    f"{expected_revision}, got {row['revision']}"
                )
            if row["status"] != "pending":
                raise ExecutionApprovalConflictError(
                    f"execution approval {clean_id!r} is not pending (status={row['status']!r})"
                )
            updated = conn.execute(
                """
                UPDATE execution_approvals
                SET status = 'canceled', updated_at = ?, resolved_at = ?, revision = revision + 1
                WHERE id = ? AND status = 'pending' AND revision = ?
                """,
                (timestamp, timestamp, clean_id, expected_revision),
            )
            if updated.rowcount != 1:
                raise ExecutionApprovalConflictError(
                    f"execution approval {clean_id!r} could not be canceled"
                )

        run_write_transaction(self.db_path, "cancel_pending_execution_approval", _body)

        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM execution_approvals WHERE id = ?",
                (clean_id,),
            ).fetchone()
        if row is None:
            raise ExecutionApprovalPersistenceError("failed to load canceled execution approval")
        return self._row_to_approval(row)  # type: ignore[return-value]

    async def cancel_pending_approvals_for_tasks(
        self,
        agent_task_ids: list[str],
    ) -> int:
        if not agent_task_ids:
            return 0
        timestamp = self._utcnow()
        placeholders = ",".join("?" * len(agent_task_ids))

        def _body(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                f"""
                UPDATE execution_approvals
                SET status = 'canceled', updated_at = ?, resolved_at = ?, revision = revision + 1
                WHERE status = 'pending' AND agent_task_id IN ({placeholders})
                """,
                (timestamp, timestamp, *agent_task_ids),
            )
            return cursor.rowcount

        return run_write_transaction(
            self.db_path,
            "cancel_pending_execution_approvals_for_tasks",
            _body,
        )
