"""Decides when the person has finished speaking during a wake word capture.

The decision is made on the audio timeline, never on the wall clock. Every frame that arrives advances the clock by its own duration, so a stalled event loop, a slow speech-to-text pass, or audio that arrives in bursts cannot make a short pause look like a long one. Whether a frame contains speech comes from the Silero voice activity model, with an adaptive energy detector as the fallback when the model cannot be loaded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Protocol

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE


class SpeechProbability(Protocol):
    """Scores one 512-sample, 16 kHz, mono float frame between 0.0 (not speech) and 1.0 (speech)."""

    def __call__(self, frame: np.ndarray) -> float: ...

    def reset(self) -> None: ...


class SileroSpeechProbability:
    """Speech probability from the bundled Silero voice activity model."""

    def __init__(self) -> None:
        from ..whisper_live_core.silero_vad_iterator import load_silero_vad

        self._model = load_silero_vad(onnx=True)
        self._model.reset_states()

    def __call__(self, frame: np.ndarray) -> float:
        return float(np.asarray(self._model(frame, SAMPLE_RATE)).item())

    def reset(self) -> None:
        self._model.reset_states()


class EnergySpeechProbability:
    """Fallback detector that follows the room's noise floor instead of using a fixed level.

    The floor rises slowly and falls quickly, so steady background noise is learned and ignored while speech, which sits well above it, still registers. A fixed absolute minimum keeps digital silence from counting as speech.
    """

    def __init__(self, *, floor_ratio: float = 3.0, absolute_minimum: float = 0.006) -> None:
        self._floor_ratio = floor_ratio
        self._absolute_minimum = absolute_minimum
        self._noise_floor: Optional[float] = None

    def __call__(self, frame: np.ndarray) -> float:
        level = float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))
        if self._noise_floor is None:
            self._noise_floor = level
        elif level < self._noise_floor:
            self._noise_floor += (level - self._noise_floor) * 0.5
        else:
            self._noise_floor += (level - self._noise_floor) * 0.002
        is_speech = level > max(self._absolute_minimum, self._noise_floor * self._floor_ratio)
        return 1.0 if is_speech else 0.0

    def reset(self) -> None:
        self._noise_floor = None


def create_speech_probability() -> SpeechProbability:
    """Return the Silero detector, or the energy detector when Silero is unavailable."""
    try:
        return SileroSpeechProbability()
    except Exception as error:
        logger.warning("Silero voice activity model unavailable for capture endpointing, using the energy detector: %s", error)
        return EnergySpeechProbability()


# How long a wake word request may stay silent after you speak before it is submitted. The countdown ring in web-components/AgentTaskCaptureInput (SILENCE_COUNTDOWN_SECONDS in VoiceCaptureView.tsx) draws against the same number, so change them together.
WAKE_WORD_SILENCE_SECONDS = 2.5


@dataclass(frozen=True)
class EndpointSettings:
    """How a capture decides it is over."""

    silence_seconds: float = WAKE_WORD_SILENCE_SECONDS
    no_speech_seconds: float = 8.0
    min_speech_seconds: float = 0.3
    speech_start_probability: float = 0.5
    speech_end_probability: float = 0.35


class CaptureEndpointTracker:
    """Follows speech and silence across a capture and reports how long the speaker has been quiet."""

    def __init__(self, probability: SpeechProbability, settings: Optional[EndpointSettings] = None) -> None:
        self._probability = probability
        self._settings = settings or EndpointSettings()
        self._pending = np.zeros(0, dtype=np.float32)
        self._frames = 0
        self._speech_frames = 0
        self._last_speech_frame = 0
        self._in_speech = False

    @property
    def settings(self) -> EndpointSettings:
        return self._settings

    @property
    def audio_seconds(self) -> float:
        return self._frames * FRAME_SECONDS

    @property
    def heard_speech(self) -> bool:
        return self._speech_frames * FRAME_SECONDS >= self._settings.min_speech_seconds

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    @property
    def trailing_silence_seconds(self) -> float:
        """Seconds of audio since speech last ended, or zero while speaking or before any speech."""
        if not self.heard_speech or self._in_speech:
            return 0.0
        return (self._frames - self._last_speech_frame) * FRAME_SECONDS

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self._settings.silence_seconds - self.trailing_silence_seconds)

    @property
    def speech_has_ended(self) -> bool:
        return self.heard_speech and self.trailing_silence_seconds >= self._settings.silence_seconds

    @property
    def no_speech_timed_out(self) -> bool:
        return not self.heard_speech and self.audio_seconds >= self._settings.no_speech_seconds

    def feed(self, audio: np.ndarray) -> None:
        """Advance the audio clock by this audio. Partial frames wait for the rest of their samples."""
        if audio.size == 0:
            return
        self._pending = np.concatenate([self._pending, audio.astype(np.float32, copy=False)])
        while self._pending.size >= FRAME_SAMPLES:
            frame = self._pending[:FRAME_SAMPLES]
            self._pending = self._pending[FRAME_SAMPLES:]
            self._advance(self._probability(frame))

    def _advance(self, probability: float) -> None:
        self._frames += 1
        threshold = self._settings.speech_end_probability if self._in_speech else self._settings.speech_start_probability
        self._in_speech = probability >= threshold
        if self._in_speech:
            self._speech_frames += 1
            self._last_speech_frame = self._frames
