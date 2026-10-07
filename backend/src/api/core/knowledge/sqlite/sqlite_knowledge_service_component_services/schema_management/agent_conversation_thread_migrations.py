"""Create the per-task agent conversation thread table on fresh and existing databases."""

from __future__ import annotations

import sqlite3

AGENT_CONVERSATION_THREAD_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS agent_conversation_threads (
        agent_task_id TEXT PRIMARY KEY,
        root_task_id TEXT NOT NULL,
        model_family TEXT NOT NULL,
        model_id TEXT NOT NULL DEFAULT '',
        format_version INTEGER NOT NULL DEFAULT 1,
        message_count INTEGER NOT NULL DEFAULT 0,
        messages_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_agent_conversation_threads_root ON agent_conversation_threads(root_task_id)",
)


def migrate_agent_conversation_thread_tables(conn: sqlite3.Connection) -> None:
    """Idempotent; runs on every startup inside the schema transaction."""
    for statement in AGENT_CONVERSATION_THREAD_STATEMENTS:
        conn.execute(statement)
