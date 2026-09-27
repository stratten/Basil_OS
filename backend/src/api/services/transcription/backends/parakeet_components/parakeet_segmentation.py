"""Segmentation helpers for adaptive Parakeet transcription."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, List, Sequence

import numpy as np

from .parakeet_coverage import ParakeetAudioCoverage, ParakeetAudioSpan
from .parakeet_decoder import ParakeetToken


@dataclass(frozen=True)
class ParakeetSegmentWindow:
    original_start_seconds: float
    original_end_seconds: float
    padded_start_seconds: float
    padded_end_seconds: float

    @property
    def inner_start_seconds(self) -> float:
        return round(self.original_start_seconds - self.padded_start_seconds, 3)

    @property
    def inner_end_seconds(self) -> float:
        return round(self.original_end_seconds - self.padded_start_seconds, 3)

    @property
    def duration_seconds(self) -> float:
        return round(self.padded_end_seconds - self.padded_start_seconds, 3)


def build_active_span_windows(
    audio_coverage: ParakeetAudioCoverage,
    *,
    left_context_seconds: float = 1.0,
    right_context_seconds: float = 1.0,
    merge_gap_seconds: float = 0.35,
    minimum_span_seconds: float = 0.4,
) -> List[ParakeetSegmentWindow]:
    merged_spans = _merge_close_spans(
        audio_coverage.active_spans,
        merge_gap_seconds=merge_gap_seconds,
    )
    windows: List[ParakeetSegmentWindow] = []
    for span in merged_spans:
        if span.duration_seconds < minimum_span_seconds:
            continue
        windows.append(
            _window_with_context(
                span,
                duration_seconds=audio_coverage.duration_seconds,
                left_context_seconds=left_context_seconds,
                right_context_seconds=right_context_seconds,
            )
        )
    return windows


def build_overlap_windows(
    duration_seconds: float,
    *,
    chunk_seconds: float = 6.0,
    left_context_seconds: float = 1.5,
    right_context_seconds: float = 1.0,
    stride_seconds: float = 4.0,
) -> List[ParakeetSegmentWindow]:
    if duration_seconds <= 0:
        return []
    windows: List[ParakeetSegmentWindow] = []
    start = 0.0
    while start < duration_seconds:
        end = min(duration_seconds, start + chunk_seconds)
        target = ParakeetAudioSpan(
            start_seconds=round(start, 3),
            end_seconds=round(end, 3),
        )
        windows.append(
            _window_with_context(
                target,
                duration_seconds=duration_seconds,
                left_context_seconds=left_context_seconds,
                right_context_seconds=right_context_seconds,
            )
        )
        if end >= duration_seconds:
            break
        start += stride_seconds
    return _dedupe_windows(windows)


def slice_audio_for_window(
    audio: np.ndarray,
    window: ParakeetSegmentWindow,
    *,
    sample_rate: int,
) -> np.ndarray:
    start_sample = max(0, int(round(window.padded_start_seconds * sample_rate)))
    end_sample = min(audio.size, int(round(window.padded_end_seconds * sample_rate)))
    return audio[start_sample:end_sample].astype(np.float32, copy=False)


def offset_words_from_window(
    words: Sequence[ParakeetToken],
    window: ParakeetSegmentWindow,
) -> List[ParakeetToken]:
    kept: List[ParakeetToken] = []
    for word in words:
        midpoint = (word.start_sec + word.end_sec) / 2.0
        if midpoint < window.inner_start_seconds or midpoint > window.inner_end_seconds:
            continue
        kept.append(
            ParakeetToken(
                text=word.text,
                start_sec=round(word.start_sec + window.padded_start_seconds, 3),
                end_sec=round(word.end_sec + window.padded_start_seconds, 3),
            )
        )
    return kept


def merge_segment_words(
    word_groups: Iterable[Sequence[ParakeetToken]],
    *,
    duplicate_window_seconds: float = 0.32,
) -> List[ParakeetToken]:
    merged: List[ParakeetToken] = []
    for group in word_groups:
        for word in group:
            if _is_duplicate_tail_word(
                merged,
                word,
                duplicate_window_seconds=duplicate_window_seconds,
            ):
                continue
            merged.append(word)
    return sorted(merged, key=lambda item: (item.start_sec, item.end_sec, item.text))


def words_to_text(words: Sequence[ParakeetToken]) -> str:
    return " ".join(word.text.strip() for word in words if word.text.strip()).strip()


def _merge_close_spans(
    spans: Sequence[ParakeetAudioSpan],
    *,
    merge_gap_seconds: float,
) -> List[ParakeetAudioSpan]:
    if not spans:
        return []
    ordered = sorted(spans, key=lambda span: span.start_seconds)
    merged: List[ParakeetAudioSpan] = [ordered[0]]
    for span in ordered[1:]:
        previous = merged[-1]
        if span.start_seconds - previous.end_seconds <= merge_gap_seconds:
            merged[-1] = ParakeetAudioSpan(
                start_seconds=previous.start_seconds,
                end_seconds=max(previous.end_seconds, span.end_seconds),
            )
        else:
            merged.append(span)
    return merged


def _window_with_context(
    span: ParakeetAudioSpan,
    *,
    duration_seconds: float,
    left_context_seconds: float,
    right_context_seconds: float,
) -> ParakeetSegmentWindow:
    return ParakeetSegmentWindow(
        original_start_seconds=round(span.start_seconds, 3),
        original_end_seconds=round(span.end_seconds, 3),
        padded_start_seconds=round(max(0.0, span.start_seconds - left_context_seconds), 3),
        padded_end_seconds=round(
            min(duration_seconds, span.end_seconds + right_context_seconds),
            3,
        ),
    )


def _dedupe_windows(
    windows: Sequence[ParakeetSegmentWindow],
) -> List[ParakeetSegmentWindow]:
    seen: set[tuple[float, float, float, float]] = set()
    unique: List[ParakeetSegmentWindow] = []
    for window in windows:
        key = (
            window.original_start_seconds,
            window.original_end_seconds,
            window.padded_start_seconds,
            window.padded_end_seconds,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(window)
    return unique


def _is_duplicate_tail_word(
    merged: Sequence[ParakeetToken],
    word: ParakeetToken,
    *,
    duplicate_window_seconds: float,
) -> bool:
    normalized = _normalize_word_for_repeat(word.text)
    if not normalized:
        return True
    for previous in reversed(merged[-5:]):
        if _normalize_word_for_repeat(previous.text) != normalized:
            continue
        if abs(previous.start_sec - word.start_sec) <= duplicate_window_seconds:
            return True
    return False


def _normalize_word_for_repeat(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())
