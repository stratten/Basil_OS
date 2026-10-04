"""Synthetic tests for adaptive Parakeet handling."""

from __future__ import annotations

import numpy as np

from api.services.transcription.backends.parakeet_components.parakeet_adaptive_transcription import (
    ParakeetPipelineTranscript,
    run_adaptive_parakeet_transcription,
)
from api.services.transcription.backends.parakeet_components.parakeet_conditioning import (
    apply_mild_peak_limited_gain,
    apply_speech_window_rms_conditioning,
)
from api.services.transcription.backends.parakeet_components.parakeet_coverage import (
    analyze_parakeet_audio_coverage,
    assess_parakeet_transcript_coverage,
)
from api.services.transcription.backends.parakeet_components.parakeet_decoder import (
    ParakeetToken,
)
from api.services.transcription.backends.parakeet_components.parakeet_segmentation import (
    build_active_span_windows,
    build_overlap_windows,
    offset_words_from_window,
)


SAMPLE_RATE = 16000


def test_coverage_gate_flags_low_density_active_audio() -> None:
    audio = np.full(SAMPLE_RATE * 10, 0.05, dtype=np.float32)
    audio_coverage = analyze_parakeet_audio_coverage(audio, sample_rate=SAMPLE_RATE)
    words = [ParakeetToken(text="hello", start_sec=0.5, end_sec=0.9)]

    assessment = assess_parakeet_transcript_coverage(
        audio_coverage=audio_coverage,
        words=words,
        text="hello",
    )

    assert assessment.suspect is True
    assert "low_word_density" in assessment.reasons
    assert "low_text_density" in assessment.reasons


def test_segment_windows_keep_context_separate_from_target_region() -> None:
    audio = np.zeros(SAMPLE_RATE * 8, dtype=np.float32)
    audio[SAMPLE_RATE * 2 : SAMPLE_RATE * 5] = 0.05
    audio_coverage = analyze_parakeet_audio_coverage(audio, sample_rate=SAMPLE_RATE)

    windows = build_active_span_windows(audio_coverage)
    kept_words = offset_words_from_window(
        [
            ParakeetToken(text="left", start_sec=0.2, end_sec=0.4),
            ParakeetToken(text="target", start_sec=1.4, end_sec=1.7),
            ParakeetToken(text="right", start_sec=4.4, end_sec=4.6),
        ],
        windows[0],
    )

    assert windows[0].padded_start_seconds < windows[0].original_start_seconds
    assert [word.text for word in kept_words] == ["target"]
    assert kept_words[0].start_sec >= windows[0].original_start_seconds


def test_overlap_windows_cover_duration_with_context() -> None:
    windows = build_overlap_windows(
        12.0,
        chunk_seconds=6.0,
        left_context_seconds=1.5,
        right_context_seconds=1.0,
        stride_seconds=4.0,
    )

    assert len(windows) == 3
    assert windows[0].original_start_seconds == 0.0
    assert windows[-1].original_end_seconds == 12.0
    assert windows[1].padded_start_seconds < windows[1].original_start_seconds


def test_conditioning_reports_bounded_gain_and_clipping() -> None:
    audio = np.full(SAMPLE_RATE * 2, 0.01, dtype=np.float32)
    audio_coverage = analyze_parakeet_audio_coverage(audio, sample_rate=SAMPLE_RATE)

    speech_result = apply_speech_window_rms_conditioning(
        audio,
        audio_coverage,
        max_gain=3.0,
    )
    peak_result = apply_mild_peak_limited_gain(
        audio,
        audio_coverage,
        max_gain=2.0,
    )

    assert speech_result.gain <= 3.0
    assert peak_result.gain <= 2.0
    assert speech_result.clipped_samples == 0
    assert peak_result.rms_after > peak_result.rms_before


def test_adaptive_selection_can_choose_overlap_parakeet_output() -> None:
    audio = np.full(SAMPLE_RATE * 12, 0.05, dtype=np.float32)

    def fake_infer(input_audio: np.ndarray) -> ParakeetPipelineTranscript:
        duration = input_audio.size / SAMPLE_RATE
        if duration >= 11.5:
            return ParakeetPipelineTranscript(
                text="short",
                words=[ParakeetToken(text="short", start_sec=0.5, end_sec=0.9)],
            )
        words = [
            ParakeetToken(text="covered", start_sec=0.4, end_sec=0.8),
            ParakeetToken(text="speech", start_sec=max(0.9, duration - 1.0), end_sec=max(1.2, duration - 0.4)),
        ]
        return ParakeetPipelineTranscript(
            text="covered speech",
            words=words,
        )

    result = run_adaptive_parakeet_transcription(
        audio,
        sample_rate=SAMPLE_RATE,
        infer_transcript=fake_infer,
    )

    assert result.baseline_suspect is True
    assert result.selected_strategy == "overlap_window_segmented"
    assert result.selected_run.coverage.coverage_score > result.runs[0].coverage.coverage_score
