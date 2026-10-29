"""Incremental migrations for the source-safe agent work ledger."""

from __future__ import annotations

import json
import logging
import sqlite3

from .schema import get_agent_work_schema_statements


logger = logging.getLogger(__name__)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _execute_agent_work_schema(conn: sqlite3.Connection) -> None:
    for statement in get_agent_work_schema_statements():
        conn.execute(statement)


def _add_missing_columns(
    conn: sqlite3.Connection,
    table_name: str,
    column_definitions: dict[str, str],
) -> None:
    current_columns = _columns(conn, table_name)
    for name, definition in column_definitions.items():
        if name not in current_columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {definition}")


def _preserve_colliding_receipt_keys(
    conn: sqlite3.Connection,
    duplicate_session_id: str,
    retained_session_id: str,
) -> None:
    receipts = conn.execute(
        """
        SELECT id, receipt_key
        FROM agent_work_receipts
        WHERE session_id = ?
        ORDER BY created_at, id
        """,
        (duplicate_session_id,),
    ).fetchall()
    for receipt in receipts:
        receipt_key = receipt["receipt_key"]
        if receipt_key:
            collision = conn.execute(
                """
                SELECT 1 FROM agent_work_receipts
                WHERE session_id = ? AND receipt_key = ?
                """,
                (retained_session_id, receipt_key),
            ).fetchone()
            if collision:
                receipt_key = f"{receipt_key}::migrated::{receipt['id']}"
        conn.execute(
            """
            UPDATE agent_work_receipts
            SET session_id = ?, receipt_key = ?
            WHERE id = ?
            """,
            (retained_session_id, receipt_key, receipt["id"]),
        )


def _move_duplicate_root_session(
    conn: sqlite3.Connection,
    duplicate_session_id: str,
    retained_session_id: str,
) -> None:
    items = conn.execute(
        """
        SELECT id, external_id
        FROM agent_work_items
        WHERE session_id = ?
        ORDER BY created_at, id
        """,
        (duplicate_session_id,),
    ).fetchall()
    for item in items:
        collision = conn.execute(
            """
            SELECT 1
            FROM agent_work_items
            WHERE session_id = ? AND external_id IS ?
            """,
            (retained_session_id, item["external_id"]),
        ).fetchone()
        if collision:
            conn.execute(
                """
                UPDATE agent_work_items
                SET entity_type = 'legacy',
                    source_system = 'legacy_migration',
                    source_scope_json = ?,
                    identity_quality = 'legacy_unscoped'
                WHERE id = ?
                """,
                (
                    json.dumps(
                        {"original_session_id": duplicate_session_id},
                        sort_keys=True,
                    ),
                    item["id"],
                ),
            )
        conn.execute(
            "UPDATE agent_work_items SET session_id = ? WHERE id = ?",
            (retained_session_id, item["id"]),
        )
    _preserve_colliding_receipt_keys(conn, duplicate_session_id, retained_session_id)
    conn.execute(
        "DELETE FROM agent_work_sessions WHERE id = ?",
        (duplicate_session_id,),
    )


def _reconcile_duplicate_root_sessions(conn: sqlite3.Connection) -> None:
    duplicate_roots = conn.execute(
        """
        SELECT root_task_id
        FROM agent_work_sessions
        WHERE root_task_id IS NOT NULL AND root_task_id != ''
        GROUP BY root_task_id
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for duplicate_root in duplicate_roots:
        sessions = conn.execute(
            """
            SELECT id
            FROM agent_work_sessions
            WHERE root_task_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (duplicate_root["root_task_id"],),
        ).fetchall()
        retained_session_id = sessions[0]["id"]
        for session in sessions[1:]:
            _move_duplicate_root_session(
                conn,
                duplicate_session_id=session["id"],
                retained_session_id=retained_session_id,
            )


def _backfill_legacy_items(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE agent_work_items
        SET identity_quality = 'legacy_unscoped'
        WHERE identity_quality IS NULL OR identity_quality = ''
        """
    )


def migrate_agent_work_session_tables(conn: sqlite3.Connection) -> None:
    """Upgrade or create ledger tables without discarding historic records."""
    if not _table_exists(conn, "agent_work_sessions"):
        _execute_agent_work_schema(conn)
        return

    _add_missing_columns(
        conn,
        "agent_work_sessions",
        {
            "root_task_id": "root_task_id TEXT",
            "scope_json": "scope_json TEXT NOT NULL DEFAULT '{}'",
        },
    )
    conn.execute(
        """
        UPDATE agent_work_sessions
        SET root_task_id = COALESCE(
            (
                SELECT NULLIF(root_task_id, '')
                FROM agent_tasks
                WHERE agent_tasks.id = agent_work_sessions.agent_task_id
            ),
            agent_task_id
        )
        WHERE root_task_id IS NULL OR root_task_id = ''
        """
    )
    _add_missing_columns(
        conn,
        "agent_work_items",
        {
            "entity_type": "entity_type TEXT",
            "source_system": "source_system TEXT",
            "source_scope_json": "source_scope_json TEXT",
            "identity_quality": (
                "identity_quality TEXT NOT NULL DEFAULT 'legacy_unscoped'"
            ),
        },
    )
    if _table_exists(conn, "agent_work_receipts"):
        _add_missing_columns(
            conn,
            "agent_work_receipts",
            {
                "observed_postcondition_json": (
                    "observed_postcondition_json TEXT NOT NULL DEFAULT '{}'"
                ),
                "material_write": "material_write INTEGER NOT NULL DEFAULT 0",
            },
        )
    _backfill_legacy_items(conn)
    conn.execute("DROP INDEX IF EXISTS idx_agent_work_sessions_root")
    conn.execute("DROP INDEX IF EXISTS idx_agent_work_items_external")
    _reconcile_duplicate_root_sessions(conn)
    _execute_agent_work_schema(conn)
    logger.info("Migrated durable agent work ledger to source-safe identity schema")
