"""Idempotent migration for durable provider user-input interaction tables (Package 4A)."""

from __future__ import annotations

import sqlite3

from .interaction_schema import get_provider_interaction_schema_statements


def migrate_provider_interaction_tables(conn: sqlite3.Connection) -> None:
    for statement in get_provider_interaction_schema_statements():
        conn.execute(statement)
