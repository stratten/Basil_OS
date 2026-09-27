"""Adaptive Parakeet-only transcription orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Sequence

import numpy as np

from .parakeet_conditioning import (
    ParakeetConditioningResult,
    apply_mild_peak_limited_gain,
    apply_small_dither_conditioning,
    apply_speech_window_rms_conditioning,
    apply_whole_file_rms_conditioning,
)
from .parakeet_coverage import (
    ParakeetAudioCoverage,
    ParakeetCoverageAssessment,
    analyze_parakeet_audio_coverage,
    assess_parakeet_transcript_coverage,
)
from .parakeet_decoder import ParakeetToken
from .parakeet_segmentation import (
    ParakeetSegmentWindow,
    build_active_span_windows,
    build_overlap_windows,
    merge_segment_words,
    offset_words_from_window,
    slice_audio_for_window,
    words_to_text,
)


ParakeetInferenceCallable = Callable[[np.ndarray], "ParakeetPipelineTranscript"]


@dataclass(frozen=True)
class ParakeetPipelineTranscript:
    text: str
    words: List[ParakeetToken]


@dataclass(frozen=True)
class ParakeetAdaptiveRun:
    strategy: str
    text: str
    words: List[ParakeetToken]
    coverage: ParakeetCoverageAssessment
    conditioning: ParakeetConditioningResult | None = None
    windows: List[ParakeetSegmentWindow] = field(default_factory=list)


@dataclass(frozen=True)
class ParakeetAdaptiveResult:
    text: str
    selected_strategy: str
    baseline_suspect: bool
    audio_coverage: ParakeetAudioCoverage
    selected_run: ParakeetAdaptiveRun
    runs: List[ParakeetAdaptiveRun]


def run_adaptive_parakeet_transcription(
    audio: np.ndarray,
    *,
    sample_rate: int,
    infer_transcript: ParakeetInferenceCallable,
    force_adaptive: bool = False,
) -> ParakeetAdaptiveResult:
    audio_f32 = audio.astype(np.float32, copy=False)
    audio_coverage = analyze_parakeet_audio_coverage(
        audio_f32,
        sample_rate=sample_rate,
    )
    baseline_conditioning = apply_whole_file_rms_conditioning(audio_f32)
    baseline_run = _run_conditioned_strategy(
        strategy="baseline_rms",
        conditioning=baseline_conditioning,
        audio_coverage=audio_coverage,
        infer_transcript=infer_transcript,
    )
    runs = [baseline_run]

    if baseline_run.coverage.suspect or force_adaptive:
        runs.extend(
            _run_segmented_strategies(
                audio_f32,
                audio_coverage=audio_coverage,
                infer_transcript=infer_transcript,
            )
        )
        runs.extend(
            _run_conditioning_strategies(
                audio_f32,
                audio_coverage=audio_coverage,
                infer_transcript=infer_transcript,
                include_dither=_should_try_dither(baseline_run.coverage),
            )
        )

    selected = _select_best_run(runs)
    return ParakeetAdaptiveResult(
        text=selected.text,
        selected_strategy=selected.strategy,
        baseline_suspect=baseline_run.coverage.suspect,
        audio_coverage=audio_coverage,
        selected_run=selected,
        runs=runs,
    )


def _run_conditioned_strategy(
    *,
    strategy: str,
    conditioning: ParakeetConditioningResult,
    audio_coverage: ParakeetAudioCoverage,
    infer_transcript: ParakeetInferenceCallable,
) -> ParakeetAdaptiveRun:
    transcript = infer_transcript(conditioning.audio.astype(np.float32, copy=False))
    coverage = assess_parakeet_transcript_coverage(
        audio_coverage=audio_coverage,
        words=transcript.words,
        text=transcript.text,
    )
    return ParakeetAdaptiveRun(
        strategy=strategy,
        text=transcript.text,
        words=transcript.words,
        coverage=coverage,
        conditioning=conditioning,
    )


def _run_segmented_strategies(
    audio: np.ndarray,
    *,
    audio_coverage: ParakeetAudioCoverage,
    infer_transcript: ParakeetInferenceCallable,
) -> List[ParakeetAdaptiveRun]:
    runs: List[ParakeetAdaptiveRun] = []
    active_windows = build_active_span_windows(audio_coverage)
    if active_windows:
        runs.append(
            _run_windowed_strategy(
                strategy="active_span_segmented",
                audio=audio,
                audio_coverage=audio_coverage,
                windows=active_windows,
                infer_transcript=infer_transcript,
            )
        )

    overlap_windows = build_overlap_windows(audio_coverage.duration_seconds)
    if overlap_windows:
        runs.append(
            _run_windowed_strategy(
                strategy="overlap_window_segmented",
                audio=audio,
                audio_coverage=audio_coverage,
                windows=overlap_windows,
                infer_transcript=infer_transcript,
            )
        )
    return runs


def _run_windowed_strategy(
    *,
    strategy: str,
    audio: np.ndarray,
    audio_coverage: ParakeetAudioCoverage,
    windows: Sequence[ParakeetSegmentWindow],
    infer_transcript: ParakeetInferenceCallable,
) -> ParakeetAdaptiveRun:
    word_groups: List[List[ParakeetToken]] = []
    for window in windows:
        window_audio = slice_audio_for_window(
            audio,
            window,
            sample_rate=audio_coverage.sample_rate,
        )
        if window_audio.size == 0:
            continue
        conditioned = apply_whole_file_rms_conditioning(window_audio)
        transcript = infer_transcript(conditioned.audio.astype(np.float32, copy=False))
        word_groups.append(offset_words_from_window(transcript.words, window))

    merged_words = merge_segment_words(word_groups)
    text = words_to_text(merged_words)
    coverage = assess_parakeet_transcript_coverage(
        audio_coverage=audio_coverage,
        words=merged_words,
        text=text,
    )
    return ParakeetAdaptiveRun(
        strategy=strategy,
        text=text,
        words=merged_words,
        coverage=coverage,
        windows=list(windows),
    )


def _run_conditioning_strategies(
    audio: np.ndarray,
    *,
    audio_coverage: ParakeetAudioCoverage,
    infer_transcript: ParakeetInferenceCallable,
    include_dither: bool,
) -> List[ParakeetAdaptiveRun]:
    conditioning_results = [
        apply_speech_window_rms_conditioning(audio, audio_coverage),
        apply_mild_peak_limited_gain(audio, audio_coverage),
    ]
    if include_dither:
        conditioning_results.append(apply_small_dither_conditioning(audio))

    return [
        _run_conditioned_strategy(
            strategy=result.strategy,
            conditioning=result,
            audio_coverage=audio_coverage,
            infer_transcript=infer_transcript,
        )
        for result in conditioning_results
    ]


def _should_try_dither(coverage: ParakeetCoverageAssessment) -> bool:
    if "active_audio_without_words" in coverage.reasons:
        return True
    return coverage.word_count <= 2 and coverage.text_chars <= 20


def _select_best_run(runs: Sequence[ParakeetAdaptiveRun]) -> ParakeetAdaptiveRun:
    if not runs:
        raise ValueError("No Parakeet adaptive runs were provided")

    strategy_rank = {
        "baseline_rms": 0,
        "active_span_segmented": 1,
        "overlap_window_segmented": 2,
        "speech_rms_conditioned": 3,
        "mild_peak_limited_gain": 4,
        "small_dither_conditioned": 5,
    }
    return max(
        runs,
        key=lambda run: (
            run.coverage.coverage_score,
            run.coverage.active_span_coverage_ratio,
            run.coverage.emitted_span_seconds,
            run.coverage.word_count,
            -strategy_rank.get(run.strategy, 99),
        ),
    )
