"""Measured audio conditioning strategies for adaptive Parakeet runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .parakeet_coverage import ParakeetAudioCoverage, ParakeetAudioSpan


DEFAULT_TARGET_RMS: float = 0.05


@dataclass(frozen=True)
class ParakeetConditioningResult:
    strategy: str
    audio: np.ndarray
    gain: float
    rms_before: float
    rms_after: float
    peak_before: float
    peak_after: float
    clipped_samples: int
    dither_amplitude: float = 0.0


def apply_whole_file_rms_conditioning(
    audio: np.ndarray,
    *,
    target_rms: float = DEFAULT_TARGET_RMS,
) -> ParakeetConditioningResult:
    return _apply_gain(
        audio,
        strategy="baseline_rms",
        gain=_gain_for_rms(_rms(audio), target_rms=target_rms),
    )


def apply_speech_window_rms_conditioning(
    audio: np.ndarray,
    audio_coverage: ParakeetAudioCoverage,
    *,
    target_rms: float = DEFAULT_TARGET_RMS,
    max_gain: float = 4.0,
) -> ParakeetConditioningResult:
    active_audio = _active_audio_samples(
        audio,
        audio_coverage.active_spans,
        sample_rate=audio_coverage.sample_rate,
    )
    active_rms = _rms(active_audio) if active_audio.size else _rms(audio)
    gain = min(max_gain, _gain_for_rms(active_rms, target_rms=target_rms))
    return _apply_gain(audio, strategy="speech_rms_conditioned", gain=gain)


def apply_mild_peak_limited_gain(
    audio: np.ndarray,
    audio_coverage: ParakeetAudioCoverage,
    *,
    low_active_rms_threshold: float = 0.035,
    max_gain: float = 2.5,
) -> ParakeetConditioningResult:
    active_audio = _active_audio_samples(
        audio,
        audio_coverage.active_spans,
        sample_rate=audio_coverage.sample_rate,
    )
    active_rms = _rms(active_audio) if active_audio.size else _rms(audio)
    if active_rms >= low_active_rms_threshold:
        gain = 1.0
    else:
        gain = min(max_gain, low_active_rms_threshold / max(active_rms, 1e-8))
    return _apply_gain(audio, strategy="mild_peak_limited_gain", gain=gain)


def apply_small_dither_conditioning(
    audio: np.ndarray,
    *,
    dither_amplitude: float = 3.0e-5,
) -> ParakeetConditioningResult:
    audio_f32 = audio.astype(np.float32, copy=False)
    rng = np.random.default_rng(seed=0)
    noise = rng.normal(0.0, dither_amplitude, size=audio_f32.shape).astype(np.float32)
    conditioned = np.clip(audio_f32 + noise, -1.0, 1.0).astype(np.float32, copy=False)
    clipped_samples = int(np.sum(np.abs(audio_f32 + noise) > 1.0))
    return ParakeetConditioningResult(
        strategy="small_dither_conditioned",
        audio=conditioned,
        gain=1.0,
        rms_before=round(_rms(audio_f32), 8),
        rms_after=round(_rms(conditioned), 8),
        peak_before=round(_peak(audio_f32), 8),
        peak_after=round(_peak(conditioned), 8),
        clipped_samples=clipped_samples,
        dither_amplitude=dither_amplitude,
    )


def _apply_gain(
    audio: np.ndarray,
    *,
    strategy: str,
    gain: float,
) -> ParakeetConditioningResult:
    audio_f32 = audio.astype(np.float32, copy=False)
    scaled = audio_f32 * float(gain)
    clipped_samples = int(np.sum(np.abs(scaled) > 1.0))
    conditioned = np.clip(scaled, -1.0, 1.0).astype(np.float32, copy=False)
    return ParakeetConditioningResult(
        strategy=strategy,
        audio=conditioned,
        gain=round(float(gain), 6),
        rms_before=round(_rms(audio_f32), 8),
        rms_after=round(_rms(conditioned), 8),
        peak_before=round(_peak(audio_f32), 8),
        peak_after=round(_peak(conditioned), 8),
        clipped_samples=clipped_samples,
    )


def _active_audio_samples(
    audio: np.ndarray,
    active_spans: Sequence[ParakeetAudioSpan],
    *,
    sample_rate: int,
) -> np.ndarray:
    slices = []
    for span in active_spans:
        start = max(0, int(round(span.start_seconds * sample_rate)))
        end = min(audio.size, int(round(span.end_seconds * sample_rate)))
        if end > start:
            slices.append(audio[start:end])
    if not slices:
        return np.asarray([], dtype=np.float32)
    return np.concatenate(slices).astype(np.float32, copy=False)


def _gain_for_rms(current_rms: float, *, target_rms: float) -> float:
    if current_rms < 1e-8:
        return 1.0
    return float(target_rms / current_rms)


def _rms(audio: np.ndarray) -> float:
    audio_f32 = audio.astype(np.float32, copy=False)
    if audio_f32.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio_f32 * audio_f32)))


def _peak(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.max(np.abs(audio)))
