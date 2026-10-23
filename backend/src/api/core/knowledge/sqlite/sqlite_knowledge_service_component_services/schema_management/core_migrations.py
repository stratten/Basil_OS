"""SQLite schema migrations grouped by durable domain."""

import json
import logging
import sqlite3
import uuid

from ...schema import get_schema_statements
from ..infrastructure.connection import generate_context_hash

logger = logging.getLogger(__name__)


def migrate_retrieval_tables(conn: sqlite3.Connection) -> None:
    """Create rebuildable retrieval-index metadata; vectors stay in a sidecar."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS retrieval_documents (
            document_id TEXT PRIMARY KEY,
            source_kind TEXT NOT NULL,
            source_id TEXT NOT NULL,
            content_digest TEXT NOT NULL,
            occurred_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            embedding_model TEXT NOT NULL,
            embedding_dimension INTEGER NOT NULL,
            vector_id INTEGER NOT NULL,
            generation_id TEXT NOT NULL,
            indexed_at TIMESTAMP NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(source_kind, source_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS retrieval_index_state (
            embedding_model TEXT PRIMARY KEY,
            embedding_dimension INTEGER NOT NULL,
            generation_id TEXT,
            document_count INTEGER NOT NULL DEFAULT 0,
            completed_at TIMESTAMP,
            last_error TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_retrieval_documents_source "
        "ON retrieval_documents(source_kind, occurred_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_retrieval_documents_digest "
        "ON retrieval_documents(content_digest)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_retrieval_documents_vector "
        "ON retrieval_documents(embedding_model, is_active, vector_id)"
    )


def migrate_activities_table(conn: sqlite3.Connection) -> None:
    cursor = conn.execute("PRAGMA table_info(activities)")
    columns = [row['name'] for row in cursor.fetchall()]
    logger.debug(f"Existing columns in activities table: {columns}")

    if 'context_hash' not in columns:
        logger.info("Adding context_hash column to activities table...")
        conn.execute("ALTER TABLE activities ADD COLUMN context_hash TEXT")
        cursor = conn.execute(
            "SELECT id, app_name, window_title, extracted_text FROM activities"
        )
        for row in cursor:
            ctx_hash = generate_context_hash(
                row['app_name'], row['window_title'], row['extracted_text']
            )
            conn.execute(
                "UPDATE activities SET context_hash = ? WHERE id = ?",
                (ctx_hash, row['id']),
            )
        logger.info("Updated existing activities with context hashes")

    if 'capture_frequency_minutes' not in columns:
        logger.info("Adding capture_frequency_minutes column to activities table...")
        conn.execute("ALTER TABLE activities ADD COLUMN capture_frequency_minutes REAL")
        logger.info("Added capture_frequency_minutes column")

    if 'observation_count' not in columns:
        logger.info("Adding observation_count column to activities table...")
        conn.execute("ALTER TABLE activities ADD COLUMN observation_count INTEGER DEFAULT 1")
        conn.execute("UPDATE activities SET observation_count = 1 WHERE observation_count IS NULL")
        logger.info("Added observation_count column")

    if 'last_observed_at' not in columns:
        logger.info("Adding last_observed_at column to activities table...")
        conn.execute("ALTER TABLE activities ADD COLUMN last_observed_at TEXT")
        conn.execute("UPDATE activities SET last_observed_at = timestamp WHERE last_observed_at IS NULL")
        logger.info("Added last_observed_at column")

    if 'content_fingerprint' not in columns:
        logger.info("Adding content_fingerprint column to activities table...")
        conn.execute("ALTER TABLE activities ADD COLUMN content_fingerprint TEXT")
        logger.info("Added content_fingerprint column")


def migrate_assistant_outputs_table(conn: sqlite3.Connection) -> None:
    # Step 1: handle the table-name rename. Older DBs have a
    # 'suggestions' table. The team identity rename moves it to
    # 'assistant_outputs'. This is idempotent: if the new name already
    # exists, we skip the rename. If only a legacy name exists, rename
    # in place. If neither exists, fall through to the create branch.
    suggestions_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='suggestions'"
    ).fetchone() is not None
    new_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='assistant_outputs'"
    ).fetchone() is not None

    if suggestions_exists and not new_exists:
        conn.execute("ALTER TABLE suggestions RENAME TO assistant_outputs")
        logger.info("Renamed legacy 'suggestions' table to 'assistant_outputs'")
        new_exists = True

    if not new_exists:
        for statement in get_schema_statements():
            if 'assistant_outputs' in statement.lower():
                conn.execute(statement)
        logger.info("Created assistant_outputs table and indexes")
        return

    # Step 2: column-name renames (suggestion_text -> output_text,
    # type -> output_type). SQLite supports RENAME COLUMN since 3.25;
    # use it directly and guard on column existence so this is
    # idempotent across reboots.
    col_info = conn.execute("PRAGMA table_info(assistant_outputs)").fetchall()
    cols_present = {row['name'] for row in col_info}

    if 'suggestion_text' in cols_present and 'output_text' not in cols_present:
        conn.execute(
            "ALTER TABLE assistant_outputs RENAME COLUMN suggestion_text TO output_text"
        )
        logger.info("Renamed assistant_outputs.suggestion_text -> output_text")

    if 'type' in cols_present and 'output_type' not in cols_present:
        conn.execute(
            "ALTER TABLE assistant_outputs RENAME COLUMN type TO output_type"
        )
        logger.info("Renamed assistant_outputs.type -> output_type")

    # Step 3: incremental column adds. Refresh column list after
    # renames so the guard below sees the new names.
    col_info = conn.execute("PRAGMA table_info(assistant_outputs)").fetchall()
    sg_columns = [row['name'] for row in col_info]
    assistant_output_column_migrations = {
        "output_type": "ALTER TABLE assistant_outputs ADD COLUMN output_type TEXT DEFAULT 'regular'",
        "screen_capture_path": "ALTER TABLE assistant_outputs ADD COLUMN screen_capture_path TEXT",
        "text_selection": "ALTER TABLE assistant_outputs ADD COLUMN text_selection TEXT",
        "app_name": "ALTER TABLE assistant_outputs ADD COLUMN app_name TEXT",
        "window_title": "ALTER TABLE assistant_outputs ADD COLUMN window_title TEXT",
        "status": "ALTER TABLE assistant_outputs ADD COLUMN status TEXT DEFAULT 'completed'",
        "refinement_count": "ALTER TABLE assistant_outputs ADD COLUMN refinement_count INTEGER DEFAULT 0",
        "refinements": "ALTER TABLE assistant_outputs ADD COLUMN refinements TEXT",
        "processing_time_ms": "ALTER TABLE assistant_outputs ADD COLUMN processing_time_ms INTEGER",
        "input_modality": "ALTER TABLE assistant_outputs ADD COLUMN input_modality TEXT",
        "context_type": "ALTER TABLE assistant_outputs ADD COLUMN context_type TEXT",
        "recipient": "ALTER TABLE assistant_outputs ADD COLUMN recipient TEXT",
    }
    for col_name, alter_sql in assistant_output_column_migrations.items():
        if col_name not in sg_columns:
            conn.execute(alter_sql)
            logger.info(f"Added {col_name} column to assistant_outputs table")

    # Step 4: legacy value migration. Pre-rename pipelines persisted
    # output_type='voice'. Flip any remaining legacy rows so the history
    # UI sees a single canonical assistant-session type. Idempotent.
    legacy_voice_count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM assistant_outputs WHERE output_type = 'voice'"
    ).fetchone()
    if legacy_voice_count and legacy_voice_count["cnt"]:
        conn.execute(
            "UPDATE assistant_outputs SET output_type = 'assistant_session' WHERE output_type = 'voice'"
        )
        logger.info(
            f"Assistant output migration: relabeled {legacy_voice_count['cnt']} legacy "
            f"assistant_outputs rows to 'assistant_session'"
        )

    # Step 5: activity_id nullability migration (preserved from the
    # original suggestions migration; uses the table-rebuild pattern).
    col_info = conn.execute("PRAGMA table_info(assistant_outputs)").fetchall()
    activity_col = next((c for c in col_info if c['name'] == 'activity_id'), None)
    if activity_col and activity_col['notnull']:
        logger.info("Migrating assistant_outputs table: making activity_id nullable")
        existing_cols = [c['name'] for c in col_info]
        cols_csv = ", ".join(existing_cols)
        conn.execute("ALTER TABLE assistant_outputs RENAME TO assistant_outputs_old")
        for stmt in get_schema_statements():
            if 'CREATE TABLE IF NOT EXISTS assistant_outputs' in stmt and 'assistant_outputs_old' not in stmt:
                conn.execute(stmt)
                break
        conn.execute(f"""
            INSERT INTO assistant_outputs ({cols_csv})
            SELECT {cols_csv} FROM assistant_outputs_old
        """)
        conn.execute("DROP TABLE assistant_outputs_old")
        conn.commit()
        logger.info("Migrated assistant_outputs table: activity_id is now nullable")



def migrate_transcriptions_table(conn: sqlite3.Connection) -> None:
    """Add lifecycle columns (0.9.0) to existing transcriptions tables.

    Existing rows get status='completed' via the column's DEFAULT so the
    history UI keeps treating pre-migration rows as successful runs.
    error_message stays NULL for those rows.
    """
    cursor = conn.execute("PRAGMA table_info(transcriptions)")
    tr_columns = [row['name'] for row in cursor.fetchall()]

    tr_migrations = {
        "status": "ALTER TABLE transcriptions ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'",
        "error_message": "ALTER TABLE transcriptions ADD COLUMN error_message TEXT",
        "last_transcribed_at": "ALTER TABLE transcriptions ADD COLUMN last_transcribed_at TIMESTAMP",
    }
    for col_name, alter_sql in tr_migrations.items():
        if col_name not in tr_columns:
            conn.execute(alter_sql)
            logger.info(f"Added {col_name} column to transcriptions table")

    if "last_transcribed_at" not in tr_columns:
        conn.execute(
            """
            UPDATE transcriptions
            SET last_transcribed_at = timestamp
            WHERE last_transcribed_at IS NULL
            """
        )
        conn.execute(
            """
            UPDATE transcriptions
            SET timestamp = created_at
            WHERE created_at IS NOT NULL
            """
        )
        logger.info(
            "Backfilled transcriptions.last_transcribed_at and restored "
            "transcriptions.timestamp from created_at where available"
        )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_transcriptions_timestamp
        ON transcriptions(timestamp)
        """
    )


def migrate_contact_identity_observations_table(conn: sqlite3.Connection) -> None:
    """Create the contact_identity_observations table on existing databases.

    Pure additive migration: there is no prior version of this table, so the
    only operation is "create if missing." Mirrors the create-only branch of
    ``migrate_mcp_call_log_table``. The table stores screen-derived candidate
    identity facts and is deliberately distinct from contact_relationships.
    """
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='contact_identity_observations'"
    )
    if cursor.fetchone():
        return

    logger.info("Creating contact_identity_observations table...")
    for statement in get_schema_statements():
        stmt = statement.lower()
        if (
            "create table if not exists contact_identity_observations" in stmt
            or "create index if not exists idx_contact_observations_" in stmt
        ):
            conn.execute(statement)
    logger.info("Created contact_identity_observations table and indexes")



