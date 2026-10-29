"""Coverage scoring for Parakeet adaptive transcription."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import List, Sequence

import numpy as np

from .parakeet_decoder import ParakeetToken


PARAKEET_COVERAGE_WINDOW_SECONDS: float = 0.25


@dataclass(frozen=True)
class ParakeetAudioSpan:
    start_seconds: float
    end_seconds: float

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)


@dataclass(frozen=True)
class ParakeetAudioCoverage:
    sample_rate: int
    sample_count: int
    duration_seconds: float
    rms: float
    peak: float
    window_seconds: float
    threshold: float
    active_windows: int
    total_windows: int
    active_window_ratio: float
    active_spans: List[ParakeetAudioSpan] = field(default_factory=list)

    @property
    def active_duration_seconds(self) -> float:
        return round(sum(span.duration_seconds for span in self.active_spans), 3)


@dataclass(frozen=True)
class ParakeetCoverageAssessment:
    suspect: bool
    coverage_score: float
    reasons: List[str]
    word_count: int
    text_chars: int
    word_density: float
    text_chars_per_active_second: float
    emitted_start_seconds: float | None
    emitted_end_seconds: float | None
    emitted_span_seconds: float
    active_span_coverage_ratio: float
    trailing_active_audio_after_last_word_seconds: float
    longest_uncovered_active_span_seconds: float
    repeated_adjacent_words: int


def analyze_parakeet_audio_coverage(
    audio: np.ndarray,
    *,
    sample_rate: int,
    window_seconds: float = PARAKEET_COVERAGE_WINDOW_SECONDS,
) -> ParakeetAudioCoverage:
    audio_f32 = audio.astype(np.float32, copy=False)
    if audio_f32.size == 0 or sample_rate <= 0:
        return ParakeetAudioCoverage(
            sample_rate=max(0, sample_rate),
            sample_count=0,
            duration_seconds=0.0,
            rms=0.0,
            peak=0.0,
            window_seconds=window_seconds,
            threshold=0.0,
            active_windows=0,
            total_windows=0,
            active_window_ratio=0.0,
            active_spans=[],
        )

    rms = float(np.sqrt(np.mean(audio_f32 * audio_f32)))
    peak = float(np.max(np.abs(audio_f32)))
    threshold = max(1e-4, rms * 0.15, peak * 0.01)
    window_values = _window_rms_values(
        audio_f32,
        sample_rate=sample_rate,
        window_seconds=window_seconds,
    )
    active_flags = [value >= threshold for value in window_values]
    active_windows = sum(active_flags)
    return ParakeetAudioCoverage(
        sample_rate=sample_rate,
        sample_count=int(audio_f32.size),
        duration_seconds=round(audio_f32.size / sample_rate, 3),
        rms=round(rms, 8),
        peak=round(peak, 8),
        window_seconds=window_seconds,
        threshold=round(threshold, 8),
        active_windows=active_windows,
        total_windows=len(window_values),
        active_window_ratio=round(active_windows / len(window_values), 4)
        if window_values
        else 0.0,
        active_spans=_active_spans(active_flags, window_seconds=window_seconds),
    )


def assess_parakeet_transcript_coverage(
    *,
    audio_coverage: ParakeetAudioCoverage,
    words: Sequence[ParakeetToken],
    text: str,
) -> ParakeetCoverageAssessment:
    active_duration = audio_coverage.active_duration_seconds
    word_count = len(words)
    text_chars = len(" ".join(text.strip().split()))
    emitted_start = round(words[0].start_sec, 3) if words else None
    emitted_end = round(words[-1].end_sec, 3) if words else None
    emitted_span = (
        round(max(0.0, words[-1].end_sec - words[0].start_sec), 3)
        if words
        else 0.0
    )
    word_density = round(word_count / active_duration, 3) if active_duration > 0 else 0.0
    char_density = round(text_chars / active_duration, 3) if active_duration > 0 else 0.0
    covered_spans = _count_active_spans_with_words(audio_coverage.active_spans, words)
    active_span_coverage_ratio = (
        round(covered_spans / len(audio_coverage.active_spans), 4)
        if audio_coverage.active_spans
        else 0.0
    )
    trailing_active = _trailing_active_audio_after_last_word(
        audio_coverage.active_spans,
        emitted_end,
    )
    longest_uncovered_span = _longest_uncovered_active_span(
        audio_coverage.active_spans,
        words,
    )
    repeated_adjacent_words = _count_repeated_adjacent_words(words)

    reasons: List[str] = []
    if active_duration >= 0.75 and word_count == 0:
        reasons.append("active_audio_without_words")
    if trailing_active >= 0.75:
        reasons.append("active_audio_after_last_word")
    if longest_uncovered_span >= 1.0:
        reasons.append("active_span_without_word_overlap")
    if active_duration >= 4.0 and word_density < 1.55:
        reasons.append("low_word_density")
    if active_duration >= 4.0 and char_density < 8.0:
        reasons.append("low_text_density")
    if repeated_adjacent_words > 0:
        reasons.append("repeated_adjacent_words")

    coverage_score = _coverage_score(
        active_span_coverage_ratio=active_span_coverage_ratio,
        emitted_span_seconds=emitted_span,
        active_duration_seconds=active_duration,
        word_density=word_density,
        char_density=char_density,
        trailing_active_seconds=trailing_active,
        longest_uncovered_span_seconds=longest_uncovered_span,
        repeated_adjacent_words=repeated_adjacent_words,
    )
    return ParakeetCoverageAssessment(
        suspect=len(reasons) >= 2 or "active_audio_without_words" in reasons,
        coverage_score=coverage_score,
        reasons=reasons,
        word_count=word_count,
        text_chars=text_chars,
        word_density=word_density,
        text_chars_per_active_second=char_density,
        emitted_start_seconds=emitted_start,
        emitted_end_seconds=emitted_end,
        emitted_span_seconds=emitted_span,
        active_span_coverage_ratio=active_span_coverage_ratio,
        trailing_active_audio_after_last_word_seconds=trailing_active,
        longest_uncovered_active_span_seconds=longest_uncovered_span,
        repeated_adjacent_words=repeated_adjacent_words,
    )


def _window_rms_values(
    audio: np.ndarray,
    *,
    sample_rate: int,
    window_seconds: float,
) -> List[float]:
    window_samples = max(1, int(round(window_seconds * sample_rate)))
    values: List[float] = []
    for start in range(0, audio.size, window_samples):
        window = audio[start : start + window_samples]
        if window.size:
            values.append(float(np.sqrt(np.mean(window * window))))
    return values


def _active_spans(
    active_flags: Sequence[bool],
    *,
    window_seconds: float,
) -> List[ParakeetAudioSpan]:
    spans: List[ParakeetAudioSpan] = []
    active_start: int | None = None
    for index, active in enumerate(active_flags):
        if active and active_start is None:
            active_start = index
        elif not active and active_start is not None:
            spans.append(_span_from_indices(active_start, index, window_seconds))
            active_start = None
    if active_start is not None:
        spans.append(_span_from_indices(active_start, len(active_flags), window_seconds))
    return spans


def _span_from_indices(
    start_index: int,
    end_index: int,
    window_seconds: float,
) -> ParakeetAudioSpan:
    return ParakeetAudioSpan(
        start_seconds=round(start_index * window_seconds, 3),
        end_seconds=round(end_index * window_seconds, 3),
    )


def _count_active_spans_with_words(
    active_spans: Sequence[ParakeetAudioSpan],
    words: Sequence[ParakeetToken],
) -> int:
    return sum(1 for span in active_spans if any(_overlaps(span, word) for word in words))


def _longest_uncovered_active_span(
    active_spans: Sequence[ParakeetAudioSpan],
    words: Sequence[ParakeetToken],
) -> float:
    uncovered = [
        span.duration_seconds
        for span in active_spans
        if not any(_overlaps(span, word) for word in words)
    ]
    return round(max(uncovered, default=0.0), 3)


def _trailing_active_audio_after_last_word(
    active_spans: Sequence[ParakeetAudioSpan],
    emitted_end: float | None,
) -> float:
    if emitted_end is None:
        return round(sum(span.duration_seconds for span in active_spans), 3)
    trailing = 0.0
    for span in active_spans:
        if span.end_seconds <= emitted_end:
            continue
        trailing += max(0.0, span.end_seconds - max(span.start_seconds, emitted_end))
    return round(trailing, 3)


def _overlaps(span: ParakeetAudioSpan, word: ParakeetToken) -> bool:
    return word.end_sec > span.start_seconds and word.start_sec < span.end_seconds


def _count_repeated_adjacent_words(words: Sequence[ParakeetToken]) -> int:
    repeats = 0
    previous = ""
    for word in words:
        normalized = _normalize_word_for_repeat(word.text)
        if normalized and normalized == previous:
            repeats += 1
        previous = normalized
    return repeats


def _normalize_word_for_repeat(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _coverage_score(
    *,
    active_span_coverage_ratio: float,
    emitted_span_seconds: float,
    active_duration_seconds: float,
    word_density: float,
    char_density: float,
    trailing_active_seconds: float,
    longest_uncovered_span_seconds: float,
    repeated_adjacent_words: int,
) -> float:
    span_ratio = (
        min(1.0, emitted_span_seconds / active_duration_seconds)
        if active_duration_seconds > 0
        else 0.0
    )
    density_score = min(1.0, word_density / 1.8) * 0.5 + min(1.0, char_density / 10.0) * 0.5
    penalty = min(
        0.45,
        trailing_active_seconds * 0.08
        + longest_uncovered_span_seconds * 0.08
        + repeated_adjacent_words * 0.08,
    )
    score = active_span_coverage_ratio * 0.35 + span_ratio * 0.25 + density_score * 0.4 - penalty
    return round(max(0.0, min(1.0, score)), 4)
