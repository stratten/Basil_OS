"""SQLite schema migrations grouped by durable domain."""

import json
import logging
import sqlite3
import uuid

from ...schema import get_schema_statements
from ..infrastructure.connection import generate_context_hash

logger = logging.getLogger(__name__)


def migrate_zettel_tables(conn: sqlite3.Connection) -> None:
    """Create the zettel_entries table and indexes on existing databases.

    Pure additive migration mirroring ``migrate_contact_identity_observations_table``.
    Required because ``db_connection._ensure_tables`` only bootstraps the full
    schema when one of REQUIRED_TABLES is missing, which never happens on an
    existing database - so a newly added table would otherwise never be created.
    """
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='zettel_entries'"
    )
    if cursor.fetchone():
        return

    logger.info("Creating zettel unified event stream tables...")
    for statement in get_schema_statements():
        stmt = statement.lower()
        if (
            "create table if not exists zettel_entries" in stmt
            or "create index if not exists idx_zettel_" in stmt
        ):
            conn.execute(statement)
    logger.info("Created zettel_entries and indexes")


# (table, id_column, source_kind) for every table that feeds the stream.
_ZETTEL_SOURCE_TABLES = (
    ("agent_tasks", "id", "agent_task"),
    ("transcriptions", "id", "transcription"),
    ("assistant_outputs", "id", "assistant_output"),
    ("scheduled_agent_task_runs", "id", "scheduled_run"),
    ("activities", "id", "screen_block"),
)

# Columns added to zettel_entries on databases created before them.
# Each carries a default so ALTER TABLE ADD COLUMN accepts the NOT NULL ones.
_ZETTEL_NARRATIVE_COLUMNS = (
    ("narrative", "narrative TEXT"),
    ("narrative_state", "narrative_state TEXT NOT NULL DEFAULT 'pending'"),
    ("narrative_model", "narrative_model TEXT"),
    ("narrative_at", "narrative_at TIMESTAMP"),
    ("narrative_error", "narrative_error TEXT"),
    ("narrative_attempts", "narrative_attempts INTEGER NOT NULL DEFAULT 0"),
    ("is_open", "is_open INTEGER"),
    ("open_note", "open_note TEXT"),
    # NULL means "the memory evaluator has not consumed this entry yet", which
    # is what replaces the memory_signals watermark. Backfilling to NULL is
    # correct: the watermark file was never written, so nothing was consumed.
    ("memory_swept_at", "memory_swept_at TIMESTAMP"),
)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _column_names(conn: sqlite3.Connection, table: str) -> set:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}



def migrate_zettel_backreference(conn: sqlite3.Connection) -> None:
    """Add zettel_id back-references to source tables and narrative columns.

    Idempotent and safe to run on both fresh and existing databases. Replaces
    the removed watermark table: presence of zettel_id is now the "already
    seen" signal, so the moving-cursor machinery is dropped entirely.

    First run is detected by the absence of activities.zettel_id. Only then are
    the pre-existing screen_block projections deleted so they re-card cleanly -
    a coalesced block spans many activity rows whose per-row stamps cannot be
    reconstructed from the block entry alone, so a 1:1 backfill is impossible
    for that source and a clean rebuild is the correct, one-time repair.
    """
    first_run = _table_exists(conn, "activities") and (
        "zettel_id" not in _column_names(conn, "activities")
    )

    for table, _id_column, _kind in _ZETTEL_SOURCE_TABLES:
        if not _table_exists(conn, table):
            continue
        if "zettel_id" not in _column_names(conn, table):
            logger.info("Adding zettel_id back-reference to %s", table)
            conn.execute(f"ALTER TABLE {table} ADD COLUMN zettel_id TEXT")
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_zettel_id ON {table}(zettel_id)"
        )

    if _table_exists(conn, "zettel_entries"):
        existing = _column_names(conn, "zettel_entries")
        for name, ddl in _ZETTEL_NARRATIVE_COLUMNS:
            if name not in existing:
                logger.info("Adding %s to zettel_entries", name)
                conn.execute(f"ALTER TABLE zettel_entries ADD COLUMN {ddl}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_zettel_entries_state "
            "ON zettel_entries(narrative_state, occurred_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_zettel_entries_sweep "
            "ON zettel_entries(narrative_state, memory_swept_at, narrative_at)"
        )

    if first_run and _table_exists(conn, "zettel_entries"):
        logger.info("Rebuilding screen_block projections under the new contract")
        conn.execute("DELETE FROM zettel_entries WHERE source_kind = 'screen_block'")
        for table, id_column, kind in _ZETTEL_SOURCE_TABLES:
            if kind == "screen_block" or not _table_exists(conn, table):
                continue
            conn.execute(
                f"UPDATE {table} SET zettel_id = ? || ':' || CAST({id_column} AS TEXT) "
                f"WHERE zettel_id IS NULL AND EXISTS ("
                f"  SELECT 1 FROM zettel_entries z "
                f"  WHERE z.source_kind = ? AND z.source_id = CAST({table}.{id_column} AS TEXT)"
                f")",
                (kind, kind),
            )

    conn.execute("DROP TABLE IF EXISTS zettel_source_watermarks")


def migrate_conversation_memory_projection(conn: sqlite3.Connection) -> None:
    """Finalize legacy thread cards without synthesizing historical pair entries."""
    if not _table_exists(conn, "zettel_entries"):
        return
    conn.execute(
        """
        UPDATE zettel_entries
        SET narrative_state = 'final',
            is_open = 0,
            open_note = NULL,
            memory_swept_at = NULL
        WHERE source_kind = 'conversation'
          AND (
              narrative_state != 'final'
              OR COALESCE(is_open, -1) != 0
              OR open_note IS NOT NULL
          )
        """
    )

