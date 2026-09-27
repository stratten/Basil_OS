"""Audio coverage metrics for Parakeet failure-mode diagnostics."""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import librosa
import numpy as np

from .models import AudioCoverageMetrics, AudioSpan


TARGET_SAMPLE_RATE = 16000
COVERAGE_WINDOW_SECONDS = 0.25


def load_mono_audio(audio_path: Path) -> Tuple[np.ndarray, int]:
    audio, sample_rate = librosa.load(
        str(audio_path),
        sr=TARGET_SAMPLE_RATE,
        mono=True,
    )
    return audio.astype(np.float32, copy=False), int(sample_rate)


def analyze_audio_coverage(audio_path: Path) -> AudioCoverageMetrics:
    audio, sample_rate = load_mono_audio(audio_path)
    if audio.size == 0:
        return AudioCoverageMetrics(
            path=str(audio_path),
            sample_rate=sample_rate,
            samples=0,
            duration_seconds=0.0,
            rms=0.0,
            peak=0.0,
            coverage_window_seconds=COVERAGE_WINDOW_SECONDS,
            coverage_threshold=0.0,
            active_windows=0,
            total_windows=0,
            active_window_ratio=0.0,
            max_silent_run_seconds=0.0,
            active_spans=[],
        )

    rms = float(np.sqrt(np.mean(audio * audio)))
    peak = float(np.max(np.abs(audio)))
    window_rms_values = _window_rms_values(audio, sample_rate)
    threshold = max(1e-4, rms * 0.15, peak * 0.01)
    active_flags = [value >= threshold for value in window_rms_values]
    active_windows = sum(active_flags)

    return AudioCoverageMetrics(
        path=str(audio_path),
        sample_rate=sample_rate,
        samples=int(audio.size),
        duration_seconds=round(audio.size / sample_rate, 3),
        rms=round(rms, 8),
        peak=round(peak, 8),
        coverage_window_seconds=COVERAGE_WINDOW_SECONDS,
        coverage_threshold=round(threshold, 8),
        active_windows=active_windows,
        total_windows=len(window_rms_values),
        active_window_ratio=round(
            active_windows / len(window_rms_values) if window_rms_values else 0.0,
            4,
        ),
        max_silent_run_seconds=round(
            _max_run_below_threshold(window_rms_values, threshold)
            * COVERAGE_WINDOW_SECONDS,
            3,
        ),
        active_spans=_active_spans(active_flags),
    )


def _window_rms_values(audio: np.ndarray, sample_rate: int) -> List[float]:
    window_samples = max(1, int(round(COVERAGE_WINDOW_SECONDS * sample_rate)))
    values: List[float] = []
    for start in range(0, audio.size, window_samples):
        window = audio[start : start + window_samples]
        if window.size:
            values.append(float(np.sqrt(np.mean(window * window))))
    return values


def _max_run_below_threshold(values: List[float], threshold: float) -> int:
    longest = 0
    current = 0
    for value in values:
        if value < threshold:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _active_spans(active_flags: List[bool]) -> List[AudioSpan]:
    spans: List[AudioSpan] = []
    active_start: int | None = None
    for index, active in enumerate(active_flags):
        if active and active_start is None:
            active_start = index
        elif not active and active_start is not None:
            spans.append(_span_from_window_indices(active_start, index))
            active_start = None
    if active_start is not None:
        spans.append(_span_from_window_indices(active_start, len(active_flags)))
    return spans


def _span_from_window_indices(start_index: int, end_index: int) -> AudioSpan:
    return AudioSpan(
        start_seconds=round(start_index * COVERAGE_WINDOW_SECONDS, 3),
        end_seconds=round(end_index * COVERAGE_WINDOW_SECONDS, 3),
    )
