"""The backreference migration must upgrade a database created before it."""

import sqlite3

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.zettel_migrations import (
    migrate_zettel_backreference,
)


def _columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _table_exists(conn, table):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


@pytest.fixture()
def legacy_conn():
    """A pre-migration database: source tables and zettel_entries lack the new
    columns, and the abandoned watermark table still exists."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE agent_tasks (id TEXT PRIMARY KEY, timestamp TEXT, status TEXT)")
    conn.execute("CREATE TABLE activities (id TEXT PRIMARY KEY, timestamp TEXT)")
    conn.execute(
        "CREATE TABLE zettel_entries ("
        "id TEXT PRIMARY KEY, source_kind TEXT, source_id TEXT, event_type TEXT, "
        "occurred_at TEXT, title TEXT, summary TEXT, outcome TEXT, "
        "payload_json TEXT DEFAULT '{}', materialized_at TEXT)"
    )
    conn.execute("CREATE TABLE zettel_source_watermarks (source_kind TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO agent_tasks VALUES ('t1', '2026-07-24 10:00:00', 'completed')")
    conn.execute("INSERT INTO activities VALUES ('a1', '2026-07-24 10:00:00')")
    conn.execute(
        "INSERT INTO zettel_entries (id, source_kind, source_id, event_type, occurred_at, "
        "title, materialized_at) VALUES "
        "('agent_task:t1', 'agent_task', 't1', 'agent_task_run', '2026-07-24T10:00:00+00:00', 'T', 'x'), "
        "('screen_block:a1', 'screen_block', 'a1', 'screen_block', '2026-07-24T10:00:00+00:00', 'S', 'x')"
    )
    yield conn
    conn.close()


def test_adds_zettel_id_and_narrative_columns(legacy_conn):
    migrate_zettel_backreference(legacy_conn)
    assert "zettel_id" in _columns(legacy_conn, "agent_tasks")
    assert "zettel_id" in _columns(legacy_conn, "activities")
    assert "narrative_state" in _columns(legacy_conn, "zettel_entries")
    assert "is_open" in _columns(legacy_conn, "zettel_entries")


def test_drops_the_watermark_table(legacy_conn):
    migrate_zettel_backreference(legacy_conn)
    assert not _table_exists(legacy_conn, "zettel_source_watermarks")


def test_backfills_one_to_one_sources(legacy_conn):
    migrate_zettel_backreference(legacy_conn)
    assert legacy_conn.execute(
        "SELECT zettel_id FROM agent_tasks WHERE id='t1'"
    ).fetchone()[0] == "agent_task:t1"


def test_rebuilds_screen_blocks_on_first_run(legacy_conn):
    migrate_zettel_backreference(legacy_conn)
    remaining = legacy_conn.execute(
        "SELECT COUNT(*) AS n FROM zettel_entries WHERE source_kind='screen_block'"
    ).fetchone()["n"]
    assert remaining == 0


def test_is_idempotent(legacy_conn):
    migrate_zettel_backreference(legacy_conn)
    # A second run must not error nor re-stamp anything differently.
    migrate_zettel_backreference(legacy_conn)
    assert legacy_conn.execute(
        "SELECT zettel_id FROM agent_tasks WHERE id='t1'"
    ).fetchone()[0] == "agent_task:t1"
