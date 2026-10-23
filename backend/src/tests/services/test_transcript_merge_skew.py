"""Tests for cross-track start-skew correction in transcript merging (2E)."""

from api.services.whisper_live_core.post_processing.transcript_merger import (
    merge_session_transcripts,
)
from api.services.whisper_live_core.post_processing.meeting_transcript_utils import (
    parse_iso_to_epoch,
)


def test_parse_iso_to_epoch_handles_z_and_offset_and_invalid() -> None:
    z = parse_iso_to_epoch("2026-06-09T17:01:45.719Z")
    offset = parse_iso_to_epoch("2026-06-09T17:01:45.719+00:00")
    assert z is not None and offset is not None
    assert abs(z - offset) < 0.001
    assert parse_iso_to_epoch(None) is None
    assert parse_iso_to_epoch("") is None
    assert parse_iso_to_epoch("not-a-date") is None


def test_merge_applies_start_offset_changing_order() -> None:
    # System tap started 1.5s after the mic. Without correction a system line at
    # raw 0.5s would sort before a mic line at raw 1.0s; with the +1.5s offset
    # the system line lands at 2.0s and correctly orders after the mic line.
    members = [
        {
            "source": "Microphone",
            "start_offset_seconds": 0.0,
            "segments": [{"start": 1.0, "end": 1.4, "text": "mic first", "speaker": "Speaker 1"}],
        },
        {
            "source": "System Audio",
            "start_offset_seconds": 1.5,
            "segments": [{"start": 0.5, "end": 0.9, "text": "system later", "speaker": "Speaker 1"}],
        },
    ]

    merged = merge_session_transcripts(members)
    texts = [seg["text"] for seg in merged["segments"]]
    assert texts == ["mic first", "system later"]
    # System segment shifted onto the shared timeline.
    system_seg = next(s for s in merged["segments"] if s["text"] == "system later")
    assert abs(system_seg["start"] - 2.0) < 0.0001
    assert abs(system_seg["end"] - 2.4) < 0.0001


def test_merge_without_offset_preserves_raw_order() -> None:
    # Behavior-preserving when no offsets are supplied: raw-start sort.
    members = [
        {
            "source": "Microphone",
            "segments": [{"start": 1.0, "end": 1.4, "text": "mic", "speaker": "Speaker 1"}],
        },
        {
            "source": "System Audio",
            "segments": [{"start": 0.5, "end": 0.9, "text": "system", "speaker": "Speaker 1"}],
        },
    ]

    merged = merge_session_transcripts(members)
    texts = [seg["text"] for seg in merged["segments"]]
    assert texts == ["system", "mic"]


def test_merge_ignores_invalid_offset() -> None:
    members = [
        {
            "source": "Microphone",
            "start_offset_seconds": "bogus",
            "segments": [{"start": 1.0, "end": 1.4, "text": "mic", "speaker": "Speaker 1"}],
        },
    ]
    merged = merge_session_transcripts(members)
    assert merged["segments"][0]["start"] == 1.0
