"""Exclusion windows keep a recurring schedule from starting runs inside quiet hours."""

from datetime import datetime, timezone

import pytest

from api.services.scheduled_agent_tasks.scheduled_agent_task_service_components.schedule_exclusion_windows import (
    normalize_exclusion_windows,
    parse_exclusion_windows,
    shift_out_of_windows,
)
from api.services.scheduled_agent_tasks.scheduled_agent_task_service_components.schedule_time_math import (
    compute_next_run_at,
    get_zone,
    normalized_schedule_config,
)

NIGHT = {"start": "22:00", "end": "07:00"}


def _utc(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _next(config, now, tz="UTC"):
    return compute_next_run_at("recurring", config, tz, from_time=now)


def test_interval_landing_in_a_window_resumes_when_the_window_ends():
    config = {"mode": "interval", "minutes": 30, "exclusion_windows": [NIGHT]}
    assert _next(config, _utc(2026, 10, 27, 21, 50)) == _utc(2026, 10, 28, 7, 0).isoformat()


def test_interval_outside_a_window_is_unchanged():
    config = {"mode": "interval", "minutes": 30, "exclusion_windows": [NIGHT]}
    assert _next(config, _utc(2026, 10, 28, 6, 40)) == _utc(2026, 10, 28, 7, 10).isoformat()


def test_interval_that_would_land_just_before_the_end_resumes_at_the_end():
    config = {"mode": "interval", "minutes": 30, "exclusion_windows": [NIGHT]}
    assert _next(config, _utc(2026, 10, 28, 6, 20)) == _utc(2026, 10, 28, 7, 0).isoformat()


def test_multiple_windows_are_all_honored():
    config = {
        "mode": "interval",
        "minutes": 60,
        "exclusion_windows": [{"start": "00:00", "end": "06:00"}, {"start": "12:00", "end": "13:00"}],
    }
    assert _next(config, _utc(2026, 10, 27, 11, 30)) == _utc(2026, 10, 27, 13, 0).isoformat()


def test_chained_windows_shift_through_both():
    config = {
        "mode": "interval",
        "minutes": 30,
        "exclusion_windows": [{"start": "22:00", "end": "07:00"}, {"start": "07:00", "end": "08:00"}],
    }
    assert _next(config, _utc(2026, 10, 27, 21, 50)) == _utc(2026, 10, 28, 8, 0).isoformat()


def test_daily_schedule_skips_an_excluded_day():
    # 2026-10-30 is a Friday. Saturday and Sunday are excluded all day, so the next run is Monday.
    config = {"mode": "daily", "time": "09:00", "exclusion_windows": [{"start": "00:00", "end": "00:00", "days": [5, 6]}]}
    assert _next(config, _utc(2026, 10, 30, 10, 0)) == _utc(2026, 11, 2, 9, 0).isoformat()


def test_weekly_schedule_skips_an_occurrence_inside_a_window():
    # 2026-10-26 is a Monday. Monday 09:00 falls inside the 08:00-10:00 window, so the next run is Wednesday.
    config = {"mode": "weekly", "days": [0, 2], "time": "09:00", "exclusion_windows": [{"start": "08:00", "end": "10:00", "days": [0]}]}
    assert _next(config, _utc(2026, 10, 25, 12, 0)) == _utc(2026, 10, 28, 9, 0).isoformat()


def test_windows_are_read_in_the_schedule_timezone():
    # 23:00 UTC is 19:00 in New York (EDT). Four hours later is 23:00 local, inside 22:00-07:00, so the run moves to 07:00 EDT (11:00 UTC).
    config = {"mode": "interval", "minutes": 240, "exclusion_windows": [NIGHT]}
    assert _next(config, _utc(2026, 10, 27, 23, 0), tz="America/New_York") == _utc(2026, 10, 28, 11, 0).isoformat()


def test_a_midnight_crossing_window_limited_to_days_starts_on_those_days_only():
    zone = get_zone("UTC")
    windows = parse_exclusion_windows([{"start": "22:00", "end": "07:00", "days": [4]}])
    saturday_early = datetime(2026, 10, 31, 2, 0, tzinfo=zone)
    friday_early = datetime(2026, 10, 30, 2, 0, tzinfo=zone)
    assert shift_out_of_windows(saturday_early, windows) == datetime(2026, 10, 31, 7, 0, tzinfo=zone)
    assert shift_out_of_windows(friday_early, windows) == friday_early


def test_windows_that_leave_no_time_return_none():
    config = {"mode": "daily", "time": "23:00", "exclusion_windows": [NIGHT]}
    assert _next(config, _utc(2026, 10, 27, 12, 0)) is None


def test_one_time_schedules_ignore_windows():
    config = {"run_at": "2026-10-28T03:00:00+00:00", "exclusion_windows": [NIGHT]}
    assert compute_next_run_at("one_time", config, "UTC", from_time=_utc(2026, 10, 27, 12, 0)) == "2026-10-28T03:00:00+00:00"


def test_normalize_sorts_dedupes_and_canonicalizes():
    result = normalize_exclusion_windows(
        [
            {"start": "7:00", "end": "9:00", "days": [6, 5, 5]},
            {"start": "22:00", "end": "07:00"},
            {"start": "22:00", "end": "07:00"},
        ]
    )
    assert result == [{"start": "07:00", "end": "09:00", "days": [5, 6]}, {"start": "22:00", "end": "07:00"}]


@pytest.mark.parametrize(
    "raw",
    [
        "22:00-07:00",
        [{"start": "25:00", "end": "07:00"}],
        [{"start": "22:00"}],
        [{"start": "22:00", "end": "07:00", "days": [7]}],
        [{"start": "22:00", "end": "07:00", "days": "weekdays"}],
        ["22:00"],
        [{"start": "01:00", "end": "02:00"}] * 9,
    ],
)
def test_normalize_rejects_malformed_windows(raw):
    with pytest.raises(ValueError):
        normalize_exclusion_windows(raw)


def test_stored_garbage_is_ignored_instead_of_blocking_the_schedule():
    config = {"mode": "interval", "minutes": 30, "exclusion_windows": "garbage"}
    assert _next(config, _utc(2026, 10, 27, 12, 0)) == _utc(2026, 10, 27, 12, 30).isoformat()


def test_normalized_schedule_config_rejects_windows_that_cover_every_run():
    with pytest.raises(ValueError, match="no time"):
        normalized_schedule_config("recurring", {"mode": "daily", "time": "23:00", "exclusion_windows": [NIGHT]}, "UTC")


def test_normalized_schedule_config_drops_windows_from_one_time_and_empty_lists():
    assert normalized_schedule_config("one_time", {"run_at": "2026-10-28T03:00:00Z", "exclusion_windows": [NIGHT]}, "UTC") == {"run_at": "2026-10-28T03:00:00Z"}
    assert normalized_schedule_config("recurring", {"mode": "interval", "minutes": 5, "exclusion_windows": []}, "UTC") == {"mode": "interval", "minutes": 5}


def test_normalized_schedule_config_returns_canonical_windows():
    result = normalized_schedule_config("recurring", {"mode": "interval", "minutes": 30, "exclusion_windows": [{"start": "6:5", "end": "7:00"}]}, "UTC")
    assert result["exclusion_windows"] == [{"start": "06:05", "end": "07:00"}]
