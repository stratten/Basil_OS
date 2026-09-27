"""Durable managed file-change history: changes, heads, and blob references."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from typing import Any, Optional

from ..infrastructure.connection import get_sync_connection, run_write_transaction


class ManagedFileHistoryPersistenceError(RuntimeError):
    """Base error for managed file-history persistence failures."""


class ManagedFileHistoryConflictError(ManagedFileHistoryPersistenceError):
    """Raised when a change or blob transition cannot be applied as requested."""


TERMINAL_CHANGE_STATES = {"applied", "failed", "conflicted", "reverted"}


class ManagedFileHistoryRepository:
    """Persist durable managed file-change history rows."""

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
            raise ManagedFileHistoryPersistenceError(f"{field_name} must be a nonblank string")
        return value.strip()

    @classmethod
    def _row_to_change(cls, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": row["id"],
            "root_task_id": row["root_task_id"],
            "agent_task_id": row["agent_task_id"],
            "canonical_path": row["canonical_path"],
            "operation": row["operation"],
            "origin": row["origin"],
            "pre_image_sha256": row["pre_image_sha256"],
            "pre_image_size_bytes": row["pre_image_size_bytes"],
            "post_image_sha256": row["post_image_sha256"],
            "post_image_size_bytes": row["post_image_size_bytes"],
            "expected_precondition_sha256": row["expected_precondition_sha256"],
            "restores_change_id": row["restores_change_id"],
            "state": row["state"],
            "error_message": row["error_message"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "applied_at": row["applied_at"],
        }

    @classmethod
    def _row_to_head(cls, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "canonical_path": row["canonical_path"],
            "current_change_id": row["current_change_id"],
            "current_sha256": row["current_sha256"],
            "updated_at": row["updated_at"],
        }

    def prepare_change(
        self,
        *,
        root_task_id: str,
        agent_task_id: str,
        canonical_path: str,
        operation: str,
        origin: str,
        pre_image_sha256: Optional[str],
        pre_image_size_bytes: Optional[int],
        expected_precondition_sha256: Optional[str],
        restores_change_id: Optional[str] = None,
    ) -> dict[str, Any]:
        change_id = str(uuid.uuid4())
        timestamp = self._utcnow()

        def _body(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO managed_file_changes (
                    id, root_task_id, agent_task_id, canonical_path, operation, origin,
                    pre_image_sha256, pre_image_size_bytes, post_image_sha256, post_image_size_bytes,
                    expected_precondition_sha256, restores_change_id, state,
                    error_message, created_at, updated_at, applied_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, 'prepared', NULL, ?, ?, NULL)
                """,
                (
                    change_id,
                    self._require_nonblank(root_task_id, "root_task_id"),
                    self._require_nonblank(agent_task_id, "agent_task_id"),
                    self._require_nonblank(canonical_path, "canonical_path"),
                    operation,
                    origin,
                    pre_image_sha256,
                    pre_image_size_bytes,
                    expected_precondition_sha256,
                    restores_change_id,
                    timestamp,
                    timestamp,
                ),
            )

        run_write_transaction(self.db_path, "prepare_managed_file_change", _body)
        change = self.get_change(change_id)
        if change is None:
            raise ManagedFileHistoryPersistenceError("failed to load prepared managed file change")
        return change

    def mark_applied(
        self,
        change_id: str,
        *,
        post_image_sha256: str,
        post_image_size_bytes: int,
    ) -> dict[str, Any]:
        clean_id = self._require_nonblank(change_id, "change_id")
        timestamp = self._utcnow()

        def _body(conn: sqlite3.Connection) -> None:
            updated = conn.execute(
                """
                UPDATE managed_file_changes
                SET state = 'applied', post_image_sha256 = ?, post_image_size_bytes = ?,
                    updated_at = ?, applied_at = ?
                WHERE id = ? AND state = 'prepared'
                """,
                (post_image_sha256, post_image_size_bytes, timestamp, timestamp, clean_id),
            )
            if updated.rowcount != 1:
                raise ManagedFileHistoryConflictError(
                    f"managed file change {clean_id!r} could not transition to applied"
                )

        run_write_transaction(self.db_path, "mark_managed_file_change_applied", _body)
        change = self.get_change(clean_id)
        if change is None:
            raise ManagedFileHistoryPersistenceError("failed to load applied managed file change")
        return change

    def mark_applied_and_upsert_head(
        self,
        *,
        change_id: str,
        canonical_path: str,
        post_image_sha256: str,
        post_image_size_bytes: int,
        displaced_change_id: str | None = None,
    ) -> dict[str, Any]:
        """Finalize a change and advance its durable head atomically."""
        clean_id = self._require_nonblank(change_id, "change_id")
        clean_path = self._require_nonblank(canonical_path, "canonical_path")
        timestamp = self._utcnow()

        def _body(conn: sqlite3.Connection) -> None:
            updated = conn.execute(
                """
                UPDATE managed_file_changes
                SET state = 'applied', post_image_sha256 = ?, post_image_size_bytes = ?,
                    updated_at = ?, applied_at = ?
                WHERE id = ? AND state = 'prepared'
                """,
                (post_image_sha256, post_image_size_bytes, timestamp, timestamp, clean_id),
            )
            if updated.rowcount != 1:
                raise ManagedFileHistoryConflictError(
                    f"managed file change {clean_id!r} could not transition to applied"
                )
            if displaced_change_id is not None:
                conn.execute(
                    """
                    UPDATE managed_file_changes
                    SET state = 'reverted', updated_at = ?
                    WHERE id = ? AND state = 'applied'
                    """,
                    (timestamp, self._require_nonblank(displaced_change_id, "displaced_change_id")),
                )
            conn.execute(
                """
                INSERT INTO managed_file_heads (canonical_path, current_change_id, current_sha256, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(canonical_path) DO UPDATE SET
                    current_change_id = excluded.current_change_id,
                    current_sha256 = excluded.current_sha256,
                    updated_at = excluded.updated_at
                """,
                (clean_path, clean_id, post_image_sha256, timestamp),
            )

        run_write_transaction(self.db_path, "finalize_managed_file_change", _body)
        change = self.get_change(clean_id)
        if change is None:
            raise ManagedFileHistoryPersistenceError("failed to load finalized managed file change")
        return change

    def mark_failed(self, change_id: str, error_message: str) -> dict[str, Any]:
        return self._transition_terminal(change_id, "failed", error_message)

    def mark_conflicted(self, change_id: str, error_message: str) -> dict[str, Any]:
        return self._transition_terminal(change_id, "conflicted", error_message)

    def mark_reverted(self, change_id: str) -> None:
        clean_id = self._require_nonblank(change_id, "change_id")
        timestamp = self._utcnow()

        def _body(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                UPDATE managed_file_changes
                SET state = 'reverted', updated_at = ?
                WHERE id = ? AND state = 'applied'
                """,
                (timestamp, clean_id),
            )

        run_write_transaction(self.db_path, "mark_managed_file_change_reverted", _body)

    def _transition_terminal(self, change_id: str, next_state: str, error_message: str) -> dict[str, Any]:
        clean_id = self._require_nonblank(change_id, "change_id")
        timestamp = self._utcnow()

        def _body(conn: sqlite3.Connection) -> None:
            updated = conn.execute(
                f"""
                UPDATE managed_file_changes
                SET state = '{next_state}', error_message = ?, updated_at = ?
                WHERE id = ? AND state = 'prepared'
                """,
                (error_message, timestamp, clean_id),
            )
            if updated.rowcount != 1:
                raise ManagedFileHistoryConflictError(
                    f"managed file change {clean_id!r} could not transition to {next_state!r}"
                )

        run_write_transaction(self.db_path, f"mark_managed_file_change_{next_state}", _body)
        change = self.get_change(clean_id)
        if change is None:
            raise ManagedFileHistoryPersistenceError("failed to load transitioned managed file change")
        return change

    def get_change(self, change_id: str) -> dict[str, Any] | None:
        clean_id = self._require_nonblank(change_id, "change_id")
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM managed_file_changes WHERE id = ?",
                (clean_id,),
            ).fetchone()
        return self._row_to_change(row)

    def get_head(self, canonical_path: str) -> dict[str, Any] | None:
        clean_path = self._require_nonblank(canonical_path, "canonical_path")
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM managed_file_heads WHERE canonical_path = ?",
                (clean_path,),
            ).fetchone()
        return self._row_to_head(row)

    def upsert_head(self, canonical_path: str, change_id: str, sha256_digest: str) -> None:
        clean_path = self._require_nonblank(canonical_path, "canonical_path")
        clean_id = self._require_nonblank(change_id, "change_id")
        timestamp = self._utcnow()

        def _body(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO managed_file_heads (canonical_path, current_change_id, current_sha256, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(canonical_path) DO UPDATE SET
                    current_change_id = excluded.current_change_id,
                    current_sha256 = excluded.current_sha256,
                    updated_at = excluded.updated_at
                """,
                (clean_path, clean_id, sha256_digest, timestamp),
            )

        run_write_transaction(self.db_path, "upsert_managed_file_head", _body)

    def list_retained_versions(self, canonical_path: str, *, limit: int = 10_000) -> list[dict[str, Any]]:
        clean_path = self._require_nonblank(canonical_path, "canonical_path")
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM managed_file_changes
                WHERE canonical_path = ? AND state IN ('applied', 'reverted')
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (clean_path, limit),
            ).fetchall()
        return [change for change in (self._row_to_change(row) for row in rows) if change is not None]

    def sum_task_bytes(self, agent_task_id: str) -> int:
        clean_id = self._require_nonblank(agent_task_id, "agent_task_id")
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(
                    SUM(
                        COALESCE(pre_image_size_bytes, 0)
                        + COALESCE(post_image_size_bytes, 0)
                    ),
                    0
                ) AS total
                FROM managed_file_changes
                WHERE agent_task_id = ? AND state IN ('prepared', 'applied', 'reverted')
                """,
                (clean_id,),
            ).fetchone()
        return int(row["total"] or 0)

    def sum_total_store_bytes(self) -> int:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(byte_size), 0) AS total FROM managed_file_blobs WHERE ref_count > 0"
            ).fetchone()
        return int(row["total"] or 0)

    def upsert_blob_ref(self, sha256_digest: str, byte_size: int) -> None:
        clean_digest = self._require_nonblank(sha256_digest, "sha256_digest")
        timestamp = self._utcnow()

        def _body(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO managed_file_blobs (sha256, byte_size, ref_count, created_at, pending_deletion, marked_for_deletion_at)
                VALUES (?, ?, 1, ?, 0, NULL)
                ON CONFLICT(sha256) DO UPDATE SET
                    ref_count = ref_count + 1,
                    pending_deletion = 0,
                    marked_for_deletion_at = NULL
                """,
                (clean_digest, byte_size, timestamp),
            )

        run_write_transaction(self.db_path, "upsert_managed_file_blob_ref", _body)

    def decrement_blob_ref(self, sha256_digest: str) -> None:
        clean_digest = self._require_nonblank(sha256_digest, "sha256_digest")
        timestamp = self._utcnow()

        def _body(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE managed_file_blobs SET ref_count = MAX(ref_count - 1, 0) WHERE sha256 = ?",
                (clean_digest,),
            )
            conn.execute(
                """
                UPDATE managed_file_blobs
                SET pending_deletion = 1, marked_for_deletion_at = ?
                WHERE sha256 = ? AND ref_count = 0 AND pending_deletion = 0
                """,
                (timestamp, clean_digest),
            )

        run_write_transaction(self.db_path, "decrement_managed_file_blob_ref", _body)

    def delete_change_row(self, change_id: str) -> None:
        clean_id = self._require_nonblank(change_id, "change_id")

        def _body(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM managed_file_changes WHERE id = ?", (clean_id,))

        run_write_transaction(self.db_path, "delete_managed_file_change_row", _body)

    def list_blobs_pending_purge(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT sha256, byte_size FROM managed_file_blobs
                WHERE pending_deletion = 1 AND ref_count = 0
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [{"sha256": row["sha256"], "byte_size": row["byte_size"]} for row in rows]

    def purge_blob_row(self, sha256_digest: str) -> None:
        clean_digest = self._require_nonblank(sha256_digest, "sha256_digest")

        def _body(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM managed_file_blobs WHERE sha256 = ? AND pending_deletion = 1 AND ref_count = 0",
                (clean_digest,),
            )

        run_write_transaction(self.db_path, "purge_managed_file_blob_row", _body)
