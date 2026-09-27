"""SQLite schema migrations grouped by durable domain."""

import json
import logging
import sqlite3
import uuid

from ...schema import get_schema_statements
from ..infrastructure.connection import generate_context_hash

logger = logging.getLogger(__name__)


def migrate_scheduled_agent_tasks_tables(conn: sqlite3.Connection) -> None:
    """Ensure scheduled agent task tables and indexes exist in existing databases."""
    legacy_tables = ("scheduled_instruction_runs", "scheduled_instructions")
    for legacy_table in legacy_tables:
        legacy_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (legacy_table,)
        ).fetchone()
        if legacy_exists:
            logger.info("Dropping legacy %s table during scheduled agent task rename", legacy_table)
            conn.execute(f"DROP TABLE IF EXISTS {legacy_table}")

    cursor = conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='scheduled_agent_tasks'
    """)
    if not cursor.fetchone():
        logger.info("Creating scheduled agent task tables...")
        for statement in get_schema_statements():
            stmt = statement.lower()
            if (
                "create table if not exists scheduled_agent_tasks" in stmt
                or "create table if not exists scheduled_agent_task_runs" in stmt
                or "create index if not exists idx_scheduled_" in stmt
            ):
                conn.execute(statement)
        logger.info("Created scheduled agent task tables and indexes")
        return

    # Ensure newly added columns exist for partial migrations.
    cursor = conn.execute("PRAGMA table_info(scheduled_agent_tasks)")
    sc_columns = [row['name'] for row in cursor.fetchall()]
    sc_migrations = {
        "source_type": "ALTER TABLE scheduled_agent_tasks ADD COLUMN source_type TEXT DEFAULT 'manual'",
        "next_run_at": "ALTER TABLE scheduled_agent_tasks ADD COLUMN next_run_at TIMESTAMP",
        "last_run_at": "ALTER TABLE scheduled_agent_tasks ADD COLUMN last_run_at TIMESTAMP",
        "last_status": "ALTER TABLE scheduled_agent_tasks ADD COLUMN last_status TEXT",
        "reference_paths": "ALTER TABLE scheduled_agent_tasks ADD COLUMN reference_paths TEXT NOT NULL DEFAULT '[]'",
    }
    for col_name, alter_sql in sc_migrations.items():
        if col_name not in sc_columns:
            conn.execute(alter_sql)
            logger.info(f"Added {col_name} column to scheduled_agent_tasks table")

    # Ensure scheduled_agent_task_runs exists and has expected columns/indexes.
    cursor = conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='scheduled_agent_task_runs'
    """)
    if not cursor.fetchone():
        logger.info("Creating scheduled_agent_task_runs table...")
        for statement in get_schema_statements():
            stmt = statement.lower()
            if (
                "create table if not exists scheduled_agent_task_runs" in stmt
                or "create index if not exists idx_scheduled_agent_task_runs_" in stmt
            ):
                conn.execute(statement)
        logger.info("Created scheduled_agent_task_runs table and indexes")
        return

    cursor = conn.execute("PRAGMA table_info(scheduled_agent_task_runs)")
    run_columns = [row['name'] for row in cursor.fetchall()]
    if "minion_id" in run_columns and "agent_task_id" not in run_columns:
        conn.execute("ALTER TABLE scheduled_agent_task_runs RENAME COLUMN minion_id TO agent_task_id")
        logger.info("Renamed scheduled_agent_task_runs.minion_id -> agent_task_id")
        run_columns = ["agent_task_id" if name == "minion_id" else name for name in run_columns]
    run_migrations = {
        "agent_task_id": "ALTER TABLE scheduled_agent_task_runs ADD COLUMN agent_task_id TEXT",
        "error_message": "ALTER TABLE scheduled_agent_task_runs ADD COLUMN error_message TEXT",
        "created_at": "ALTER TABLE scheduled_agent_task_runs ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    }
    for col_name, alter_sql in run_migrations.items():
        if col_name not in run_columns:
            conn.execute(alter_sql)
            logger.info(f"Added {col_name} column to scheduled_agent_task_runs table")

    for statement in get_schema_statements():
        stmt = statement.lower()
        if "create index if not exists idx_scheduled_" in stmt:
            conn.execute(statement)



