from datetime import datetime, timedelta, timezone

import pytest

from api.services.conversation.conversation_models import Conversation, Message, MessageRole
from api.services.conversation.conversation_timestamps import utc_iso_timestamp, utc_now_naive


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-09-30 12:27:00", "2026-09-30T12:27:00Z"),
        ("2026-09-30T12:27:00", "2026-09-30T12:27:00Z"),
        ("2026-09-30T12:27:00.125000", "2026-09-30T12:27:00.125000Z"),
        ("2026-09-30T12:27:00Z", "2026-09-30T12:27:00Z"),
        ("2026-09-30T08:27:00-04:00", "2026-09-30T12:27:00Z"),
        ("  2026-09-30 12:27:00  ", "2026-09-30T12:27:00Z"),
    ],
)
def test_utc_iso_timestamp_normalizes_strings(raw, expected):
    assert utc_iso_timestamp(raw) == expected


def test_utc_iso_timestamp_treats_naive_datetime_as_utc():
    assert utc_iso_timestamp(datetime(2026, 9, 30, 12, 27)) == "2026-09-30T12:27:00Z"


def test_utc_iso_timestamp_converts_aware_datetime_to_utc():
    eastern = timezone(timedelta(hours=-4))
    assert utc_iso_timestamp(datetime(2026, 9, 30, 8, 27, tzinfo=eastern)) == "2026-09-30T12:27:00Z"


@pytest.mark.parametrize("raw", ["", "   ", "not a timestamp", "2026-13-45 99:99:99"])
def test_utc_iso_timestamp_returns_unparseable_strings_unchanged(raw):
    assert utc_iso_timestamp(raw) == raw


def test_utc_iso_timestamp_passes_none_through():
    assert utc_iso_timestamp(None) is None


def test_utc_now_naive_is_naive_and_close_to_utc_now():
    value = utc_now_naive()
    assert value.tzinfo is None
    reference = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs((reference - value).total_seconds()) < 5


def test_model_default_timestamps_use_utc_clock():
    reference = datetime.now(timezone.utc).replace(tzinfo=None)
    message = Message(id="m", content="c", role=MessageRole.USER)
    conversation = Conversation(id="c")
    for value in (message.timestamp, conversation.created_at, conversation.updated_at):
        assert value.tzinfo is None
        assert abs((reference - value).total_seconds()) < 5
