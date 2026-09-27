"""Relative-time semantics for the unified history tool.

Tokens must resolve against the user's local day, matching
activity_query_tool, and must reach the store as UTC because occurred_at is
compared as text.
"""

from datetime import datetime, timedelta, timezone

from api.services.agent_processing.tools.internal_basil_tools.unified_history_tool import (
    _parse_time,
    _relative,
)


def _local_midnight() -> datetime:
    return datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)


def test_today_is_the_local_day_not_the_utc_day():
    assert _relative("today") == _local_midnight()


def test_yesterday_is_the_local_previous_day():
    assert _relative("yesterday") == _local_midnight() - timedelta(days=1)


def test_relative_tokens_reach_the_store_as_utc():
    parsed = datetime.fromisoformat(_parse_time("yesterday", datetime.now(timezone.utc)))
    assert parsed.utcoffset() == timedelta(0)
    assert parsed == _local_midnight() - timedelta(days=1)


def test_naive_iso_input_is_treated_as_utc():
    assert _parse_time("2026-07-24T10:00:00", datetime.now(timezone.utc)) == (
        "2026-07-24T10:00:00+00:00"
    )


def test_offset_input_is_normalized_to_utc():
    assert _parse_time("2026-07-24T06:00:00-04:00", datetime.now(timezone.utc)) == (
        "2026-07-24T10:00:00+00:00"
    )


def test_unparseable_input_falls_back_to_the_default_in_utc():
    default = datetime.now(timezone.utc) - timedelta(days=1)
    assert _parse_time("last tuesday-ish", default) == default.astimezone(timezone.utc).isoformat()


def test_unknown_token_is_not_silently_treated_as_a_date():
    assert _relative("fortnight") is None
