"""Additive schema migration facade for the To-Do domain.

This is a new, unreleased domain: `todo_items`, `todo_sources`, and
`todo_events` ship inside `get_schema_statements()`, so a fresh database
already has every column and index. This facade exists only to bring an
in-development database (one created before a given additive column or
index existed) up to date. It must never rebuild a table and must never
call `conn.commit()` -- `SchemaManager.initialize_db()` owns the transaction.
"""

import logging
import sqlite3

from ....schema import get_schema_statements

logger = logging.getLogger(__name__)

# Columns added after the initial `todo_items` CREATE TABLE landed. Every
# entry here must also exist, with an identical default, in the CREATE TABLE
# statement in schema.py, so a fresh database and a migrated in-development
# database converge on the same column set.
_TODO_ITEMS_ADDITIVE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("description", "TEXT NOT NULL DEFAULT ''"),
    ("notes", "TEXT NOT NULL DEFAULT ''"),
    ("due_at", "TEXT"),
    ("completed_at", "TEXT"),
    ("idempotency_key", "TEXT"),
    ("idempotency_payload_hash", "TEXT"),
    ("revision", "INTEGER NOT NULL DEFAULT 1"),
)

_TODO_INDEX_STATEMENT_PREFIXES = (
    "create index if not exists idx_todo_items_",
    "create unique index if not exists idx_todo_items_",
    "create index if not exists idx_todo_sources_",
    "create index if not exists idx_todo_references_",
    "create index if not exists idx_todo_events_",
)


def migrate_todo_tables(conn: sqlite3.Connection) -> None:
    """Create absent `todo_` tables, add absent additive columns, then create
    absent `idx_todo_` indexes, in that order. Column additions must run
    before index creation because an index may reference a column that only
    an in-development database is missing."""
    for statement in get_schema_statements():
        stmt = statement.strip().lower()
        if stmt.startswith("create table if not exists todo_items"):
            conn.execute(statement)
        elif stmt.startswith("create table if not exists todo_sources"):
            conn.execute(statement)
        elif stmt.startswith("create table if not exists todo_references"):
            conn.execute(statement)
        elif stmt.startswith("create table if not exists todo_events"):
            conn.execute(statement)

    _add_missing_todo_items_columns(conn)

    for statement in get_schema_statements():
        stmt = statement.strip().lower()
        if any(stmt.startswith(prefix) for prefix in _TODO_INDEX_STATEMENT_PREFIXES):
            conn.execute(statement)

    logger.info("To-Do schema migration facade applied (tables, columns, indexes)")


def _add_missing_todo_items_columns(conn: sqlite3.Connection) -> None:
    existing_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(todo_items)").fetchall()
    }
    if not existing_columns:
        # todo_items does not exist yet on this connection (should not happen
        # after the CREATE TABLE pass above, but keep this defensive).
        return
    for column_name, column_ddl in _TODO_ITEMS_ADDITIVE_COLUMNS:
        if column_name in existing_columns:
            continue
        conn.execute(f"ALTER TABLE todo_items ADD COLUMN {column_name} {column_ddl}")
        logger.info("Added additive column todo_items.%s", column_name)
