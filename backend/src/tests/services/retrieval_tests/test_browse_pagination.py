"""Service-level keyset paging over merged zettel and raw history rows."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from api.services.retrieval.browse_paging import COMPACT_SUMMARY_CHARS, event_key
from api.services.retrieval.contracts import RetrievalAggregateRequest, RetrievalBrowseRequest
from api.services.retrieval.registry import build_default_retrieval_registry
from api.services.retrieval.service import UnifiedRetrievalService
from api.services.zettel import store
from api.services.zettel.sources.base import ZettelDraft

RANGE_START = "2026-07-27T00:00:00+00:00"
RANGE_END = "2026-07-28T00:00:00+00:00"


class _ConnectionContext:
    def __init__(self, conn) -> None:
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *exc_info):
        return False


@pytest.fixture()
def new_york_tz(monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _service(conn, monkeypatch) -> UnifiedRetrievalService:
    monkeypatch.setattr(
        "api.services.retrieval.service.get_sync_connection",
        lambda *args, **kwargs: _ConnectionContext(conn),
    )
    return UnifiedRetrievalService(":memory:", build_default_retrieval_registry())


def _add_card(conn, source_id: str, occurred_at: str, summary: str = "card summary") -> None:
    store.insert_card(
        conn,
        ZettelDraft(
            source_kind="agent_task",
            source_id=source_id,
            event_type="agent_task",
            occurred_at=occurred_at,
            title=f"Card {source_id}",
            summary=summary,
        ),
    )


def _add_raw_transcription(conn, source_id: str, occurred_at: str) -> None:
    conn.execute(
        "INSERT INTO transcriptions "
        "(id, timestamp, transcription_text, model_name, status, zettel_id, audio_file_path) "
        "VALUES (?, ?, 'raw transcription text', 'm', 'completed', NULL, ?)",
        (source_id, occurred_at, f"/tmp/{source_id}.wav"),
    )


def _seed_mixed_day(conn) -> int:
    tied = "2026-07-27T15:00:00+00:00"
    for index in range(4):
        _add_card(conn, f"card-tied-{index}", tied)
    for index in range(3):
        _add_card(conn, f"card-{index}", f"2026-07-27T1{index}:30:00+00:00")
    for index in range(3):
        _add_raw_transcription(conn, f"raw-tied-{index}", tied)
    for index in range(3):
        _add_raw_transcription(conn, f"raw-{index}", f"2026-07-27T0{index + 1}:45:00+00:00")
    conn.commit()
    return 13


def _browse_all(service, **kwargs) -> tuple[list[dict], list[dict]]:
    events: list[dict] = []
    pages: list[dict] = []
    cursor = None
    while True:
        page = service.browse(
            RetrievalBrowseRequest(start=RANGE_START, end=RANGE_END, cursor=cursor, **kwargs)
        )
        assert page["success"] is True
        pages.append(page)
        events.extend(page["events"])
        cursor = page["next_cursor"]
        if cursor is None:
            return events, pages
        assert len(pages) < 50


def test_paging_visits_every_event_once_in_newest_first_order(conn, monkeypatch):
    expected_total = _seed_mixed_day(conn)
    events, pages = _browse_all(_service(conn, monkeypatch), limit=4)
    keys = [event_key(event) for event in events]
    assert len(keys) == expected_total
    assert len(set(keys)) == expected_total
    assert keys == sorted(keys, reverse=True)
    assert [page["count"] for page in pages] == [4, 4, 4, 1]
    assert all(page["total_in_range"] == expected_total for page in pages)
    assert pages[0]["truncated"] is True
    assert pages[-1]["truncated"] is False
    assert {event["representation"] for event in events} == {"zettel", "raw"}


def test_compact_view_omits_heavy_fields_and_full_view_keeps_them(conn, monkeypatch):
    _seed_mixed_day(conn)
    _add_card(conn, "long-card", "2026-07-27T20:00:00+00:00", summary="s" * 500)
    conn.commit()
    service = _service(conn, monkeypatch)
    compact = service.browse(
        RetrievalBrowseRequest(start=RANGE_START, end=RANGE_END, limit=20, view="compact")
    )
    full = service.browse(RetrievalBrowseRequest(start=RANGE_START, end=RANGE_END, limit=20))
    assert compact["view"] == "compact"
    for event in compact["events"]:
        assert "narrative" not in event and "payload" not in event and "raw_summary" not in event
        assert {"source_kind", "source_id", "occurred_at", "title"} <= set(event)
        assert len(event.get("summary", "")) <= COMPACT_SUMMARY_CHARS + 1
    assert full["view"] == "full"
    assert all("payload" in event and "narrative_state" in event for event in full["events"])


def test_output_budget_trims_pages_without_losing_events(conn, monkeypatch):
    for index in range(12):
        _add_card(conn, f"long-{index:02d}", f"2026-07-27T{index + 1:02d}:00:00+00:00", summary="s" * 500)
    conn.commit()
    events, pages = _browse_all(
        _service(conn, monkeypatch), limit=500, view="full", max_output_chars=4_000
    )
    assert len({event_key(event) for event in events}) == 12
    assert len(pages) > 1
    assert pages[0]["budget_trimmed"] is True
    assert all(page["total_in_range"] == 12 for page in pages)


def test_invalid_cursor_returns_structured_error(conn, monkeypatch):
    result = _service(conn, monkeypatch).browse(
        RetrievalBrowseRequest(start=RANGE_START, end=RANGE_END, cursor="not-a-cursor")
    )
    assert result["success"] is False
    assert "next_cursor" in result["error"]


def test_page_limit_is_capped_at_500_and_empty_range_has_no_cursor(conn, monkeypatch):
    result = _service(conn, monkeypatch).browse(
        RetrievalBrowseRequest(start=RANGE_START, end=RANGE_END, limit=1000)
    )
    assert result["page_limit"] == 500
    assert result["count"] == 0
    assert result["total_in_range"] == 0
    assert result["next_cursor"] is None


def test_date_only_range_means_local_midnight(conn, monkeypatch, new_york_tz):
    evening = datetime(2026, 7, 27, 21, 0).astimezone().astimezone(timezone.utc).isoformat()
    next_morning = datetime(2026, 7, 28, 6, 0).astimezone().astimezone(timezone.utc).isoformat()
    _add_card(conn, "evening", evening)
    _add_card(conn, "next-morning", next_morning)
    conn.commit()
    result = _service(conn, monkeypatch).browse(
        RetrievalBrowseRequest(start="2026-07-27", end="2026-07-28", limit=10)
    )
    assert result["range"]["start"] == "2026-07-27T04:00:00+00:00"
    assert [event["source_id"] for event in result["events"]] == ["evening"]


def test_day_aggregate_buckets_by_local_calendar_day(conn, monkeypatch, new_york_tz):
    occurred = datetime(2026, 7, 27, 23, 30).astimezone().astimezone(timezone.utc).isoformat()
    assert occurred.startswith("2026-07-28")
    _add_card(conn, "late-card", occurred)
    _add_raw_transcription(conn, "late-raw", occurred)
    conn.commit()
    result = _service(conn, monkeypatch).aggregate(
        RetrievalAggregateRequest(
            group_by="day", start="2026-07-27T00:00:00+00:00", end="2026-07-29T00:00:00+00:00"
        )
    )
    assert result["grouped_counts"] == {"2026-07-27": 2}
