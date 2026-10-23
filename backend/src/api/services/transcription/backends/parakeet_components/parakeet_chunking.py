"""Reusable chunking helpers for long-form Parakeet transcription."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np


WordTuple = Tuple[str, float, float]

PARAKEET_SAMPLE_RATE: int = 16000
PARAKEET_TARGET_CHUNK_SECONDS: float = 30.0
PARAKEET_MAX_CHUNK_SECONDS: float = 40.0
PARAKEET_MIN_CHUNK_SECONDS: float = 18.0
PARAKEET_BOUNDARY_SEARCH_RADIUS_SECONDS: float = 5.0
PARAKEET_ANALYSIS_WINDOW_SECONDS: float = 0.5
PARAKEET_OVERLAP_SECONDS: float = 0.5


@dataclass(frozen=True)
class ParakeetAudioChunk:
    """A decode window plus the timestamp range accepted from that window."""

    index: int
    audio_start_seconds: float
    audio_end_seconds: float
    accept_start_seconds: float
    accept_end_seconds: float
    used_forced_boundary: bool


def build_silence_aware_parakeet_chunks(
    audio: np.ndarray,
    *,
    sample_rate: int = PARAKEET_SAMPLE_RATE,
    target_chunk_seconds: float = PARAKEET_TARGET_CHUNK_SECONDS,
    max_chunk_seconds: float = PARAKEET_MAX_CHUNK_SECONDS,
    min_chunk_seconds: float = PARAKEET_MIN_CHUNK_SECONDS,
    boundary_search_radius_seconds: float = PARAKEET_BOUNDARY_SEARCH_RADIUS_SECONDS,
    analysis_window_seconds: float = PARAKEET_ANALYSIS_WINDOW_SECONDS,
    overlap_seconds: float = PARAKEET_OVERLAP_SECONDS,
) -> List[ParakeetAudioChunk]:
    """Split audio into silence-aware Parakeet decode windows."""

    if audio.size == 0 or sample_rate <= 0:
        return [
            ParakeetAudioChunk(
                index=0,
                audio_start_seconds=0.0,
                audio_end_seconds=0.0,
                accept_start_seconds=0.0,
                accept_end_seconds=0.0,
                used_forced_boundary=False,
            )
        ]

    duration = len(audio) / sample_rate
    rms_centers, rms_values = calculate_parakeet_rms_envelope(
        audio,
        sample_rate=sample_rate,
        analysis_window_seconds=analysis_window_seconds,
    )
    chunks: List[ParakeetAudioChunk] = []
    accept_start = 0.0

    while accept_start < duration:
        remaining = duration - accept_start
        if remaining <= max_chunk_seconds:
            accept_end = duration
            forced = False
        else:
            target = accept_start + target_chunk_seconds
            search_start = max(
                accept_start + min_chunk_seconds,
                target - boundary_search_radius_seconds,
            )
            search_end = min(
                accept_start + max_chunk_seconds,
                target + boundary_search_radius_seconds,
            )
            boundary = find_quiet_parakeet_boundary(
                rms_centers,
                rms_values,
                search_start,
                search_end,
            )
            forced = boundary is None
            accept_end = (
                min(accept_start + target_chunk_seconds, duration)
                if boundary is None
                else boundary
            )

        audio_start = max(
            0.0,
            accept_start - (overlap_seconds if chunks else 0.0),
        )
        audio_end = min(
            duration,
            accept_end + (overlap_seconds if accept_end < duration else 0.0),
        )
        chunks.append(
            ParakeetAudioChunk(
                index=len(chunks),
                audio_start_seconds=audio_start,
                audio_end_seconds=audio_end,
                accept_start_seconds=accept_start,
                accept_end_seconds=accept_end,
                used_forced_boundary=forced,
            )
        )
        accept_start = accept_end

    return chunks


def calculate_parakeet_rms_envelope(
    audio: np.ndarray,
    *,
    sample_rate: int,
    analysis_window_seconds: float = PARAKEET_ANALYSIS_WINDOW_SECONDS,
) -> Tuple[np.ndarray, np.ndarray]:
    """Calculate RMS values and center timestamps for overlapping windows."""

    window_samples = max(1, _seconds_to_sample(analysis_window_seconds, sample_rate))
    hop_samples = max(1, window_samples // 2)
    centers: List[float] = []
    values: List[float] = []

    for start in range(0, len(audio), hop_samples):
        end = min(start + window_samples, len(audio))
        if end <= start:
            break
        window = audio[start:end].astype(np.float32, copy=False)
        rms = float(np.sqrt(np.mean(window * window))) if window.size else 0.0
        centers.append(((start + end) / 2) / sample_rate)
        values.append(rms)
        if end == len(audio):
            break

    return np.asarray(centers), np.asarray(values)


def find_quiet_parakeet_boundary(
    centers: np.ndarray,
    values: np.ndarray,
    search_start: float,
    search_end: float,
) -> float | None:
    """Return the quietest RMS center inside a candidate boundary window."""

    mask = (centers >= search_start) & (centers <= search_end)
    if not np.any(mask):
        return None
    candidate_centers = centers[mask]
    candidate_values = values[mask]
    if candidate_values.size == 0:
        return None
    quiet_index = int(np.argmin(candidate_values))
    return float(candidate_centers[quiet_index])


def offset_and_filter_parakeet_words(
    chunk: ParakeetAudioChunk,
    local_words: List[WordTuple],
    *,
    audio_duration_seconds: float,
) -> List[WordTuple]:
    """Offset local chunk words and keep only words in the accepted range."""

    accepted: List[WordTuple] = []
    for text, start, end in local_words:
        global_start = chunk.audio_start_seconds + start
        global_end = chunk.audio_start_seconds + end
        if global_end <= chunk.accept_start_seconds:
            continue
        if (
            global_start >= chunk.accept_end_seconds
            and chunk.accept_end_seconds < audio_duration_seconds
        ):
            continue
        accepted.append((text, global_start, global_end))
    return accepted


def deduplicate_parakeet_boundary_words(
    existing_words: List[WordTuple],
    new_words: List[WordTuple],
) -> List[WordTuple]:
    """Remove repeated words caused by overlapping chunk boundaries."""

    if not existing_words:
        return new_words

    deduplicated: List[WordTuple] = []
    recent_words = existing_words[-8:]
    for word in new_words:
        text, start, end = word
        normalized = text.strip().lower()
        is_duplicate = any(
            normalized == previous_text.strip().lower()
            and abs(start - previous_start) < 0.9
            and abs(end - previous_end) < 0.9
            for previous_text, previous_start, previous_end in recent_words
        )
        if not is_duplicate:
            deduplicated.append(word)
    return deduplicated


def parakeet_word_tuples_to_text(word_tuples: List[WordTuple]) -> str:
    """Join Parakeet word tuples into transcript text."""

    return _join_segment_words(
        [(text or "").strip() for text, _, _ in word_tuples if (text or "").strip()]
    )


def parakeet_word_tuples_to_segments(
    word_tuples: List[WordTuple],
    *,
    max_gap_seconds: float = 0.8,
    max_segment_seconds: float = 12.0,
) -> List[Dict[str, Any]]:
    """Group word-level timestamp triples into readable transcript segments."""

    segments: List[Dict[str, Any]] = []
    current_words: List[str] = []
    current_start: float | None = None
    current_end: float | None = None

    for text, start, end in word_tuples:
        word = (text or "").strip()
        if not word:
            continue

        should_start_new = current_start is None
        if current_end is not None:
            gap = start - current_end
            duration = end - current_start if current_start is not None else 0.0
            should_start_new = gap > max_gap_seconds or duration > max_segment_seconds

        if should_start_new:
            if current_words and current_start is not None and current_end is not None:
                segments.append(
                    {
                        "start": current_start,
                        "end": current_end,
                        "text": _join_segment_words(current_words),
                    }
                )
            current_words = [word]
            current_start = start
            current_end = end
        else:
            current_words.append(word)
            current_end = end

        if word[-1:] in {".", "?", "!"}:
            if current_words and current_start is not None and current_end is not None:
                segments.append(
                    {
                        "start": current_start,
                        "end": current_end,
                        "text": _join_segment_words(current_words),
                    }
                )
            current_words = []
            current_start = None
            current_end = None

    if current_words and current_start is not None and current_end is not None:
        segments.append(
            {
                "start": current_start,
                "end": current_end,
                "text": _join_segment_words(current_words),
            }
        )

    return segments


def _seconds_to_sample(seconds: float, sample_rate: int) -> int:
    return int(round(seconds * sample_rate))


def _join_segment_words(words: List[str]) -> str:
    text = " ".join(words)
    for punctuation in [".", ",", "?", "!", ":", ";"]:
        text = text.replace(f" {punctuation}", punctuation)
    return text.strip()
