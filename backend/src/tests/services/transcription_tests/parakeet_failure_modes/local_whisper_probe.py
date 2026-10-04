"""Local Whisper probe for Parakeet failure-mode diagnostics."""

from __future__ import annotations

from pathlib import Path
from time import monotonic
from typing import Any

from .audio_coverage import analyze_audio_coverage
from .models import BackendRunResult, build_backend_result


DEFAULT_WHISPER_MODEL = "Whisper Large V3 Turbo"


async def run_local_whisper_probe(
    audio_path: Path,
    *,
    model_name: str = DEFAULT_WHISPER_MODEL,
) -> BackendRunResult:
    from api.services.whisper_live_core.post_processing.transcription_processor import (
        TranscriptionProcessor,
    )

    started_at = monotonic()

    async def progress_callback(*_args: Any) -> None:
        return None

    try:
        audio_metrics = analyze_audio_coverage(audio_path)
        processor = TranscriptionProcessor(
            audio_path=audio_path,
            audio_duration=audio_metrics.duration_seconds,
            model_name=model_name,
        )
        segments = await processor.transcribe_with_selected_model(progress_callback)
        text = " ".join(str(segment.get("text", "")).strip() for segment in segments)
        return build_backend_result(
            backend="local_whisper",
            model_id=model_name,
            success=True,
            wall_seconds=monotonic() - started_at,
            text=text,
        )
    except Exception as exc:
        return build_backend_result(
            backend="local_whisper",
            model_id=model_name,
            success=False,
            wall_seconds=monotonic() - started_at,
            error=f"{type(exc).__name__}: {exc}",
        )
