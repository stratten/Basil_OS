"""Tests for the shared atomic transcript-write and integrity-guard helpers."""

import json
import wave
from pathlib import Path

import numpy as np
import pytest

from api.services.whisper_live_core.post_processing.atomic_json import (
    atomic_write_json,
    sanitize_transcript_segments,
    write_transcript_atomically,
)

SAMPLE_RATE = 16000


def _write_wav(path: Path, duration_seconds: float) -> None:
    samples = np.zeros(int(duration_seconds * SAMPLE_RATE), dtype=np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(samples.tobytes())


# ---- atomic_write_json ----

def test_atomic_write_json_writes_full_content(tmp_path: Path) -> None:
    target = tmp_path / "transcript.json"
    atomic_write_json(target, {"meeting_id": "abc", "segments": []})
    assert json.loads(target.read_text()) == {"meeting_id": "abc", "segments": []}


def test_atomic_write_json_never_leaves_a_temp_file_behind(tmp_path: Path) -> None:
    target = tmp_path / "transcript.json"
    atomic_write_json(target, {"meeting_id": "abc", "segments": []})
    leftover_temp_files = [p for p in tmp_path.iterdir() if p.name != target.name]
    assert leftover_temp_files == []


def test_atomic_write_json_preserves_prior_file_if_serialization_fails(tmp_path: Path) -> None:
    target = tmp_path / "transcript.json"
    atomic_write_json(target, {"meeting_id": "abc", "segments": ["good"]})

    class Unserializable:
        pass

    with pytest.raises(TypeError):
        atomic_write_json(target, {"meeting_id": "abc", "segments": [Unserializable()]})

    # The previous good file must still be intact; no torn/partial write.
    assert json.loads(target.read_text()) == {"meeting_id": "abc", "segments": ["good"]}
    leftover_temp_files = [p for p in tmp_path.iterdir() if p.name != target.name]
    assert leftover_temp_files == []


# ---- sanitize_transcript_segments ----

def test_sanitize_drops_interim_flagged_segments() -> None:
    segments = [
        {"start": 0.0, "end": 1.0, "text": "hello", "speaker": None},
        {"start": 1.0, "end": 2.0, "text": "stale", "speaker": None, "is_interim": True},
    ]
    cleaned = sanitize_transcript_segments(segments)
    assert cleaned == [{"start": 0.0, "end": 1.0, "text": "hello", "speaker": None}]


def test_sanitize_clamps_segments_to_real_audio_duration(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    _write_wav(audio_path, duration_seconds=10.0)
    segments = [
        {"start": 0.0, "end": 5.0, "text": "in range", "speaker": None},
        {"start": 8.0, "end": 12.0, "text": "clamp to duration", "speaker": None},
        {"start": 15.0, "end": 20.0, "text": "entirely past duration", "speaker": None},
    ]
    cleaned = sanitize_transcript_segments(segments, audio_path=audio_path)
    assert [s["text"] for s in cleaned] == ["in range", "clamp to duration"]
    assert cleaned[1]["end"] == pytest.approx(10.0)


def test_sanitize_collapses_duplicated_trailing_run() -> None:
    segments = [
        {"start": 0.0, "end": 1.0, "text": "hello there", "speaker": None},
        {"start": 1.0, "end": 2.0, "text": "repeat me", "speaker": None},
        {"start": 2.0, "end": 3.0, "text": "repeat me", "speaker": None},
        {"start": 3.0, "end": 4.0, "text": "repeat me", "speaker": None},
    ]
    cleaned = sanitize_transcript_segments(segments)
    assert [s["text"] for s in cleaned] == ["hello there", "repeat me"]


def test_sanitize_clamp_respects_resume_timeline_offset(tmp_path: Path) -> None:
    # A resumed recording part's own audio.wav is short, but its segments are
    # stamped on the logical multi-part timeline (already shifted by the
    # resume offset), so the valid window must shift with it rather than
    # starting at zero.
    audio_path = tmp_path / "audio.wav"
    _write_wav(audio_path, duration_seconds=1.0)
    segments = [
        {"start": 2.5, "end": 3.0, "text": "within this resumed part", "speaker": None},
        {"start": 3.4, "end": 3.6, "text": "clamp to end of this part", "speaker": None},
        {"start": 3.5, "end": 4.5, "text": "past this part's real audio", "speaker": None},
    ]
    cleaned = sanitize_transcript_segments(
        segments, audio_path=audio_path, timeline_offset_seconds=2.5
    )
    assert [s["text"] for s in cleaned] == [
        "within this resumed part",
        "clamp to end of this part",
    ]
    assert cleaned[1]["end"] == pytest.approx(3.5)


def test_sanitize_uses_discontinuous_native_capture_ranges(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    _write_wav(audio_path, duration_seconds=3.0)
    segments = [
        {"start": 10.2, "end": 11.0, "text": "first capture", "speaker": None},
        {"start": 11.2, "end": 12.0, "text": "socket gap", "speaker": None},
        {"start": 13.0, "end": 14.8, "text": "second capture", "speaker": None},
        {"start": 15.0, "end": 16.0, "text": "past capture", "speaker": None},
    ]

    cleaned = sanitize_transcript_segments(
        segments,
        audio_path=audio_path,
        timeline_ranges=[{"start": 10.0, "end": 11.0}, {"start": 13.0, "end": 15.0}],
    )

    assert [segment["text"] for segment in cleaned] == ["first capture", "second capture"]
    assert cleaned[0]["start"] == pytest.approx(10.2)
    assert cleaned[0]["end"] == pytest.approx(11.0)
    assert cleaned[1]["start"] == pytest.approx(13.0)
    assert cleaned[1]["end"] == pytest.approx(14.8)


def test_sanitize_is_noop_for_already_clean_segments(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    _write_wav(audio_path, duration_seconds=10.0)
    segments = [
        {"start": 0.0, "end": 1.0, "text": "a", "speaker": None},
        {"start": 1.0, "end": 2.0, "text": "b", "speaker": None},
    ]
    assert sanitize_transcript_segments(segments, audio_path=audio_path) == segments


# ---- write_transcript_atomically ----

def test_write_transcript_atomically_sanitizes_before_persisting(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    _write_wav(audio_path, duration_seconds=5.0)
    transcript_path = tmp_path / "transcript.json"

    transcript = {
        "meeting_id": "abc",
        "segments": [
            {"start": 0.0, "end": 1.0, "text": "kept", "speaker": None},
            {"start": 1.0, "end": 2.0, "text": "interim leak", "speaker": None, "is_interim": True},
            {"start": 9.0, "end": 12.0, "text": "past real duration", "speaker": None},
        ],
    }
    write_transcript_atomically(transcript, transcript_path, audio_path=audio_path)

    saved = json.loads(transcript_path.read_text())
    assert saved["segments"] == [{"start": 0.0, "end": 1.0, "text": "kept", "speaker": None}]
