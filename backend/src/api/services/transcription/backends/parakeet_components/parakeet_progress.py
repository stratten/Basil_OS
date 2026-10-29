"""Progress payloads for Parakeet transcription orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict


PARAKEET_PROGRESS_CALLBACK_CONTEXT_KEY = "_parakeet_progress_callback"


@dataclass(frozen=True)
class ParakeetTranscriptionProgress:
    """Structured progress update for long-form Parakeet transcription."""

    strategy: str
    stage_progress: float
    current_time_seconds: float
    audio_duration_seconds: float
    message: str
    eta_seconds: float
    chunk_index: int
    chunk_count: int

    def to_payload(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "stage_progress": self.stage_progress,
            "current_time_seconds": self.current_time_seconds,
            "audio_duration_seconds": self.audio_duration_seconds,
            "message": self.message,
            "eta_seconds": self.eta_seconds,
            "chunk_index": self.chunk_index,
            "chunk_count": self.chunk_count,
        }


ParakeetProgressCallback = Callable[[ParakeetTranscriptionProgress], None]
