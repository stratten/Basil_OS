"""Tests for the per-source live VAD threshold policy.

Validates that the microphone path stays on Silero's strict defaults while
system-audio sources get the lenient, dip-bridging profile. Pure logic, no
model loading.
"""
import pytest

from api.services.whisper_live_core.vad_threshold_policy import (
    vad_params_for_source,
    STRICT_THRESHOLD,
    STRICT_MIN_SILENCE_MS,
    LENIENT_THRESHOLD,
    LENIENT_MIN_SILENCE_MS,
)


@pytest.mark.parametrize(
    "source",
    ["Zoom", "Teams", "Safari", "Google Chrome", "Arc", "zoom.us", "QuickTime Player"],
)
def test_system_audio_sources_get_lenient_profile(source):
    threshold, min_silence_ms = vad_params_for_source(source)
    assert threshold == LENIENT_THRESHOLD
    assert min_silence_ms == LENIENT_MIN_SILENCE_MS
    # The lenient profile must actually be more permissive than strict.
    assert threshold < STRICT_THRESHOLD
    assert min_silence_ms > STRICT_MIN_SILENCE_MS


@pytest.mark.parametrize(
    "source",
    ["Microphone", "microphone", "MICROPHONE", "unknown", "Unknown", "", "   ", None],
)
def test_microphone_and_unknown_stay_strict(source):
    threshold, min_silence_ms = vad_params_for_source(source)
    assert threshold == STRICT_THRESHOLD
    assert min_silence_ms == STRICT_MIN_SILENCE_MS


def test_release_threshold_remains_below_arm_for_lenient():
    # Silero derives the release gate internally as (threshold - 0.15). Guard
    # that the lenient arm threshold keeps a non-negative release band.
    threshold, _ = vad_params_for_source("Zoom")
    assert threshold - 0.15 >= 0.0
