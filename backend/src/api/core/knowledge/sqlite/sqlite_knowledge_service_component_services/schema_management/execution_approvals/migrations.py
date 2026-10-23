"""Idempotent migration for durable generic execution approval tables."""

from __future__ import annotations

import sqlite3

from .schema import get_execution_approval_schema_statements


def migrate_execution_approval_tables(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'execution_approvals'"
    ).fetchone()
    if row is not None and "browser_foreground_control" not in (row[0] or ""):
        conn.execute("DROP INDEX IF EXISTS idx_execution_approvals_task_status")
        conn.execute("ALTER TABLE execution_approvals RENAME TO execution_approvals_legacy")
        for statement in get_execution_approval_schema_statements():
            conn.execute(statement)
        conn.execute(
            """
            INSERT INTO execution_approvals (
                id, agent_task_id, root_task_id, execution_type, command, script_content,
                reason, risk_level, generalized_pattern, render_context_json, status,
                remember_choice, pattern_type, revision, created_at, updated_at, resolved_at
            )
            SELECT
                id, agent_task_id, root_task_id, execution_type, command, script_content,
                reason, risk_level, generalized_pattern, render_context_json, status,
                remember_choice, pattern_type, revision, created_at, updated_at, resolved_at
            FROM execution_approvals_legacy
            """
        )
        conn.execute("DROP TABLE execution_approvals_legacy")
        return

    for statement in get_execution_approval_schema_statements():
        conn.execute(statement)
