"""The write-slot telemetry must name who waited, who held the slot, and how the hold was spent, without changing write behavior."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure import (
    write_telemetry,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
    initialize_sqlite_database_mode,
    reset_sqlite_connection_state_for_tests,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.schema_manager import (
    SchemaManager,
)


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def lines(self, marker: str) -> list[str]:
        return [message for message in self.messages if marker in message]


@pytest.fixture
def temp_db_path(tmp_path: Path) -> str:
    reset_sqlite_connection_state_for_tests()
    db_path = str(tmp_path / "telemetry.db")
    initialize_sqlite_database_mode(db_path)
    SchemaManager(db_path).initialize_db()
    return db_path


@pytest.fixture
def capture(monkeypatch: pytest.MonkeyPatch):
    # The backend's handlers sit on a non-propagating parent logger, so the handler goes on the telemetry logger itself.
    monkeypatch.setattr(write_telemetry, "SLOW_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(write_telemetry, "SLOW_HOLD_SECONDS", 0.05)
    handler = _Capture()
    write_telemetry.telemetry_logger.addHandler(handler)
    previous_level = write_telemetry.telemetry_logger.level
    write_telemetry.telemetry_logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        write_telemetry.telemetry_logger.removeHandler(handler)
        write_telemetry.telemetry_logger.setLevel(previous_level)


def _insert_conversation(conn, conversation_id: str) -> None:
    conn.execute(
        "INSERT INTO conversations (id, title, message_count, is_active, created_at, updated_at) "
        "VALUES (?, 'test', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        (conversation_id,),
    )


def test_a_fast_write_logs_nothing(temp_db_path: str, capture: _Capture) -> None:
    conn = get_sync_connection(temp_db_path)
    try:
        _insert_conversation(conn, "fast-1")
        conn.commit()
    finally:
        conn.close()

    assert capture.lines("sqlite-write-waited") == []
    assert capture.lines("sqlite-write-slot-held") == []


def test_an_idle_hold_and_the_writer_queued_behind_it_are_both_reported(
    temp_db_path: str, capture: _Capture
) -> None:
    holder_has_slot = threading.Event()

    def _holder() -> None:
        conn = get_sync_connection(temp_db_path)
        try:
            _insert_conversation(conn, "holder-1")
            holder_has_slot.set()
            time.sleep(0.4)
            conn.commit()
        finally:
            conn.close()

    thread = threading.Thread(target=_holder, name="telemetry-holder")
    thread.start()
    assert holder_has_slot.wait(timeout=5)

    waiter = get_sync_connection(temp_db_path)
    try:
        _insert_conversation(waiter, "waiter-1")
        waiter.commit()
    finally:
        waiter.close()
    thread.join(timeout=5)

    waited = capture.lines("sqlite-write-waited")
    assert len(waited) == 1
    assert "queued_ahead=0" in waited[0]
    assert "blocked_by_statement=" in waited[0]
    assert "INSERT" in waited[0]
    assert "wal_mb=" in waited[0]

    # Only the holder's hold is slow; the waiter's own write is fast once it is admitted, so it is correctly not reported.
    held = capture.lines("sqlite-write-slot-held")
    assert len(held) == 1
    holder_line = held[0]
    assert "thread=telemetry-holder" in holder_line
    idle_seconds = float(holder_line.split("idle_seconds=")[1].split()[0])
    statement_seconds = float(holder_line.split("statement_seconds=")[1].split()[0])
    assert idle_seconds >= 0.3
    assert statement_seconds < 0.3
    assert "statements=1 " in holder_line


def test_writes_through_a_cursor_are_counted_like_writes_through_the_connection(
    temp_db_path: str, capture: _Capture
) -> None:
    conn = get_sync_connection(temp_db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO conversations (id, title, message_count, is_active, created_at, updated_at) "
            "VALUES ('cursor-1', 'test', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        time.sleep(0.1)
        conn.commit()
    finally:
        conn.close()

    held = capture.lines("sqlite-write-slot-held")
    assert len(held) == 1
    assert "statements=1 " in held[0]
    assert "commit_seconds=" in held[0]


def test_a_rolled_back_write_still_reports_its_hold(temp_db_path: str, capture: _Capture) -> None:
    conn = get_sync_connection(temp_db_path)
    try:
        _insert_conversation(conn, "rollback-1")
        time.sleep(0.1)
        conn.rollback()
    finally:
        conn.close()

    assert len(capture.lines("sqlite-write-slot-held")) == 1


def test_the_one_minute_summary_is_emitted_once_the_window_has_elapsed(
    temp_db_path: str, capture: _Capture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(write_telemetry, "SUMMARY_INTERVAL_SECONDS", 0.0)
    conn = get_sync_connection(temp_db_path)
    try:
        _insert_conversation(conn, "summary-1")
        conn.commit()
    finally:
        conn.close()

    summaries = capture.lines("sqlite-write-summary")
    assert len(summaries) == 1
    # The count includes the schema-initialization writes the fixture made before the window was shortened.
    writes = int(summaries[0].split("writes=")[1].split()[0])
    assert writes >= 1
    assert "db=telemetry.db" in summaries[0]


def test_a_failing_logger_never_breaks_the_write(
    temp_db_path: str, capture: _Capture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _explode(*args, **kwargs):
        raise RuntimeError("logging is broken")

    monkeypatch.setattr(write_telemetry.telemetry_logger, "log", _explode)
    monkeypatch.setattr(write_telemetry.telemetry_logger, "info", _explode)
    monkeypatch.setattr(write_telemetry, "SUMMARY_INTERVAL_SECONDS", 0.0)

    conn = get_sync_connection(temp_db_path)
    try:
        _insert_conversation(conn, "broken-1")
        time.sleep(0.1)
        conn.commit()
    finally:
        conn.close()

    check = get_sync_connection(temp_db_path)
    try:
        row = check.execute("SELECT COUNT(*) FROM conversations WHERE id = 'broken-1'").fetchone()
    finally:
        check.close()
    assert row[0] == 1


def test_wal_megabytes_is_none_without_a_wal_file(tmp_path: Path) -> None:
    assert write_telemetry.wal_megabytes(str(tmp_path / "missing.db")) is None
