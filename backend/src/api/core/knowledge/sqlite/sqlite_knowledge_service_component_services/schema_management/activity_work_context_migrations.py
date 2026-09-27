"""SQLite schema migrations grouped by durable domain."""

import json
import logging
import sqlite3
import uuid

from ...schema import get_schema_statements
from ..infrastructure.connection import generate_context_hash

logger = logging.getLogger(__name__)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _column_names(conn: sqlite3.Connection, table: str) -> set:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def migrate_activity_work_contexts(conn: sqlite3.Connection) -> int:
    """Backfill deterministic work-context metadata and reset screen-block projections.

    Idempotent: a second run finds no rows whose work_context_version is missing
    or not equal to WORK_CONTEXT_VERSION, returns 0, and does not touch zettels.
    """
    from api.services.capture.shared.work_context import WORK_CONTEXT_VERSION, derive_work_context

    if not _table_exists(conn, "activities"):
        return 0

    rows = conn.execute(
        """
        SELECT a.id, a.app_name, a.window_title
        FROM activities a
        LEFT JOIN activity_metadata v
            ON v.activity_id = a.id AND v.key = 'work_context_version'
        WHERE v.value IS NULL OR v.value != ?
        """,
        (WORK_CONTEXT_VERSION,),
    ).fetchall()

    changed = len(rows)
    for row in rows:
        context = derive_work_context(
            row["app_name"] or "",
            row["window_title"],
            capture_id=str(row["id"]),
        )
        for key, value in context.as_metadata().items():
            conn.execute(
                """
                INSERT INTO activity_metadata (activity_id, key, value, confidence)
                VALUES (?, ?, ?, 1.0)
                ON CONFLICT(activity_id, key) DO UPDATE SET
                    value = excluded.value,
                    confidence = excluded.confidence
                """,
                (row["id"], key, value),
            )

    if changed > 0 and _table_exists(conn, "zettel_entries"):
        logger.info(
            "Resetting %s screen_block projections after work-context backfill",
            changed,
        )
        conn.execute("DELETE FROM zettel_entries WHERE source_kind = 'screen_block'")
        conn.execute(
            "UPDATE activities SET zettel_id = NULL WHERE zettel_id LIKE 'screen_block:%'"
        )

    return changed



