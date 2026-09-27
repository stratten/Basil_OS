"""Normalization is the single definition of time and bounds for the stream."""

from datetime import datetime, timezone

from api.services.zettel.normalization import (
    PAYLOAD_MAX_CHARS,
    bounded_payload,
    content_digest,
    to_utc_iso,
    truncate,
)


def test_naive_sqlite_timestamp_is_treated_as_utc():
    assert to_utc_iso("2026-07-24 14:30:00") == "2026-07-24T14:30:00+00:00"


def test_offset_timestamp_is_converted_to_utc():
    assert to_utc_iso("2026-07-24T10:30:00-04:00") == "2026-07-24T14:30:00+00:00"


def test_zulu_and_datetime_inputs_are_accepted():
    assert to_utc_iso("2026-07-24T14:30:00Z") == "2026-07-24T14:30:00+00:00"
    aware = datetime(2026, 7, 24, 14, 30, tzinfo=timezone.utc)
    assert to_utc_iso(aware) == "2026-07-24T14:30:00+00:00"


def test_unparseable_and_empty_values_return_none():
    assert to_utc_iso(None) is None
    assert to_utc_iso("") is None
    assert to_utc_iso("not a timestamp") is None


def test_truncate_collapses_whitespace_and_caps_length():
    assert truncate("  a\n\n b  ", 50) == "a b"
    capped = truncate("x" * 300, 200)
    assert len(capped) == 200 and capped.endswith("\u2026")
    assert truncate("   ", 50) is None
    assert truncate(None, 50) is None


def test_oversized_payload_is_replaced_with_a_stub():
    encoded = bounded_payload({"blob": "y" * (PAYLOAD_MAX_CHARS * 2)})
    assert len(encoded) <= PAYLOAD_MAX_CHARS
    assert "_truncated" in encoded


def test_digest_is_stable_and_sensitive():
    assert content_digest("a", None, 1) == content_digest("a", None, 1)
    assert content_digest("a", None, 1) != content_digest("a", None, 2)
