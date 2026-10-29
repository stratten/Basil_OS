"""A successful tool call records when the connection last worked, and Settings receives UTC-marked times."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from api.core.models.preferences import MCPConnectionRecord, Preferences
from api.routes.connections.connection_route_helpers import connection_to_dto
from api.routes.connections.models import CallLogEntry
from api.services.agent_processing.tools.external_services.external_catalog import audit
from api.services.mcp_connectors import connection_status_service as status_service

USED_AT = datetime(2026, 10, 28, 19, 34, 26, 706042)


@pytest.fixture
def saved(monkeypatch):
    """An in-memory stand-in for preferences.json holding one Gmail connection and counting writes."""
    prefs = Preferences()
    record = MCPConnectionRecord(id="gmail-1", friendly_name="Gmail", server_url="https://gmailmcp.googleapis.com/mcp/v1")
    prefs.connections.mcp_connections.append(record)
    writes = []
    monkeypatch.setattr("api.core.preferences.preferences_io.load_preferences", lambda: prefs)
    monkeypatch.setattr("api.core.preferences.preferences_io.save_preferences", lambda value: writes.append(value))
    return record, writes


def test_success_records_the_time_and_marks_a_never_checked_connection_healthy(saved):
    record, writes = saved
    assert status_service.mark_connection_used_successfully("gmail-1", USED_AT) is True
    assert record.last_successful_use_at == USED_AT
    assert record.last_connection_status == "healthy"
    assert record.last_connection_status_message == "Connected."
    assert record.last_connection_check_at is None
    assert len(writes) == 1


def test_success_clears_a_stale_needs_reconnect_status(saved):
    record, _ = saved
    record.last_connection_status = "needs_reconnect"
    record.last_connection_status_message = "Sign in again."
    assert status_service.mark_connection_used_successfully("gmail-1", USED_AT) is True
    assert record.last_connection_status == "healthy"
    assert record.last_connection_status_message == "Connected."


def test_calls_in_quick_succession_do_not_rewrite_preferences(saved):
    record, writes = saved
    assert status_service.mark_connection_used_successfully("gmail-1", USED_AT) is True
    assert status_service.mark_connection_used_successfully("gmail-1", USED_AT + timedelta(seconds=5)) is False
    assert record.last_successful_use_at == USED_AT
    assert status_service.mark_connection_used_successfully("gmail-1", USED_AT + timedelta(seconds=61)) is True
    assert record.last_successful_use_at == USED_AT + timedelta(seconds=61)
    assert len(writes) == 2


def test_unknown_connection_writes_nothing(saved):
    _, writes = saved
    assert status_service.mark_connection_used_successfully("missing", USED_AT) is False
    assert writes == []


class _Record:
    id = "gmail-1"
    server_url = "https://gmailmcp.googleapis.com/mcp/v1"


async def _audit(classification: str) -> None:
    await audit.record_external_catalog_audit(
        record=_Record(),
        tool_name="search_threads",
        arguments={},
        classification=classification,
        envelope={"ok": classification == "success", "result": {"text": "ok"}},
        started_at=USED_AT,
        completed_at=USED_AT,
    )


@pytest.fixture
def marked(monkeypatch):
    """Records each use the audit hook reports; the call-log write itself fails because no database is configured."""
    calls = []
    monkeypatch.setattr(status_service, "mark_connection_used_successfully", lambda connection_id, used_at: calls.append((connection_id, used_at)))
    return calls


@pytest.mark.asyncio
async def test_audit_of_a_successful_call_records_the_use_even_when_the_log_write_fails(marked):
    await _audit("success")
    assert marked == [("gmail-1", USED_AT)]


@pytest.mark.asyncio
@pytest.mark.parametrize("classification", ["error", "denied", "skipped"])
async def test_audit_of_an_unsuccessful_call_records_no_use(marked, classification):
    await _audit(classification)
    assert marked == []


@pytest.mark.asyncio
async def test_a_failure_recording_the_use_never_breaks_the_tool_call(monkeypatch):
    def broken(connection_id, used_at):
        raise OSError("preferences.json is read-only")

    monkeypatch.setattr(status_service, "mark_connection_used_successfully", broken)
    await _audit("success")


def test_connection_times_are_sent_with_a_utc_marker_and_unset_times_stay_null(saved):
    record, _ = saved
    record.last_connection_check_at = USED_AT
    record.last_successful_use_at = USED_AT
    payload = connection_to_dto(record).model_dump(mode="json")
    assert payload["last_connection_check_at"] == "2026-10-28T19:34:26.706042Z"
    assert payload["last_successful_use_at"] == "2026-10-28T19:34:26.706042Z"
    record.last_successful_use_at = None
    assert connection_to_dto(record).model_dump(mode="json")["last_successful_use_at"] is None


def test_call_log_times_are_sent_with_a_utc_marker():
    entry = CallLogEntry(
        id="1",
        connection_id="gmail-1",
        server_url="https://gmailmcp.googleapis.com/mcp/v1",
        tool_name="search_threads",
        result_classification="success",
        started_at="2026-10-28T19:34:26.706042",
        completed_at=None,
    )
    assert entry.started_at == "2026-10-28T19:34:26.706042Z"
    assert entry.completed_at is None
