"""Idempotent migration for provider-target discovery and delegation records."""

from __future__ import annotations

import json
import sqlite3

from .discovery_schema import get_provider_discovery_schema_statements


def _delegation_table_sql(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'provider_target_delegations'
        """
    ).fetchone()
    return str(row["sql"] or "") if row is not None else ""


def _create_delegation_table(conn: sqlite3.Connection) -> None:
    statements = get_provider_discovery_schema_statements()
    start = next(
        index
        for index, statement in enumerate(statements)
        if "CREATE TABLE IF NOT EXISTS provider_target_delegations" in statement
    )
    for statement in statements[start:]:
        conn.execute(statement)


def _rebuild_provider_relation_table(conn: sqlite3.Connection) -> None:
    conn.execute("SAVEPOINT provider_target_delegation_authority_migration")
    try:
        conn.execute("ALTER TABLE provider_target_delegations RENAME TO provider_target_delegations_legacy")
        _create_delegation_table(conn)
        legacy_rows = conn.execute("SELECT * FROM provider_target_delegations_legacy").fetchall()
        for row in legacy_rows:
            data = dict(row)
            snapshot = {
                field: data.get(field)
                for field in (
                    "status", "failure_reason", "child_terminal_status", "child_result_json",
                    "child_terminal_at", "continuation_started_at", "continuation_finished_at",
                    "continuation_failure_reason", "submitted_at",
                )
                if field in data
            }
            conn.execute(
                """
                INSERT INTO provider_target_delegations (
                    id, authorization_id, parent_agent_task_id, root_task_id,
                    child_agent_task_id, delegated_agent_run_id, provider_profile_id,
                    workspace_grant_id, selected_connection_id, selected_tool_name,
                    selected_service_policy, legacy_lifecycle_snapshot_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["id"], data["authorization_id"], data["parent_agent_task_id"],
                    data["root_task_id"], data["child_agent_task_id"],
                    data.get("delegated_agent_run_id"), data["provider_profile_id"],
                    data["workspace_grant_id"], data.get("selected_connection_id"),
                    data.get("selected_tool_name"), data.get("selected_service_policy"),
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    data["created_at"], data.get("updated_at") or data["created_at"],
                ),
            )
        if conn.execute("SELECT COUNT(*) FROM provider_target_delegations").fetchone()[0] != len(legacy_rows):
            raise RuntimeError("provider-target relation migration did not preserve every row")
        conn.execute("DROP TABLE provider_target_delegations_legacy")
        conn.execute("RELEASE SAVEPOINT provider_target_delegation_authority_migration")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT provider_target_delegation_authority_migration")
        conn.execute("RELEASE SAVEPOINT provider_target_delegation_authority_migration")
        raise


def migrate_provider_target_delegation_table(conn: sqlite3.Connection) -> None:
    sql = _delegation_table_sql(conn)
    if not sql:
        _create_delegation_table(conn)
        return
    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(provider_target_delegations)")
    }
    if "legacy_lifecycle_snapshot_json" not in columns:
        _rebuild_provider_relation_table(conn)
        return
    _create_delegation_table(conn)


def migrate_provider_discovery_tables(conn: sqlite3.Connection) -> None:
    for statement in get_provider_discovery_schema_statements():
        if "CREATE TABLE IF NOT EXISTS provider_target_delegations" in statement:
            break
        conn.execute(statement)
    migrate_provider_target_delegation_table(conn)
