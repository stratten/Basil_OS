"""Unit tests for browse keyset cursors, compact projection, and output budgeting."""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime

import pytest

from api.services.retrieval.browse_paging import (
    COMPACT_SUMMARY_CHARS,
    DEFAULT_BROWSE_OUTPUT_CHARS,
    MAX_BROWSE_PAGE_EVENTS,
    MIN_BROWSE_OUTPUT_CHARS,
    build_page,
    clamp_page_limit,
    decode_cursor,
    encode_cursor,
    event_key,
    project_event,
    resolve_output_budget,
    sort_newest_first,
    to_local_timestamp,
)


@pytest.fixture
def new_york_tz(monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _event(index: int, *, summary: str = "short") -> dict:
    return {
        "source_kind": "agent_task",
        "source_id": f"task-{index:03d}",
        "event_type": "agent_task",
        "occurred_at": "2026-07-27T12:00:00+00:00",
        "ended_at": None,
        "title": f"Task {index}",
        "summary": summary,
        "raw_summary": summary,
        "narrative": "long narrative " * 20,
        "narrative_state": "final",
        "is_open": False,
        "open_note": None,
        "outcome": "succeeded",
        "source_status": "completed",
        "payload": {"duration_s": index},
        "representation": "zettel",
    }


def test_cursor_round_trips_unicode_keys():
    event = {
        "occurred_at": "2026-07-27T09:00:00+00:00",
        "source_kind": "conversation",
        "source_id": "café-1",
    }
    assert decode_cursor(encode_cursor(event)) == event_key(event)


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "   ",
        "not a cursor!!",
        "ü",
        base64.urlsafe_b64encode(b'{"a": 1}').decode("ascii"),
        base64.urlsafe_b64encode(b'["a", "b"]').decode("ascii"),
        base64.urlsafe_b64encode(b'["a", "b", 3]').decode("ascii"),
        base64.urlsafe_b64encode(b"\xff\xfe").decode("ascii"),
    ],
)
def test_malformed_cursor_raises_value_error(cursor):
    with pytest.raises(ValueError, match="next_cursor"):
        decode_cursor(cursor)


def test_page_limit_and_budget_are_clamped():
    assert clamp_page_limit(0) == 1
    assert clamp_page_limit(10_000) == MAX_BROWSE_PAGE_EVENTS
    assert resolve_output_budget(None) == DEFAULT_BROWSE_OUTPUT_CHARS
    assert resolve_output_budget(10) == MIN_BROWSE_OUTPUT_CHARS
    assert resolve_output_budget(120_000) == 120_000


def test_compact_projection_keeps_back_reference_and_bounds_summary():
    event = _event(1, summary="x" * (COMPACT_SUMMARY_CHARS + 50))
    projected = project_event(event, "compact")
    assert set(projected) == {
        "source_kind",
        "source_id",
        "event_type",
        "occurred_at",
        "title",
        "outcome",
        "is_open",
        "representation",
        "summary",
    }
    assert projected["summary"] == "x" * COMPACT_SUMMARY_CHARS + "…"
    assert project_event(event, "full") is event


def test_compact_projection_omits_empty_summary():
    assert "summary" not in project_event(_event(1, summary=""), "compact")


def test_sort_breaks_timestamp_ties_by_kind_then_id():
    tied = [_event(1), _event(3), _event(2)]
    assert [event["source_id"] for event in sort_newest_first(tied)] == [
        "task-003",
        "task-002",
        "task-001",
    ]


def test_extra_candidate_produces_cursor_for_last_returned_event():
    candidates = sort_newest_first([_event(index) for index in range(4)])
    page = build_page(
        candidates, page_limit=3, max_output_chars=DEFAULT_BROWSE_OUTPUT_CHARS, view="compact"
    )
    assert len(page["events"]) == 3
    assert page["budget_trimmed"] is False
    assert decode_cursor(page["next_cursor"]) == event_key(candidates[2])


def test_last_page_has_no_cursor():
    candidates = sort_newest_first([_event(index) for index in range(3)])
    page = build_page(
        candidates, page_limit=3, max_output_chars=DEFAULT_BROWSE_OUTPUT_CHARS, view="compact"
    )
    assert page["next_cursor"] is None


def test_budget_trims_page_and_still_returns_cursor():
    candidates = sort_newest_first([_event(index, summary="y" * 600) for index in range(20)])
    page = build_page(
        candidates, page_limit=20, max_output_chars=MIN_BROWSE_OUTPUT_CHARS, view="full"
    )
    assert 1 <= len(page["events"]) < 20
    assert page["budget_trimmed"] is True
    assert decode_cursor(page["next_cursor"]) == event_key(candidates[len(page["events"]) - 1])
    assert len(json.dumps(page["events"], ensure_ascii=False)) <= MIN_BROWSE_OUTPUT_CHARS


def test_single_oversized_event_is_still_returned():
    page = build_page(
        [_event(1, summary="z" * 10_000)],
        page_limit=5,
        max_output_chars=MIN_BROWSE_OUTPUT_CHARS,
        view="full",
    )
    assert len(page["events"]) == 1
    assert page["next_cursor"] is None


def test_evening_utc_event_renders_on_previous_local_day(new_york_tz):
    stored = "2026-07-29T01:40:00+00:00"
    rendered = to_local_timestamp(stored)
    assert rendered == "2026-07-28T21:40:00-04:00"
    assert datetime.fromisoformat(rendered) == datetime.fromisoformat(stored)


def test_offsetless_timestamp_is_treated_as_utc(new_york_tz):
    assert to_local_timestamp("2026-07-29T01:40:00") == "2026-07-28T21:40:00-04:00"
    assert to_local_timestamp("2026-07-29T01:40:00Z") == "2026-07-28T21:40:00-04:00"


@pytest.mark.parametrize("value", [None, "", "not a timestamp", 17])
def test_unparseable_timestamp_passes_through(value):
    assert to_local_timestamp(value) == value


@pytest.mark.parametrize("view", ["compact", "full"])
def test_page_events_carry_local_times_but_cursor_keeps_stored_utc(new_york_tz, view):
    stored_events = []
    for index in range(3):
        event = _event(index)
        event["occurred_at"] = f"2026-07-29T0{index}:30:00+00:00"
        event["ended_at"] = f"2026-07-29T0{index}:45:00+00:00"
        stored_events.append(event)
    candidates = sort_newest_first(stored_events)
    originals = [dict(event) for event in candidates]

    page = build_page(
        candidates, page_limit=2, max_output_chars=DEFAULT_BROWSE_OUTPUT_CHARS, view=view
    )

    assert [event["occurred_at"] for event in page["events"]] == [
        "2026-07-28T22:30:00-04:00",
        "2026-07-28T21:30:00-04:00",
    ]
    if view == "full":
        assert page["events"][0]["ended_at"] == "2026-07-28T22:45:00-04:00"
    assert decode_cursor(page["next_cursor"]) == event_key(originals[1])
    assert candidates == originals
