"""Create the durable agent follow-up table for existing and fresh databases."""

from __future__ import annotations

import sqlite3

AGENT_TASK_FOLLOW_UP_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS agent_task_follow_ups (
        id TEXT PRIMARY KEY,
        root_task_id TEXT NOT NULL,
        source_agent_task_id TEXT NOT NULL,
        instructions TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        due_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'scheduled'
            CHECK (status IN ('scheduled', 'dispatching', 'submitted', 'failed', 'missed', 'canceled')),
        defer_count INTEGER NOT NULL DEFAULT 0,
        follow_up_agent_task_id TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_agent_task_follow_ups_status_due ON agent_task_follow_ups(status, due_at)",
    "CREATE INDEX IF NOT EXISTS idx_agent_task_follow_ups_root_status ON agent_task_follow_ups(root_task_id, status)",
)


def migrate_agent_follow_up_tables(conn: sqlite3.Connection) -> None:
    """Create the follow-up table and indexes; idempotent on every startup."""
    for statement in AGENT_TASK_FOLLOW_UP_STATEMENTS:
        conn.execute(statement)
