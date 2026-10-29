"""Tests for optional partial-segment streaming on ProcessingProgress (2D)."""

from api.services.whisper_live_core.post_processing.transcript_merger import (
    ProcessingProgress,
)


def _base_progress(**overrides) -> ProcessingProgress:
    defaults = dict(
        stage="transcription",
        stage_progress=0.5,
        current_time=30.0,
        total_time=60.0,
        message="Re-transcribing",
        eta_seconds=10.0,
    )
    defaults.update(overrides)
    return ProcessingProgress(**defaults)


def test_to_dict_omits_new_segments_when_empty() -> None:
    payload = _base_progress().to_dict()
    assert "new_segments" not in payload
    # Existing keys unchanged.
    assert payload["stage"] == "transcription"
    assert payload["overall_progress"] >= 0.0


def test_to_dict_includes_new_segments_when_present() -> None:
    segments = [
        {"start": 0.0, "end": 1.0, "text": "hello", "speaker": None},
        {"start": 1.0, "end": 2.0, "text": "world", "speaker": None},
    ]
    payload = _base_progress(new_segments=segments).to_dict()
    assert payload["new_segments"] == segments


def test_default_new_segments_is_isolated_per_instance() -> None:
    # Guard against a shared mutable default leaking across instances.
    a = _base_progress()
    a.new_segments.append({"start": 0.0, "end": 1.0, "text": "x"})
    b = _base_progress()
    assert b.new_segments == []
