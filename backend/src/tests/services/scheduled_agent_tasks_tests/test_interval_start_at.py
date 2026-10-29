"""Interval schedules accept an optional first-run time (``start_at``)."""

from datetime import datetime, timedelta, timezone

from api.services.scheduled_agent_tasks.scheduled_agent_task_service_components.schedule_time_math import (
    compute_next_run_at,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def _next(config, tz="UTC", now=NOW):
    return compute_next_run_at("recurring", config, tz, from_time=now)


def test_interval_without_start_at_repeats_from_now():
    assert _next({"mode": "interval", "minutes": 15}) == (NOW + timedelta(minutes=15)).isoformat()


def test_future_start_at_pins_the_first_run():
    result = _next({"mode": "interval", "minutes": 15, "start_at": "2026-10-27T18:30"})
    assert result == datetime(2026, 10, 27, 18, 30, tzinfo=timezone.utc).isoformat()


def test_start_at_is_read_in_the_schedule_timezone():
    # 18:30 in New York (EDT, UTC-4) is 22:30 UTC.
    result = _next({"mode": "interval", "minutes": 15, "start_at": "2026-10-27T18:30"}, tz="America/New_York")
    assert result == datetime(2026, 10, 27, 22, 30, tzinfo=timezone.utc).isoformat()


def test_past_start_at_is_ignored_so_the_interval_repeats_from_now():
    result = _next({"mode": "interval", "minutes": 15, "start_at": "2026-10-27T08:00"})
    assert result == (NOW + timedelta(minutes=15)).isoformat()


def test_start_at_equal_to_now_is_treated_as_passed():
    result = _next({"mode": "interval", "minutes": 15, "start_at": "2026-10-27T12:00"})
    assert result == (NOW + timedelta(minutes=15)).isoformat()


def test_blank_or_malformed_start_at_never_blocks_the_interval():
    expected = (NOW + timedelta(minutes=15)).isoformat()
    for bad in ("", "   ", "not a date", None, 12345):
        assert _next({"mode": "interval", "minutes": 15, "start_at": bad}) == expected


def test_start_at_with_an_explicit_offset_is_honored():
    result = _next({"mode": "interval", "minutes": 15, "start_at": "2026-10-27T20:00:00+02:00"})
    assert result == datetime(2026, 10, 27, 18, 0, tzinfo=timezone.utc).isoformat()


def test_start_at_does_not_affect_the_nonpositive_minutes_guard():
    assert _next({"mode": "interval", "minutes": 0, "start_at": "2026-10-27T18:30"}) is None
