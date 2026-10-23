"""Per-source Silero VAD parameter policy for live transcription.

The live transcription gate is the Silero neural VAD, which scores *speech
likelihood* (not loudness). Microphone audio is clean, close-talking speech
that reliably scores above Silero's default 0.5 threshold. Produced/system
audio (meeting apps, browser/video playback) scores lower on speech-likelihood
even when clearly audible, so the strict default was silently dropping valid
passages from the live transcript (they only resurfaced via retranscription of
the full recording).

This module chooses a more lenient, dip-bridging VAD profile for non-microphone
(system-audio) streams while leaving the microphone path on the strict default.

It is a pure function with no model/torch imports so the decision is
unit-testable without loading anything.
"""
from __future__ import annotations

from typing import Optional, Tuple

# Microphone stream identifier sent by the client
# (LiveTranscriptionViewModel+WebSocket.swift sets audio_source="Microphone").
# "unknown" is the AudioProcessor fallback when no source is provided. Both, and
# an empty source, are treated as strict so we never relax the microphone path.
STRICT_SOURCES = frozenset({"microphone", "unknown"})

# Strict profile = Silero library defaults = the unchanged microphone behavior.
STRICT_THRESHOLD = 0.5
STRICT_MIN_SILENCE_MS = 100

# Lenient profile for system-audio streams. Lowering the speech-probability gate
# (release follows internally as threshold - 0.15) re-arms speech sooner, and a
# longer required sub-threshold span keeps a momentary dip in produced audio from
# latching into a multi-second dropout.
LENIENT_THRESHOLD = 0.3
LENIENT_MIN_SILENCE_MS = 300


def vad_params_for_source(source: Optional[str]) -> Tuple[float, int]:
    """Return ``(threshold, min_silence_ms)`` for the given audio source name.

    Microphone, ``"unknown"``, and empty/``None`` sources use the strict
    defaults; any other named source (system audio, e.g. ``"Zoom"``,
    ``"Teams"``, a browser name) uses the lenient profile.
    """
    normalized = (source or "").strip()
    if not normalized or normalized.lower() in STRICT_SOURCES:
        return (STRICT_THRESHOLD, STRICT_MIN_SILENCE_MS)
    return (LENIENT_THRESHOLD, LENIENT_MIN_SILENCE_MS)
