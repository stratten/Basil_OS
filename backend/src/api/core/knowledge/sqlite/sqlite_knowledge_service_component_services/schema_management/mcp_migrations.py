"""SQLite schema migrations grouped by durable domain."""

import json
import logging
import sqlite3
import uuid

from ...schema import get_schema_statements
from ..infrastructure.connection import generate_context_hash

logger = logging.getLogger(__name__)


def migrate_mcp_call_log_table(conn: sqlite3.Connection) -> None:
    """Create the mcp_call_log table and indexes on existing databases.

    Pure additive migration: there is no prior version of this table, so
    the only operation is "create if missing." Mirrors the create-only
    branch of ``_migrate_scheduled_agent_tasks_tables``.
    """
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='mcp_call_log'"
    )
    if cursor.fetchone():
        columns = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(mcp_call_log)").fetchall()
        ]
        if "minion_id" in columns and "agent_task_id" not in columns:
            conn.execute("ALTER TABLE mcp_call_log RENAME COLUMN minion_id TO agent_task_id")
            logger.info("Renamed mcp_call_log.minion_id -> agent_task_id")
        return

    logger.info("Creating mcp_call_log table for MCP connector audit trail...")
    for statement in get_schema_statements():
        stmt = statement.lower()
        if (
            "create table if not exists mcp_call_log" in stmt
            or "create index if not exists idx_mcp_call_log" in stmt
        ):
            conn.execute(statement)
    logger.info("Created mcp_call_log table and indexes")



