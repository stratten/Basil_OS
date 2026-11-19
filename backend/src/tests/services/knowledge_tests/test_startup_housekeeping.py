"""Startup housekeeping rebuilds stale search entries a few at a time, trims the write-ahead log, and returns free space to the disk, without ever raising into startup."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.mutations.root_summary import (
    SEARCH_BUILDER_VERSION,
    build_search_document,
    recompute_root_summary,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure import (
    startup_housekeeping as housekeeping,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
    initialize_sqlite_database_mode,
    reset_sqlite_connection_state_for_tests,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.schema_manager import (
    SchemaManager,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.agent_tasks.summary_backfill import (
    build_agent_task_search_document,
)

REPEATED_TEXT = "ZEBRA-REPEATED-RESULT"
LOST_TEXT = "QUOKKA-ONLY-IN-THE-COPY"


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    """A database file made by an older build: it already has a page, so it stays in the default auto-vacuum mode."""
    reset_sqlite_connection_state_for_tests()
    path = str(tmp_path / "housekeeping.db")
    legacy = sqlite3.connect(path)
    try:
        legacy.execute("CREATE TABLE made_by_an_older_build(id INTEGER)")
        legacy.commit()
    finally:
        legacy.close()
    initialize_sqlite_database_mode(path)
    SchemaManager(path).initialize_db()
    return path


@pytest.fixture
def fresh_db_path(tmp_path: Path) -> str:
    """A database file this build creates from nothing."""
    reset_sqlite_connection_state_for_tests()
    path = str(tmp_path / "fresh.db")
    initialize_sqlite_database_mode(path)
    SchemaManager(path).initialize_db()
    return path


def _task_id(root_id: str, sequence: int) -> str:
    return root_id if sequence == 1 else f"{root_id}-t{sequence}"


def _own_result(root_id: str) -> dict:
    return {"message": "own result", "detail": REPEATED_TEXT}


def _artifacts_with_chain_copy(root_id: str, sequence: int, extra_copy_result=None) -> str:
    """What a follow-up stores: a copy of every earlier turn, each carrying that turn's prompt and result."""
    copies = [
        {"id": _task_id(root_id, earlier), "text": f"prompt {root_id}", "result": extra_copy_result if (extra_copy_result is not None and earlier == 1) else _own_result(root_id)}
        for earlier in range(1, sequence)
    ]
    return json.dumps({"chain_agentTasks": copies, "reference_paths": ["/files/quarterly-report.pdf"]})


def _insert_chain(conn, root_id: str, turns: int, status: str = "completed", own_result_for_first_turn=None, copied_first_result=None) -> None:
    for sequence in range(1, turns + 1):
        own_result = own_result_for_first_turn if (own_result_for_first_turn is not None and sequence == 1) else _own_result(root_id)
        conn.execute(
            "INSERT INTO agent_tasks (id, root_task_id, chain_sequence_number, timestamp, original_prompt, transcribed_prompt, status, result_data, accumulated_artifacts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_task_id(root_id, sequence), root_id, sequence, f"2026-11-18 10:00:{sequence:02d}", f"prompt {root_id}", f"prompt {root_id}", status,
             json.dumps(own_result), _artifacts_with_chain_copy(root_id, sequence, copied_first_result) if sequence > 1 else None),
        )
    conn.execute("UPDATE agent_tasks SET turn_count = ?, latest_status = ? WHERE id = ?", (turns, status, root_id))


def _write_old_style_entry(conn, root_id: str) -> None:
    conn.execute("INSERT INTO agent_task_search_fts(root_task_id, content) VALUES (?, ?)", (root_id, "old bloated entry"))


def _entry(db_path: str, root_id: str):
    conn = get_sync_connection(db_path, ensure_schema=False)
    try:
        content = conn.execute("SELECT content FROM agent_task_search_fts WHERE root_task_id = ?", (root_id,)).fetchone()
        version = conn.execute("SELECT builder_version FROM agent_task_search_index_state WHERE root_task_id = ?", (root_id,)).fetchone()
        return (content["content"] if content else None), (version["builder_version"] if version else None)
    finally:
        conn.close()


def _seed(db_path: str, chains: dict[str, int], status: str = "completed") -> None:
    conn = get_sync_connection(db_path)
    try:
        for root_id, turns in chains.items():
            _insert_chain(conn, root_id, turns, status)
            _write_old_style_entry(conn, root_id)
        conn.commit()
    finally:
        conn.close()


def _chain_rows(conn, root_id: str):
    return conn.execute("SELECT * FROM agent_tasks WHERE root_task_id = ? ORDER BY chain_sequence_number", (root_id,)).fetchall()


def test_copies_of_earlier_turns_that_repeat_indexed_text_are_left_out(db_path):
    conn = get_sync_connection(db_path)
    try:
        _insert_chain(conn, "root-a", 4)
        document = build_search_document(_chain_rows(conn, "root-a"))
    finally:
        conn.close()

    assert "quarterly-report.pdf" in document
    assert document.count(REPEATED_TEXT) == 4
    assert document.count("prompt root-a") == 4 * 2


def test_a_copy_that_holds_text_missing_from_the_turns_own_row_is_kept_once(db_path):
    conn = get_sync_connection(db_path)
    try:
        _insert_chain(
            conn, "root-a", 4,
            own_result_for_first_turn={"message": "the first turn's own result was later replaced"},
            copied_first_result={"message": "original result", "detail": LOST_TEXT},
        )
        document = build_search_document(_chain_rows(conn, "root-a"))
    finally:
        conn.close()

    assert document.count(LOST_TEXT) == 1


def test_the_migration_builder_and_the_write_path_builder_produce_the_same_document(db_path):
    conn = get_sync_connection(db_path)
    try:
        _insert_chain(conn, "root-a", 4, copied_first_result={"detail": LOST_TEXT}, own_result_for_first_turn={"message": "replaced"})
        rows = _chain_rows(conn, "root-a")
        assert build_agent_task_search_document(rows) == build_search_document(rows)
    finally:
        conn.close()


def test_rebuilding_an_entry_records_the_builder_version_and_removing_the_chain_clears_it(db_path):
    conn = get_sync_connection(db_path)
    try:
        _insert_chain(conn, "root-a", 2)
        recompute_root_summary(conn, "root-a")
        conn.commit()
        assert conn.execute("SELECT builder_version FROM agent_task_search_index_state WHERE root_task_id = 'root-a'").fetchone()[0] == SEARCH_BUILDER_VERSION
        conn.execute("DELETE FROM agent_tasks WHERE root_task_id = 'root-a'")
        recompute_root_summary(conn, "root-a")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM agent_task_search_index_state").fetchone()[0] == 0
    finally:
        conn.close()


def test_stale_entries_are_rebuilt_smaller_and_recorded(db_path):
    _seed(db_path, {"root-a": 3, "root-b": 2})

    rebuilt, remaining = housekeeping.reindex_stale_search_entries(db_path, budget_seconds=30)

    assert (rebuilt, remaining) == (2, 0)
    for root_id, turns in (("root-a", 3), ("root-b", 2)):
        content, version = _entry(db_path, root_id)
        assert "old bloated entry" not in content
        assert content.count(REPEATED_TEXT) == turns
        assert version == SEARCH_BUILDER_VERSION


def test_a_second_run_has_nothing_left_to_do(db_path):
    _seed(db_path, {"root-a": 2})
    housekeeping.reindex_stale_search_entries(db_path, budget_seconds=30)

    assert housekeeping.reindex_stale_search_entries(db_path, budget_seconds=30) == (0, 0)


def test_an_exhausted_budget_leaves_the_rest_for_the_next_launch(db_path):
    _seed(db_path, {"root-a": 3, "root-b": 2})

    assert housekeeping.reindex_stale_search_entries(db_path, budget_seconds=0) == (0, 2)
    assert _entry(db_path, "root-a")[1] is None


def test_the_biggest_chains_are_rebuilt_first(db_path):
    _seed(db_path, {"root-small": 1, "root-big": 5, "root-mid": 3})
    conn = get_sync_connection(db_path, ensure_schema=False)
    try:
        assert housekeeping.stale_search_roots(conn) == ["root-big", "root-mid", "root-small"]
    finally:
        conn.close()


def test_a_chain_whose_newest_turn_is_in_flight_is_not_stale(db_path):
    _seed(db_path, {"root-running": 2}, status="processing")

    assert housekeeping.reindex_stale_search_entries(db_path, budget_seconds=30) == (0, 0)


def test_a_new_database_is_created_in_incremental_auto_vacuum_mode(fresh_db_path):
    conn = sqlite3.connect(fresh_db_path)
    try:
        assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == housekeeping.AUTO_VACUUM_INCREMENTAL
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_an_existing_database_keeps_its_auto_vacuum_mode(tmp_path):
    reset_sqlite_connection_state_for_tests()
    path = str(tmp_path / "existing.db")
    legacy = sqlite3.connect(path)
    try:
        legacy.execute("CREATE TABLE already_here(id INTEGER)")
        legacy.commit()
    finally:
        legacy.close()

    initialize_sqlite_database_mode(path)

    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == housekeeping.AUTO_VACUUM_NONE
    finally:
        conn.close()


def test_a_new_database_has_free_pages_returned_in_slices_with_no_rewrite(fresh_db_path):
    conn = sqlite3.connect(fresh_db_path)
    try:
        conn.execute("CREATE TABLE junk(b BLOB)")
        for _ in range(40):
            conn.execute("INSERT INTO junk VALUES (zeroblob(100000))")
        conn.commit()
        conn.execute("DROP TABLE junk")
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    outcome, returned = housekeeping.reclaim_free_space(fresh_db_path, search_entries_remaining=0)

    assert outcome == "returned free pages in slices"
    assert returned > 0


def test_no_budget_rebuilds_every_stale_entry(db_path):
    _seed(db_path, {"root-a": 3, "root-b": 2, "root-c": 1})

    assert housekeeping.reindex_stale_search_entries(db_path, None) == (3, 0)
    for root_id in ("root-a", "root-b", "root-c"):
        assert _entry(db_path, root_id)[1] == SEARCH_BUILDER_VERSION


def test_a_stop_signal_ends_the_run_before_the_next_entry(db_path):
    _seed(db_path, {"root-a": 3, "root-b": 2})
    stop = threading.Event()
    stop.set()

    assert housekeeping.reindex_stale_search_entries(db_path, None, stop_event=stop) == (0, 2)
    assert _entry(db_path, "root-a")[1] is None


def test_a_stop_signal_during_the_rest_between_entries_ends_the_run(db_path, monkeypatch):
    _seed(db_path, {"root-a": 3, "root-b": 2})
    stop = threading.Event()
    real_wait = stop.wait

    def wait_then_stop(timeout=None):
        stop.set()
        return real_wait(0)

    monkeypatch.setattr(stop, "wait", wait_then_stop)

    rebuilt, remaining = housekeeping.reindex_stale_search_entries(db_path, None, stop_event=stop, pause_ratio=1.0)

    assert (rebuilt, remaining) == (1, 1)


def test_the_rest_between_entries_is_capped(db_path, monkeypatch):
    _seed(db_path, {"root-a": 2})
    rests = []
    monkeypatch.setattr(housekeeping.time, "sleep", rests.append)

    housekeeping.reindex_stale_search_entries(db_path, None, pause_ratio=1e9)

    assert rests == [housekeeping.REINDEX_MAX_PAUSE_SECONDS]


def test_counting_stale_entries_rebuilds_none(db_path):
    _seed(db_path, {"root-a": 3, "root-b": 2})

    assert housekeeping.count_stale_search_entries(db_path) == 2
    assert _entry(db_path, "root-a")[1] is None


def test_a_deferred_run_counts_the_stale_entries_and_leaves_the_rewrite_waiting(db_path):
    _seed(db_path, {"root-a": 3, "root-b": 2})

    report = housekeeping.run_startup_housekeeping(db_path, defer_reindex=True)

    assert report.search_entries_rebuilt == 0
    assert report.search_entries_remaining == 2
    assert _entry(db_path, "root-a")[1] is None


def test_a_deferred_run_on_an_unusable_database_does_not_raise(tmp_path):
    reset_sqlite_connection_state_for_tests()
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"this is not a sqlite database" * 100)

    report = housekeeping.run_startup_housekeeping(str(broken), defer_reindex=True)

    assert report.search_entries_remaining == -1


class _Messages(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@pytest.fixture
def housekeeping_log():
    handler = _Messages()
    previous_level = housekeeping.logger.level
    housekeeping.logger.addHandler(handler)
    housekeeping.logger.setLevel(logging.INFO)
    try:
        yield handler.lines
    finally:
        housekeeping.logger.removeHandler(handler)
        housekeeping.logger.setLevel(previous_level)


def test_the_background_run_finishes_every_entry_and_reports_it(db_path, housekeeping_log):
    _seed(db_path, {"root-a": 3, "root-b": 2})

    assert housekeeping.run_background_reindex(db_path) == (2, 0)

    assert _entry(db_path, "root-b")[1] == SEARCH_BUILDER_VERSION
    assert any("Background search re-index finished: rebuilt=2 remaining=0" in line for line in housekeeping_log)


def test_the_background_run_reports_an_early_stop(db_path, housekeeping_log):
    _seed(db_path, {"root-a": 3})
    stop = threading.Event()
    stop.set()

    assert housekeeping.run_background_reindex(db_path, stop) == (0, 1)

    assert any("Background search re-index stopped early: rebuilt=0 remaining=1" in line for line in housekeeping_log)


def test_the_background_run_never_raises_on_an_unusable_database(tmp_path):
    reset_sqlite_connection_state_for_tests()
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"this is not a sqlite database" * 100)

    assert housekeeping.run_background_reindex(str(broken)) == (0, -1)


def test_the_write_ahead_log_is_truncated_when_it_is_over_the_threshold(db_path):
    holder = sqlite3.connect(db_path)
    try:
        holder.execute("PRAGMA wal_autocheckpoint = 0")
        holder.execute("CREATE TABLE IF NOT EXISTS wal_filler(b BLOB)")
        holder.execute("INSERT INTO wal_filler VALUES (zeroblob(200000))")
        holder.commit()
        assert Path(f"{db_path}-wal").stat().st_size > 0

        assert housekeeping.truncate_wal_if_large(db_path, threshold_bytes=1) is True
        assert Path(f"{db_path}-wal").stat().st_size == 0
        assert housekeeping.truncate_wal_if_large(db_path, threshold_bytes=1) is False
    finally:
        holder.close()


def _create_free_pages(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE junk(b BLOB)")
        for _ in range(40):
            conn.execute("INSERT INTO junk VALUES (zeroblob(100000))")
        conn.commit()
        conn.execute("DROP TABLE junk")
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _pragma(db_path: str, name: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute(f"PRAGMA {name}").fetchone()[0])
    finally:
        conn.close()


EAGER = dict(min_reclaimable_bytes=1, min_reclaimable_fraction=0.0, disk_margin_bytes=0)


def test_free_space_is_not_reclaimed_while_search_entries_are_still_stale(db_path):
    _create_free_pages(db_path)

    outcome, returned = housekeeping.reclaim_free_space(db_path, search_entries_remaining=3, **EAGER)

    assert outcome == "waiting for the search re-index to finish"
    assert returned == 0
    assert _pragma(db_path, "auto_vacuum") == 0


def test_a_small_amount_of_free_space_is_left_alone(db_path):
    _create_free_pages(db_path)

    outcome, _ = housekeeping.reclaim_free_space(db_path, search_entries_remaining=0)

    assert outcome == "not needed"
    assert _pragma(db_path, "auto_vacuum") == 0


def test_not_enough_disk_skips_the_rewrite(db_path):
    _create_free_pages(db_path)

    outcome, _ = housekeeping.reclaim_free_space(
        db_path, search_entries_remaining=0, min_reclaimable_bytes=1, min_reclaimable_fraction=0.0, disk_margin_bytes=10**15
    )

    assert outcome == "skipped: not enough free disk for the one-time rewrite"
    assert _pragma(db_path, "auto_vacuum") == 0


def test_the_one_time_rewrite_converts_to_incremental_and_shrinks_the_file(db_path):
    _create_free_pages(db_path)
    before_pages = _pragma(db_path, "page_count")
    messages: list[str] = []

    outcome, returned = housekeeping.reclaim_free_space(db_path, search_entries_remaining=0, status=messages.append, **EAGER)

    assert outcome == "converted to incremental auto-vacuum"
    assert returned > 0
    assert _pragma(db_path, "auto_vacuum") == 2
    assert _pragma(db_path, "freelist_count") == 0
    assert _pragma(db_path, "page_count") < before_pages
    assert messages and "Optimizing the database" in messages[0]


def test_once_incremental_later_launches_return_free_pages_in_slices(db_path):
    _create_free_pages(db_path)
    housekeeping.reclaim_free_space(db_path, search_entries_remaining=0, **EAGER)
    assert _pragma(db_path, "auto_vacuum") == 2
    _create_free_pages_again(db_path)
    assert _pragma(db_path, "freelist_count") > 0

    outcome, returned = housekeeping.reclaim_free_space(db_path, search_entries_remaining=0)

    assert outcome == "returned free pages in slices"
    assert returned > 0
    assert _pragma(db_path, "freelist_count") == 0


def _create_free_pages_again(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE junk2(b BLOB)")
        for _ in range(40):
            conn.execute("INSERT INTO junk2 VALUES (zeroblob(100000))")
        conn.commit()
        conn.execute("DROP TABLE junk2")
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def test_the_full_run_reports_what_it_did(db_path):
    _seed(db_path, {"root-a": 3})

    report = housekeeping.run_startup_housekeeping(db_path)

    assert report.search_entries_rebuilt == 1
    assert report.search_entries_remaining == 0
    assert report.space_reclaim == "not needed"


def test_the_full_run_never_raises_even_when_the_database_is_unusable(tmp_path):
    reset_sqlite_connection_state_for_tests()
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"this is not a sqlite database" * 100)

    report = housekeeping.run_startup_housekeeping(str(broken))

    assert report.search_entries_remaining == -1
    assert report.space_reclaim in {"failed", "waiting for the search re-index to finish"}
