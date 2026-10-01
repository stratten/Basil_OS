"""Coverage for the one-time persisted American-spelling migration."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.schema_manager import (
    SchemaManager,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management import (
    american_spelling_migration,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.american_spelling_migration import (
    MARKER_TABLE,
    MIGRATION_NAME,
    americanize_persisted_text,
    migrate_american_spelling,
)

LEGACY_SCHEMA = """
CREATE TABLE parent_runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('running', 'cancelling', 'cancelled')),
    payload_json TEXT NOT NULL DEFAULT '{}',
    note TEXT NOT NULL DEFAULT '',
    file_path TEXT,
    error_type TEXT,
    title TEXT
);
CREATE INDEX idx_parent_runs_active ON parent_runs(status) WHERE status NOT IN ('cancelled');
CREATE TABLE child_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES parent_runs(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL
);
CREATE INDEX idx_child_events_live ON child_events(event_type) WHERE event_type <> 'cancelled';
CREATE TABLE run_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE legacy_counters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state TEXT NOT NULL CHECK (state IN ('open', 'cancelled'))
);
CREATE TRIGGER trg_parent_runs_audit AFTER UPDATE OF status ON parent_runs
WHEN NEW.status = 'cancelled'
BEGIN
    INSERT INTO run_audit (run_id, status) VALUES (NEW.id, NEW.status);
END;
CREATE VIRTUAL TABLE notes_fts USING fts5(body);
"""

LEGACY_PAYLOAD = {
    "cancelled": True,
    "event": "agent_task_cancelled",
    "cancelledAt": "2026-01-01T00:00:00Z",
    "message": "User cancelled it",
    "items": ["user_cancelled", "Keep Cancelled"],
}


def _legacy_connection(tmp_path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "legacy.db")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(LEGACY_SCHEMA)
    conn.executemany(
        "INSERT INTO parent_runs (id, status, payload_json, note, file_path, error_type, title) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("run-cancelled", "cancelled", json.dumps(LEGACY_PAYLOAD), "The meeting was cancelled", "/tmp/cancelled.txt", "CancelledError", "Cancelled"),
            ("run-cancelling", "cancelling", "{}", "", None, None, None),
            ("run-open", "running", json.dumps({"cancelled": False, "canceled": True}), "", None, None, None),
        ],
    )
    conn.executemany(
        "INSERT INTO child_events (id, run_id, event_type) VALUES (?, ?, ?)",
        [("evt-1", "run-cancelled", "agent_task_cancelled"), ("evt-2", "run-open", "runtime_cancelled")],
    )
    conn.execute("INSERT INTO notes_fts (body) VALUES ('agent_task_cancelled')")
    conn.commit()
    return conn


def _sql_for(conn: sqlite3.Connection, name: str) -> str:
    return conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()[0]


def test_migration_rebuilds_constraints_and_rewrites_identifier_values(tmp_path) -> None:
    with closing(_legacy_connection(tmp_path)) as conn:
        migrate_american_spelling(conn)

        table_sql = _sql_for(conn, "parent_runs")
        assert "'canceled'" in table_sql and "'canceling'" in table_sql
        assert "'cancelled'" not in table_sql and "'cancelling'" not in table_sql
        assert "'canceled'" in _sql_for(conn, "idx_parent_runs_active")
        assert "'canceled'" in _sql_for(conn, "idx_child_events_live")
        assert "'canceled'" in _sql_for(conn, "trg_parent_runs_audit")

        rows = {row[0]: row[1:] for row in conn.execute("SELECT id, status, payload_json, note, file_path, error_type, title FROM parent_runs")}
        assert rows["run-cancelled"][0] == "canceled"
        assert rows["run-cancelling"][0] == "canceling"
        assert rows["run-open"][0] == "running"
        assert json.loads(rows["run-cancelled"][1]) == {
            "canceled": True,
            "event": "agent_task_canceled",
            "canceledAt": "2026-01-01T00:00:00Z",
            "message": "User cancelled it",
            "items": ["user_canceled", "Keep Cancelled"],
        }
        assert json.loads(rows["run-open"][1]) == {"canceled": True}
        assert rows["run-cancelled"][2:] == ("The meeting was cancelled", "/tmp/cancelled.txt", "CancelledError", "Cancelled")

        assert dict(conn.execute("SELECT id, event_type FROM child_events")) == {
            "evt-1": "agent_task_canceled",
            "evt-2": "runtime_canceled",
        }
        assert conn.execute("SELECT run_id FROM child_events WHERE id = 'evt-1'").fetchone()[0] == "run-cancelled"
        assert sorted(row[0] for row in conn.execute("SELECT id FROM parent_runs")) == ["run-cancelled", "run-cancelling", "run-open"]
        assert conn.execute("SELECT body FROM notes_fts").fetchall() == [("agent_task_cancelled",)]
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute(f"SELECT name FROM {MARKER_TABLE}").fetchall() == [(MIGRATION_NAME,)]


def test_rebuilt_constraints_and_triggers_enforce_american_values(tmp_path) -> None:
    with closing(_legacy_connection(tmp_path)) as conn:
        migrate_american_spelling(conn)

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO parent_runs (id, status) VALUES ('run-british', 'cancelled')")
        conn.execute("INSERT INTO parent_runs (id, status) VALUES ('run-american', 'canceled')")
        conn.execute("UPDATE parent_runs SET status = 'canceled' WHERE id = 'run-open'")
        conn.commit()

        assert conn.execute("SELECT run_id, status FROM run_audit").fetchall() == [("run-open", "canceled")]
        conn.execute("DELETE FROM parent_runs WHERE id = 'run-cancelled'")
        conn.commit()
        assert conn.execute("SELECT id FROM child_events ORDER BY id").fetchall() == [("evt-2",)]


def test_rebuild_keeps_autoincrement_high_water_mark(tmp_path) -> None:
    with closing(_legacy_connection(tmp_path)) as conn:
        conn.executemany("INSERT INTO legacy_counters (state) VALUES (?)", [("open",), ("cancelled",), ("open",)])
        conn.execute("DELETE FROM legacy_counters WHERE id = 3")
        conn.commit()

        migrate_american_spelling(conn)
        conn.execute("INSERT INTO legacy_counters (state) VALUES ('canceled')")
        conn.commit()

        assert conn.execute("SELECT id, state FROM legacy_counters ORDER BY id").fetchall() == [
            (1, "open"),
            (2, "canceled"),
            (4, "canceled"),
        ]
        assert "'canceled'" in _sql_for(conn, "legacy_counters")


def test_migration_runs_once(tmp_path) -> None:
    with closing(_legacy_connection(tmp_path)) as conn:
        migrate_american_spelling(conn)
        conn.execute("INSERT INTO child_events (id, run_id, event_type) VALUES ('evt-3', 'run-open', 'user_cancelled')")
        conn.commit()

        migrate_american_spelling(conn)

        assert conn.execute("SELECT event_type FROM child_events WHERE id = 'evt-3'").fetchone()[0] == "user_cancelled"
        assert conn.execute(f"SELECT COUNT(*) FROM {MARKER_TABLE}").fetchone()[0] == 1


def test_failed_migration_rolls_back_every_change(tmp_path, monkeypatch) -> None:
    def fail_value_rewrite(conn: sqlite3.Connection) -> int:
        raise RuntimeError("simulated value rewrite failure")

    monkeypatch.setattr(american_spelling_migration, "_rewrite_legacy_values", fail_value_rewrite)
    with closing(_legacy_connection(tmp_path)) as conn:
        with pytest.raises(RuntimeError, match="simulated value rewrite failure"):
            migrate_american_spelling(conn)

        assert "'cancelled'" in _sql_for(conn, "parent_runs")
        assert conn.execute("SELECT status FROM parent_runs WHERE id = 'run-cancelled'").fetchone()[0] == "cancelled"
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name IN (?, 'parent_runs__legacy_spelling')", (MARKER_TABLE,)
        ).fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM child_events").fetchone()[0] == 2


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("cancelled", "canceled"),
        ("CANCELLING", "CANCELING"),
        ("agent_task_cancelled", "agent_task_canceled"),
        ("todo:cancelled:123", "todo:canceled:123"),
        ("The meeting was cancelled", "The meeting was cancelled"),
        ("Cancelled", "Cancelled"),
        ("CancelledError", "CancelledError"),
        ("/tmp/cancelled.txt", "/tmp/cancelled.txt"),
        ("{not json cancelled", "{not json cancelled"),
        ('["user_cancelled", "left alone cancelled"]', '["user_canceled", "left alone cancelled"]'),
        ('{"message": "User cancelled it"}', '{"message": "User cancelled it"}'),
    ],
)
def test_americanize_persisted_text(value: str, expected: str) -> None:
    assert americanize_persisted_text(value) == expected


def _downgrade_table_to_british_literals(conn: sqlite3.Connection, table_name: str) -> None:
    table_sql = _sql_for(conn, table_name)
    dependents = conn.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE tbl_name = ? AND type IN ('index', 'trigger') AND sql IS NOT NULL",
        (table_name,),
    ).fetchall()
    columns = ", ".join(f'"{row[1]}"' for row in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall())
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    for object_type, object_name, _ in dependents:
        conn.execute(f'DROP {object_type.upper()} "{object_name}"')
    conn.execute(f'ALTER TABLE "{table_name}" RENAME TO "{table_name}__downgrade"')
    conn.execute(table_sql.replace("'canceled'", "'cancelled'").replace("'canceling'", "'cancelling'"))
    conn.execute(f'INSERT INTO "{table_name}" ({columns}) SELECT {columns} FROM "{table_name}__downgrade"')
    conn.execute(f'DROP TABLE "{table_name}__downgrade"')
    for _, _, object_sql in dependents:
        conn.execute(object_sql)
    conn.commit()
    conn.execute("PRAGMA legacy_alter_table = OFF")
    conn.execute("PRAGMA foreign_keys = ON")


def _index_names(conn: sqlite3.Connection, table_name: str) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL ORDER BY name",
            (table_name,),
        )
    ]


def test_initialize_db_upgrades_a_legacy_todo_table_before_later_migrations(tmp_path) -> None:
    db_path = tmp_path / "knowledge.db"
    SQLiteKnowledgeService(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        _downgrade_table_to_british_literals(conn, "todo_items")
        assert "'cancelled'" in _sql_for(conn, "todo_items")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO todo_items (id, title, status, created_by_kind) VALUES ('todo-legacy', 'Legacy item', 'cancelled', 'user')"
        )
        conn.execute(
            "INSERT INTO todo_sources (id, todo_id, source_kind, source_id, created_by_kind) "
            "VALUES ('source-legacy', 'todo-legacy', 'manual', 'manual-legacy-1', 'user')"
        )
        conn.execute(f"DELETE FROM {MARKER_TABLE} WHERE name = ?", (MIGRATION_NAME,))
        conn.commit()
        index_names_before = _index_names(conn, "todo_items")

    SchemaManager(str(db_path)).initialize_db()

    with closing(sqlite3.connect(db_path)) as conn:
        todo_sql = _sql_for(conn, "todo_items")
        assert "'canceled'" in todo_sql and "'cancelled'" not in todo_sql
        assert conn.execute("SELECT status FROM todo_items WHERE id = 'todo-legacy'").fetchone()[0] == "canceled"
        assert conn.execute("SELECT COUNT(*) FROM todo_sources WHERE todo_id = 'todo-legacy'").fetchone()[0] == 1
        assert _index_names(conn, "todo_items") == index_names_before
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute(f"SELECT COUNT(*) FROM {MARKER_TABLE} WHERE name = ?", (MIGRATION_NAME,)).fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO todo_items (id, title, status, created_by_kind) VALUES ('todo-british', 'British item', 'cancelled', 'user')"
            )


def test_fresh_database_has_no_legacy_literals_and_records_marker(tmp_path) -> None:
    db_path = tmp_path / "fresh.db"
    SQLiteKnowledgeService(db_path)
    SchemaManager(str(db_path)).initialize_db()
    with closing(sqlite3.connect(db_path)) as conn:
        legacy_objects = conn.execute(
            "SELECT name FROM sqlite_master WHERE sql LIKE '%''cancelled''%' OR sql LIKE '%''cancelling''%'"
        ).fetchall()
        assert legacy_objects == []
        assert conn.execute(f"SELECT COUNT(*) FROM {MARKER_TABLE} WHERE name = ?", (MIGRATION_NAME,)).fetchone()[0] == 1
