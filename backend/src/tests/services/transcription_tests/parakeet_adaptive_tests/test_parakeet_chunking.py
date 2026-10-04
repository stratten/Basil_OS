"""Synthetic tests for reusable Parakeet chunking helpers."""

from __future__ import annotations

import numpy as np

from api.services.transcription.backends.parakeet_components.parakeet_chunking import (
    ParakeetAudioChunk,
    build_silence_aware_parakeet_chunks,
    deduplicate_parakeet_boundary_words,
    offset_and_filter_parakeet_words,
    parakeet_word_tuples_to_segments,
    parakeet_word_tuples_to_text,
)


SAMPLE_RATE = 16000


# --- 2A: chunk_seconds registry parameter -------------------------------------

def test_get_model_chunk_seconds_resolves_registry_value() -> None:
    from api.core.models.models_registry import get_model_chunk_seconds

    # Parakeet + local Whisper declare 30.0; cloud declares 360.0.
    assert get_model_chunk_seconds("NVIDIA-parakeet-tdt-0.6b-v2-quantized") == 30.0
    assert get_model_chunk_seconds("OpenAI-whisper-large-v3-turbo") == 30.0
    assert get_model_chunk_seconds("openai-whisper-1") == 360.0


def test_get_model_chunk_seconds_returns_none_when_absent() -> None:
    from api.core.models.models_registry import get_model_chunk_seconds

    # Unknown model id -> None (callers fall back to the backend default).
    assert get_model_chunk_seconds("model-that-does-not-exist") is None


def test_builder_honors_target_chunk_seconds_override() -> None:
    # Uniform audio with a high min so the boundary is forced exactly at target,
    # proving a registry-style chunk window flows through the builder.
    audio = np.full(SAMPLE_RATE * 75, 0.05, dtype=np.float32)

    default_chunks = build_silence_aware_parakeet_chunks(
        audio, sample_rate=SAMPLE_RATE, min_chunk_seconds=90.0
    )
    assert default_chunks[0].accept_end_seconds == 30.0  # class default target

    override_chunks = build_silence_aware_parakeet_chunks(
        audio, sample_rate=SAMPLE_RATE, target_chunk_seconds=20.0, min_chunk_seconds=90.0
    )
    assert override_chunks[0].accept_end_seconds == 20.0  # honored override


def test_chunked_transcriber_overrides_target_from_registry(monkeypatch) -> None:
    from api.services.whisper_live_core.post_processing import (
        parakeet_chunked_transcriber as mod,
    )

    monkeypatch.setattr(mod, "get_model_chunk_seconds", lambda model_id: 22.0)
    transcriber = mod.ParakeetChunkedTranscriber("audio.wav", 100.0, "any-model")
    assert transcriber.target_chunk_seconds == 22.0


def test_chunked_transcriber_falls_back_to_default_chunk_window(monkeypatch) -> None:
    from api.services.whisper_live_core.post_processing import (
        parakeet_chunked_transcriber as mod,
    )

    monkeypatch.setattr(mod, "get_model_chunk_seconds", lambda model_id: None)
    transcriber = mod.ParakeetChunkedTranscriber("audio.wav", 100.0, "any-model")
    assert transcriber.target_chunk_seconds == mod.ParakeetChunkedTranscriber.target_chunk_seconds


def test_silence_aware_chunks_use_quiet_boundary_near_target() -> None:
    audio = np.full(SAMPLE_RATE * 75, 0.05, dtype=np.float32)
    audio[SAMPLE_RATE * 29 : SAMPLE_RATE * 31] = 0.001

    chunks = build_silence_aware_parakeet_chunks(audio, sample_rate=SAMPLE_RATE)

    assert len(chunks) >= 2
    assert 29.0 <= chunks[0].accept_end_seconds <= 31.0
    assert chunks[0].used_forced_boundary is False


def test_silence_aware_chunks_force_boundary_without_quiet_candidate() -> None:
    audio = np.full(SAMPLE_RATE * 75, 0.05, dtype=np.float32)

    chunks = build_silence_aware_parakeet_chunks(
        audio,
        sample_rate=SAMPLE_RATE,
        min_chunk_seconds=90.0,
    )

    assert len(chunks) >= 2
    assert chunks[0].accept_end_seconds == 30.0
    assert chunks[0].used_forced_boundary is True


def test_offset_and_filter_parakeet_words_keeps_only_accept_region() -> None:
    chunk = ParakeetAudioChunk(
        index=1,
        audio_start_seconds=9.5,
        audio_end_seconds=20.5,
        accept_start_seconds=10.0,
        accept_end_seconds=20.0,
        used_forced_boundary=False,
    )

    accepted = offset_and_filter_parakeet_words(
        chunk,
        [
            ("left", 0.1, 0.3),
            ("kept", 0.7, 1.0),
            ("right", 10.7, 10.9),
        ],
        audio_duration_seconds=75.0,
    )

    assert accepted == [("kept", 10.2, 10.5)]


def test_deduplicate_parakeet_boundary_words_removes_close_duplicate() -> None:
    deduplicated = deduplicate_parakeet_boundary_words(
        [("hello", 9.8, 10.2), ("world", 10.3, 10.7)],
        [("world", 10.35, 10.75), ("again", 11.0, 11.4)],
    )

    assert deduplicated == [("again", 11.0, 11.4)]


def test_parakeet_word_tuples_to_text_removes_space_before_punctuation() -> None:
    text = parakeet_word_tuples_to_text(
        [
            ("Hello", 0.0, 0.3),
            (",", 0.3, 0.4),
            ("world", 0.5, 0.8),
            ("!", 0.8, 0.9),
        ]
    )

    assert text == "Hello, world!"


def test_parakeet_word_tuples_to_segments_splits_on_gap_duration_and_terminal_punctuation() -> None:
    segments = parakeet_word_tuples_to_segments(
        [
            ("Hello", 0.0, 0.3),
            ("there", 0.4, 0.7),
            (".", 0.7, 0.8),
            ("After", 2.0, 2.3),
            ("gap", 2.4, 2.7),
            ("Long", 20.0, 20.3),
            ("segment", 33.0, 33.3),
        ]
    )

    assert segments == [
        {"start": 0.0, "end": 0.8, "text": "Hello there."},
        {"start": 2.0, "end": 2.7, "text": "After gap"},
        {"start": 20.0, "end": 20.3, "text": "Long"},
        {"start": 33.0, "end": 33.3, "text": "segment"},
    ]
