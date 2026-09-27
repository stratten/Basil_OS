"""Request policy helpers for OpenAI transcription calls."""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from typing import Optional, Sequence

import httpx

CONNECT_TIMEOUT_SECONDS = 5.0
WRITE_TIMEOUT_SECONDS = 15.0
POOL_TIMEOUT_SECONDS = 5.0

FIRST_ATTEMPT_DURATION_FACTOR = 0.10
FIRST_ATTEMPT_MIN_READ_SECONDS = 6.0
FIRST_ATTEMPT_MAX_READ_SECONDS = 18.0

SECOND_ATTEMPT_DURATION_FACTOR = 0.20
SECOND_ATTEMPT_MIN_READ_SECONDS = 10.0
SECOND_ATTEMPT_MAX_READ_SECONDS = 45.0

UNKNOWN_DURATION_FIRST_READ_SECONDS = 12.0
UNKNOWN_DURATION_SECOND_READ_SECONDS = 30.0

RETRYABLE_STATUS_CODES = {408, 409, 429}

CONNECTION_ERROR_USER_MESSAGE = (
    "Couldn't reach the transcription service - this looks like a network or "
    "internet connection problem. Your audio was saved and can be retried from "
    "Transcription History once you're back online."
)


@dataclass(frozen=True)
class TranscriptionAttemptPolicy:
    """Timeout policy for one OpenAI transcription attempt."""

    attempt_number: int
    max_attempts: int
    audio_duration_seconds: Optional[float]
    read_timeout_seconds: float
    connect_timeout_seconds: float = CONNECT_TIMEOUT_SECONDS
    write_timeout_seconds: float = WRITE_TIMEOUT_SECONDS
    pool_timeout_seconds: float = POOL_TIMEOUT_SECONDS

    def to_httpx_timeout(self) -> httpx.Timeout:
        """Build the granular timeout object accepted by the OpenAI SDK."""
        return httpx.Timeout(
            connect=self.connect_timeout_seconds,
            read=self.read_timeout_seconds,
            write=self.write_timeout_seconds,
            pool=self.pool_timeout_seconds,
        )


def estimate_wav_duration_seconds(audio_bytes: bytes) -> Optional[float]:
    """Return WAV duration in seconds, or None when bytes are not readable WAV."""
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as reader:
            frame_rate = reader.getframerate()
            if frame_rate <= 0:
                return None
            return reader.getnframes() / float(frame_rate)
    except (EOFError, wave.Error):
        return None


def build_transcription_attempt_policies(
    *,
    audio_duration_seconds: Optional[float],
) -> Sequence[TranscriptionAttemptPolicy]:
    """Build the two-attempt Basil-owned retry policy for API dictation."""
    normalized_duration = (
        audio_duration_seconds
        if audio_duration_seconds is not None and audio_duration_seconds > 0
        else None
    )

    if normalized_duration is None:
        read_timeouts = [
            UNKNOWN_DURATION_FIRST_READ_SECONDS,
            UNKNOWN_DURATION_SECOND_READ_SECONDS,
        ]
    else:
        read_timeouts = [
            _clamp(
                normalized_duration * FIRST_ATTEMPT_DURATION_FACTOR,
                FIRST_ATTEMPT_MIN_READ_SECONDS,
                FIRST_ATTEMPT_MAX_READ_SECONDS,
            ),
            _clamp(
                normalized_duration * SECOND_ATTEMPT_DURATION_FACTOR,
                SECOND_ATTEMPT_MIN_READ_SECONDS,
                SECOND_ATTEMPT_MAX_READ_SECONDS,
            ),
        ]

    max_attempts = len(read_timeouts)
    return tuple(
        TranscriptionAttemptPolicy(
            attempt_number=index,
            max_attempts=max_attempts,
            audio_duration_seconds=normalized_duration,
            read_timeout_seconds=read_timeout,
        )
        for index, read_timeout in enumerate(read_timeouts, start=1)
    )


def should_retry_transcription_error(exc: BaseException) -> bool:
    """Return True when a failed OpenAI transcription attempt may be retried."""
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code in RETRYABLE_STATUS_CODES or 500 <= status_code <= 599

    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError, httpx.ProtocolError)):
        return True

    error_type_name = type(exc).__name__
    return error_type_name in {
        "APITimeoutError",
        "APIConnectionError",
    }


def is_connection_error(exc: BaseException) -> bool:
    """Return True when a failure was a network/connection problem (not a timeout).

    Timeouts are intentionally excluded: the caller owns a separate, more specific
    timeout message. This covers httpx transport-level connection failures and the
    OpenAI SDK's APIConnectionError (e.g., DNS failure / offline).
    """
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        return True

    error_type_name = type(exc).__name__
    if error_type_name == "APITimeoutError":
        return False
    return error_type_name == "APIConnectionError"


def _clamp(value: float, lower_bound: float, upper_bound: float) -> float:
    return min(max(value, lower_bound), upper_bound)
