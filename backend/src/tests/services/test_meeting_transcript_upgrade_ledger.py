"""Regression tests for durable live window-retranscription upgrades."""

import json

import pytest

from api.services.meetings.meeting_recorder import MeetingRecorder
from api.services.whisper_live_core.post_processing.meeting_transcript_upgrade_ledger import (
    apply_recorded_window_upgrades,
    finalize_recorded_window_upgrades,
    get_upgrade_ledger_path,
    record_window_upgrade,
)


def _transcript():
    return {
        "meeting_id": "meeting-1",
        "extra": "preserve-me",
        "segments": [
            {"start": 0, "end": 10, "text": "before", "speaker": "A"},
            {"start": 10, "end": 20, "text": "raw", "speaker": "A"},
            {"start": 20, "end": 30, "text": "after", "speaker": "A"},
        ],
    }


def test_replays_window_without_losing_unrelated_segments(tmp_path):
    record_window_upgrade(
        tmp_path,
        10,
        20,
        [{"start": 10, "end": 20, "text": "upgraded", "speaker": None}],
    )

    result = apply_recorded_window_upgrades(tmp_path, _transcript())

    assert [segment["text"] for segment in result["segments"]] == [
        "before",
        "upgraded",
        "after",
    ]
    assert result["extra"] == "preserve-me"


def test_empty_window_result_removes_stale_streaming_text(tmp_path):
    record_window_upgrade(tmp_path, 10, 20, [])

    result = apply_recorded_window_upgrades(tmp_path, _transcript())

    assert [segment["text"] for segment in result["segments"]] == ["before", "after"]


def test_later_overlapping_upgrade_wins_only_in_its_range(tmp_path):
    record_window_upgrade(
        tmp_path,
        10,
        20,
        [{"start": 10, "end": 20, "text": "first", "speaker": None}],
    )
    record_window_upgrade(
        tmp_path,
        10,
        20,
        [{"start": 10, "end": 20, "text": "second", "speaker": None}],
    )

    result = apply_recorded_window_upgrades(tmp_path, _transcript())

    assert [segment["text"] for segment in result["segments"]] == [
        "before",
        "second",
        "after",
    ]


def test_missing_ledger_leaves_transcript_unchanged(tmp_path):
    assert apply_recorded_window_upgrades(tmp_path, _transcript()) == _transcript()


def test_malformed_ledger_is_not_silently_ignored(tmp_path):
    get_upgrade_ledger_path(tmp_path).write_text("{not json")

    with pytest.raises(ValueError, match="Could not read"):
        apply_recorded_window_upgrades(tmp_path, _transcript())


def test_finalize_writes_canonical_transcript_idempotently(tmp_path, monkeypatch):
    transcript_path = tmp_path / "transcript.json"
    transcript_path.write_text(json.dumps(_transcript()))
    record_window_upgrade(
        tmp_path,
        10,
        20,
        [{"start": 10, "end": 20, "text": "upgraded", "speaker": None}],
    )
    monkeypatch.setattr(
        MeetingRecorder,
        "get_meeting_directory",
        staticmethod(lambda _meeting_id: tmp_path),
    )

    first = finalize_recorded_window_upgrades("meeting-1")
    second = finalize_recorded_window_upgrades("meeting-1")

    assert first == second
    assert [segment["text"] for segment in first["segments"]] == [
        "before",
        "upgraded",
        "after",
    ]
    assert get_upgrade_ledger_path(tmp_path).exists()
