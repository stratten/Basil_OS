"""Idempotent migration for attended generic ACP provider tables."""

from __future__ import annotations

import sqlite3

from .run_schema import get_provider_run_schema_statements


def migrate_provider_run_tables(conn: sqlite3.Connection) -> None:
    for statement in get_provider_run_schema_statements():
        conn.execute(statement)

    _add_missing_columns(
        conn,
        "provider_profiles",
        (
            ("description", "TEXT"),
            ("routing_hints_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("revision", "INTEGER NOT NULL DEFAULT 0"),
            ("authentication_method_id", "TEXT"),
        ),
    )
    _add_missing_columns(
        conn,
        "provider_workspace_grants",
        (
            ("workspace_label", "TEXT NOT NULL DEFAULT ''"),
            ("description", "TEXT"),
            ("routing_hints_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("revision", "INTEGER NOT NULL DEFAULT 0"),
        ),
    )


def _add_missing_columns(
    conn: sqlite3.Connection,
    table_name: str,
    columns: tuple[tuple[str, str], ...],
) -> None:
    existing_columns = {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for column_name, definition in columns:
        if column_name not in existing_columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
