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


def _loop_window(text, count, start=10.0, seconds_each=1.0):
    return [
        {"start": start + index * seconds_each, "end": start + (index + 1) * seconds_each, "text": text, "speaker": None}
        for index in range(count)
    ]


def test_finalize_collapses_a_silence_loop_from_a_retranscribed_window(tmp_path, monkeypatch):
    (tmp_path / "transcript.json").write_text(json.dumps(_transcript()))
    record_window_upgrade(tmp_path, 10, 20, _loop_window("Yeah.", 10))
    monkeypatch.setattr(MeetingRecorder, "get_meeting_directory", staticmethod(lambda _meeting_id: tmp_path))

    result = finalize_recorded_window_upgrades("meeting-1")

    assert [segment["text"] for segment in result["segments"]] == ["before", "Yeah.", "after"]
    on_disk = json.loads((tmp_path / "transcript.json").read_text())
    assert [segment["text"] for segment in on_disk["segments"]] == ["before", "Yeah.", "after"]
    assert on_disk["extra"] == "preserve-me"


def test_finalize_keeps_a_short_genuine_repeat_and_distinct_text(tmp_path, monkeypatch):
    (tmp_path / "transcript.json").write_text(json.dumps(_transcript()))
    window = _loop_window("Yeah.", 2) + [{"start": 12.0, "end": 13.0, "text": "Right.", "speaker": None}] + _loop_window("Yeah.", 2, start=13.0)
    record_window_upgrade(tmp_path, 10, 20, window)
    monkeypatch.setattr(MeetingRecorder, "get_meeting_directory", staticmethod(lambda _meeting_id: tmp_path))

    result = finalize_recorded_window_upgrades("meeting-1")

    assert [segment["text"] for segment in result["segments"]] == ["before", "Yeah.", "Yeah.", "Right.", "Yeah.", "Yeah.", "after"]


def test_finalize_does_not_collapse_a_loop_that_a_later_upgrade_replaced(tmp_path, monkeypatch):
    (tmp_path / "transcript.json").write_text(json.dumps(_transcript()))
    record_window_upgrade(tmp_path, 10, 20, _loop_window("Cool.", 10))
    record_window_upgrade(tmp_path, 10, 20, [{"start": 10, "end": 20, "text": "Real speech here.", "speaker": None}])
    monkeypatch.setattr(MeetingRecorder, "get_meeting_directory", staticmethod(lambda _meeting_id: tmp_path))

    result = finalize_recorded_window_upgrades("meeting-1")

    assert [segment["text"] for segment in result["segments"]] == ["before", "Real speech here.", "after"]
