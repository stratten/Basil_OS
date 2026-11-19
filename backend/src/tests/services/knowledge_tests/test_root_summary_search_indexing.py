"""A chain's search entry is created at once, then rebuilt when a turn stops being in flight, not on every write while it runs."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.mutations.root_summary import (
    IN_FLIGHT_TURN_STATUSES,
    recompute_root_summary,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
    initialize_sqlite_database_mode,
    reset_sqlite_connection_state_for_tests,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.schema_manager import (
    SchemaManager,
)


@pytest.fixture
def conn(tmp_path: Path):
    reset_sqlite_connection_state_for_tests()
    db_path = str(tmp_path / "root_summary.db")
    initialize_sqlite_database_mode(db_path)
    SchemaManager(db_path).initialize_db()
    connection = get_sync_connection(db_path)
    try:
        yield connection
    finally:
        connection.close()


def _insert_task(conn, task_id: str, root_id: str, sequence: int, status: str, prompt: str, result_message: str = "") -> None:
    result_data = '{"message": "%s"}' % result_message if result_message else None
    conn.execute(
        "INSERT INTO agent_tasks (id, root_task_id, chain_sequence_number, timestamp, original_prompt, transcribed_prompt, status, result_data) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (task_id, root_id, sequence, f"2026-11-18 10:00:0{sequence}", prompt, prompt, status, result_data),
    )


def _indexed_text(conn: sqlite3.Connection, root_id: str):
    row = conn.execute("SELECT content FROM agent_task_search_fts WHERE root_task_id = ?", (root_id,)).fetchone()
    return row["content"] if row else None


def _summary(conn, root_id: str):
    return conn.execute(
        "SELECT turn_count, latest_status, latest_agent_task_id, result_preview FROM agent_tasks WHERE id = ?",
        (root_id,),
    ).fetchone()


def test_a_new_chain_in_flight_is_searchable_by_its_request_at_once(conn):
    _insert_task(conn, "root-1", "root-1", 1, "processing", "find the zebra report")

    recompute_root_summary(conn, "root-1")

    assert "zebra" in _indexed_text(conn, "root-1")
    summary = _summary(conn, "root-1")
    assert summary["turn_count"] == 1
    assert summary["latest_status"] == "processing"


def test_a_chain_that_is_already_indexed_is_not_rebuilt_while_its_turn_runs(conn):
    _insert_task(conn, "root-1", "root-1", 1, "processing", "find the zebra report")
    recompute_root_summary(conn, "root-1")
    conn.execute("UPDATE agent_tasks SET result_data = ? WHERE id = 'root-1'", ('{"message": "Found the aardvark file"}',))

    recompute_root_summary(conn, "root-1")

    indexed = _indexed_text(conn, "root-1")
    assert "zebra" in indexed
    assert "aardvark" not in indexed
    assert _summary(conn, "root-1")["result_preview"] == "Found the aardvark file"


def test_every_in_flight_status_indexes_a_new_chain_once_and_then_defers(conn):
    for index, status in enumerate(sorted(IN_FLIGHT_TURN_STATUSES)):
        root_id = f"root-{index}"
        _insert_task(conn, root_id, root_id, 1, status, f"prompt {index}")
        recompute_root_summary(conn, root_id)
        assert f"prompt {index}" in _indexed_text(conn, root_id), status
        conn.execute("UPDATE agent_tasks SET result_data = ? WHERE id = ?", ('{"message": "later words"}', root_id))
        recompute_root_summary(conn, root_id)
        assert "later words" not in _indexed_text(conn, root_id), status


def test_the_chain_is_indexed_once_the_turn_finishes(conn):
    _insert_task(conn, "root-1", "root-1", 1, "processing", "find the zebra report")
    recompute_root_summary(conn, "root-1")
    conn.execute("UPDATE agent_tasks SET status = 'completed', result_data = ? WHERE id = 'root-1'", ('{"message": "Found the aardvark file"}',))

    recompute_root_summary(conn, "root-1")

    indexed = _indexed_text(conn, "root-1")
    assert "zebra" in indexed
    assert "aardvark" in indexed
    summary = _summary(conn, "root-1")
    assert summary["latest_status"] == "completed"
    assert summary["result_preview"] == "Found the aardvark file"


@pytest.mark.parametrize("status", ["failed", "canceled", "paused", "awaiting_user_input", "needs_clarification", "some_future_status"])
def test_every_status_that_is_not_in_flight_is_indexed(conn, status):
    _insert_task(conn, "root-1", "root-1", 1, status, "find the zebra report")

    recompute_root_summary(conn, "root-1")

    assert "zebra" in _indexed_text(conn, "root-1")


def test_a_follow_up_in_flight_keeps_the_earlier_turns_searchable(conn):
    _insert_task(conn, "root-1", "root-1", 1, "completed", "find the zebra report", "done")
    recompute_root_summary(conn, "root-1")
    _insert_task(conn, "turn-2", "root-1", 2, "processing", "now look for the quokka notes")

    recompute_root_summary(conn, "root-1")

    indexed = _indexed_text(conn, "root-1")
    assert "zebra" in indexed
    assert "quokka" not in indexed
    summary = _summary(conn, "root-1")
    assert summary["turn_count"] == 2
    assert summary["latest_status"] == "processing"
    assert summary["latest_agent_task_id"] == "turn-2"

    conn.execute("UPDATE agent_tasks SET status = 'completed' WHERE id = 'turn-2'")
    recompute_root_summary(conn, "root-1")

    indexed = _indexed_text(conn, "root-1")
    assert "zebra" in indexed
    assert "quokka" in indexed
    assert conn.execute("SELECT COUNT(*) FROM agent_task_search_fts WHERE root_task_id = 'root-1'").fetchone()[0] == 1


def test_a_missing_chain_clears_its_search_entry(conn):
    _insert_task(conn, "root-1", "root-1", 1, "completed", "find the zebra report")
    recompute_root_summary(conn, "root-1")
    assert _indexed_text(conn, "root-1") is not None
    conn.execute("DELETE FROM agent_tasks WHERE id = 'root-1'")

    recompute_root_summary(conn, "root-1")

    assert _indexed_text(conn, "root-1") is None
