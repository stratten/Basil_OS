"""Audio diagnostics for Parakeet transcription inputs."""

from __future__ import annotations

import logging
from typing import List

import numpy as np


PARAKEET_DIAGNOSTIC_WINDOW_SECONDS: float = 0.25


def log_parakeet_audio_coverage_diagnostics(
    audio: np.ndarray,
    *,
    sample_rate: int,
    source: str,
    logger: logging.Logger,
) -> None:
    """Log coarse audio coverage so sparse Parakeet output can be traced."""

    if audio.size == 0 or sample_rate <= 0:
        logger.info("Parakeet audio diagnostics skipped for empty source=%s", source)
        return

    audio_f32 = audio.astype(np.float32, copy=False)
    abs_audio = np.abs(audio_f32)
    duration_seconds = audio_f32.size / sample_rate
    rms = float(np.sqrt(np.mean(audio_f32 * audio_f32)))
    peak = float(np.max(abs_audio)) if abs_audio.size else 0.0
    window_samples = max(1, int(round(PARAKEET_DIAGNOSTIC_WINDOW_SECONDS * sample_rate)))
    window_rms_values: List[float] = []
    for start in range(0, audio_f32.size, window_samples):
        window = audio_f32[start : start + window_samples]
        if window.size == 0:
            continue
        window_rms_values.append(float(np.sqrt(np.mean(window * window))))

    if window_rms_values:
        window_threshold = max(1e-4, rms * 0.15, peak * 0.01)
        active_windows = sum(value >= window_threshold for value in window_rms_values)
        active_ratio = active_windows / len(window_rms_values)
        max_silent_run = _max_run_below_threshold(
            window_rms_values,
            window_threshold,
        )
    else:
        window_threshold = 0.0
        active_windows = 0
        active_ratio = 0.0
        max_silent_run = 0

    logger.info(
        "Parakeet audio diagnostics: source=%s sr=%s samples=%s duration=%.2fs "
        "rms=%.6f peak=%.6f windows=%s active_windows=%s active_ratio=%.3f "
        "threshold=%.6f max_silent_run=%.2fs",
        source,
        sample_rate,
        audio_f32.size,
        duration_seconds,
        rms,
        peak,
        len(window_rms_values),
        active_windows,
        active_ratio,
        window_threshold,
        max_silent_run * PARAKEET_DIAGNOSTIC_WINDOW_SECONDS,
    )


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
