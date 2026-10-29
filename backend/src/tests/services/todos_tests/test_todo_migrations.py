"""Coverage for the additive To-Do schema migration facade: fresh-database
idempotence, table creation on a pre-todo database, and additive-column
backfill on an in-development todo_items missing later columns."""

import sqlite3
from pathlib import Path

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.todos.migrations import (
    migrate_todo_tables,
)

REQUIRED_TABLES_DDL = """
CREATE TABLE activities (id TEXT PRIMARY KEY);
CREATE TABLE transcriptions (id TEXT PRIMARY KEY);
CREATE TABLE activity_metadata (id TEXT PRIMARY KEY);
CREATE TABLE activity_patterns (id TEXT PRIMARY KEY);
"""


def _run_migration(db_path: Path) -> None:
    conn = get_sync_connection(str(db_path), ensure_schema=False)
    try:
        migrate_todo_tables(conn)
        conn.commit()
    finally:
        conn.close()


def test_fresh_database_already_has_todo_tables_and_migration_is_a_noop(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    conn = get_sync_connection(str(db_path))  # ensure_schema=True: runs get_schema_statements()
    conn.close()

    _run_migration(db_path)  # must not raise, must not duplicate anything

    conn = get_sync_connection(str(db_path), ensure_schema=False)
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'todo_%'"
        ).fetchall()
    }
    assert {"todo_items", "todo_sources", "todo_references", "todo_events"}.issubset(tables)
    indexes = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_todo_%'"
        ).fetchall()
    }
    expected_indexes = {
        "idx_todo_items_status_updated_at",
        "idx_todo_items_idempotency_key",
        "idx_todo_sources_todo_id_created_at",
        "idx_todo_references_todo_id_created_at",
        "idx_todo_events_todo_id_created_at",
    }
    assert expected_indexes.issubset(indexes)


def test_migration_creates_todo_tables_on_a_pre_todo_database(tmp_path: Path) -> None:
    db_path = tmp_path / "pre_todo.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(REQUIRED_TABLES_DDL)
    conn.commit()
    conn.close()

    _run_migration(db_path)

    conn = get_sync_connection(str(db_path), ensure_schema=False)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'todo_items'"
    ).fetchone()
    assert row is not None
    reference_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'todo_references'"
    ).fetchone()
    assert reference_table is not None
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(todo_items)").fetchall()}
    assert {"description", "notes", "due_at", "completed_at", "idempotency_key", "idempotency_payload_hash", "revision"} <= columns
    conn.execute(
        "INSERT INTO todo_items (id, title, status, responsibility, priority, created_by_kind) "
        "VALUES ('t1', 'Test', 'open', 'user', 'normal', 'user')"
    )
    conn.commit()
    row = conn.execute("SELECT revision, description, notes, completed_at FROM todo_items WHERE id = 't1'").fetchone()
    assert row["revision"] == 1
    assert row["description"] == ""
    assert row["notes"] == ""
    assert row["completed_at"] is None


def test_migration_is_idempotent_when_run_twice_on_a_pre_todo_database(tmp_path: Path) -> None:
    db_path = tmp_path / "pre_todo_twice.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(REQUIRED_TABLES_DDL)
    conn.commit()
    conn.close()

    _run_migration(db_path)
    _run_migration(db_path)  # must not raise (CREATE TABLE/INDEX IF NOT EXISTS, additive-column presence check)

    conn = get_sync_connection(str(db_path), ensure_schema=False)
    count = conn.execute("SELECT COUNT(*) AS n FROM sqlite_master WHERE name = 'todo_items'").fetchone()["n"]
    assert count == 1


def test_migration_backfills_additive_columns_on_an_older_todo_items_table(tmp_path: Path) -> None:
    """Simulates an in-development database created before the additive
    columns existed: `todo_items` exists with only the original columns."""
    db_path = tmp_path / "old_todo_items.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(REQUIRED_TABLES_DDL)
    conn.execute(
        """
        CREATE TABLE todo_items (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            responsibility TEXT NOT NULL DEFAULT 'unspecified',
            priority TEXT NOT NULL DEFAULT 'normal',
            created_by_kind TEXT NOT NULL,
            created_by_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "INSERT INTO todo_items (id, title, status, responsibility, priority, created_by_kind) "
        "VALUES ('old-1', 'Pre-existing row', 'open', 'user', 'normal', 'user')"
    )
    conn.commit()
    conn.close()

    _run_migration(db_path)

    conn = get_sync_connection(str(db_path), ensure_schema=False)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(todo_items)").fetchall()}
    assert {"description", "notes", "due_at", "completed_at", "idempotency_key", "idempotency_payload_hash", "revision"} <= columns
    row = conn.execute("SELECT title, revision, description, completed_at FROM todo_items WHERE id = 'old-1'").fetchone()
    assert row["title"] == "Pre-existing row"
    assert row["revision"] == 1
    assert row["description"] == ""
    assert row["completed_at"] is None
