"""Tests for the Whisper non-speech degeneration guard."""

from api.services.transcription.backends.openai_whisper_api.degeneration_guard import (
    MIN_DEGEN_SEGMENTS,
    is_degenerate_segment_run,
)


def _dot_run(count: int, *, step: float = 5.0) -> list[dict]:
    """Build a uniform run of pure-'.' segments like whisper-1 emits on silence."""
    return [
        {"start": i * step, "end": (i + 1) * step, "text": "."}
        for i in range(count)
    ]


def test_flags_full_span_dot_run() -> None:
    segments = _dot_run(74)  # 0..370s of "."
    assert is_degenerate_segment_run(segments, chunk_duration_seconds=363.3) is True


def test_does_not_flag_repeated_real_backchannel() -> None:
    # "Yeah" repeated is legitimate speech (it really appeared in chunk 2).
    segments = [
        {"start": i * 5.0, "end": (i + 1) * 5.0, "text": "Yeah."}
        for i in range(40)
    ]
    assert is_degenerate_segment_run(segments, chunk_duration_seconds=200.0) is False


def test_does_not_flag_mixed_real_content() -> None:
    segments = [
        {"start": 0.0, "end": 5.0, "text": "."},
        {"start": 5.0, "end": 10.0, "text": "So yeah, I'm all ears."},
        {"start": 10.0, "end": 15.0, "text": "Let me pull that up."},
        {"start": 15.0, "end": 20.0, "text": "."},
        {"start": 20.0, "end": 25.0, "text": "Absolutely, that works."},
        {"start": 25.0, "end": 30.0, "text": "Right, exactly."},
    ]
    assert is_degenerate_segment_run(segments, chunk_duration_seconds=30.0) is False


def test_does_not_flag_below_min_segment_count() -> None:
    segments = _dot_run(MIN_DEGEN_SEGMENTS - 1)
    assert is_degenerate_segment_run(segments, chunk_duration_seconds=20.0) is False


def test_does_not_flag_when_trivial_span_is_small_fraction() -> None:
    # Six "." segments spanning only ~10s of a 6-minute chunk: not a loop.
    segments = _dot_run(6, step=1.0)  # 0..6s of "."
    assert is_degenerate_segment_run(segments, chunk_duration_seconds=360.0) is False


def test_flags_when_duration_unknown_but_overwhelmingly_trivial() -> None:
    segments = _dot_run(74)
    assert is_degenerate_segment_run(segments, chunk_duration_seconds=0.0) is True


def test_punctuation_variants_count_as_trivial() -> None:
    segments = [
        {"start": i * 5.0, "end": (i + 1) * 5.0, "text": text}
        for i, text in enumerate(["...", ".", ",", "-", ". .", "..", ".", ",", "."])
    ]
    assert is_degenerate_segment_run(segments, chunk_duration_seconds=45.0) is True


def test_empty_segments_not_degenerate() -> None:
    assert is_degenerate_segment_run([], chunk_duration_seconds=100.0) is False
