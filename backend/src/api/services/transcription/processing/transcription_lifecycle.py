"""Transcription lifecycle helper.

Centralizes the "save audio first, then create a row, then mark the row
complete or failed" state machine that both the local (HuggingFace) and
cloud (OpenAI Whisper API) transcription services share. Without this
helper the two services diverge: the local path historically persisted
audio before the model but only wrote a DB row on success, and the cloud
path persisted nothing at all on failure. In both cases a failed
transcription destroyed the user's audio with no way to retry.

The public surface is three coroutine entry points:

  * ``begin(audio_data, context_info, model_name, ...)`` -- persists the
    audio to disk (or reuses an existing path on retranscription) and,
    when the context is eligible for history, inserts a ``pending`` row
    with empty text. Always returns a :class:`TranscriptionStub` with a
    valid ``audio_path``; the stub's ``id`` is ``None`` when history was
    deliberately skipped (AssistantSession suggestions, flow context) so the caller
    can still call ``complete`` / ``fail`` unconditionally.
  * ``complete(stub, text, processing_time_ms, model_name=None)`` --
    flips the row to ``completed`` with the final text (no-op when no
    row was created).
  * ``fail(stub, error_message, processing_time_ms, model_name=None)`` --
    flips the row to ``failed`` with a human-readable error (no-op when
    no row was created).

Every DB call is wrapped in its own try/except so a persistence failure
is logged but never masks the original transcription error that the
service is responsible for propagating to the websocket layer.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ....core.config.api_settings import settings
from ....core.knowledge.models import Transcription
from ....core.knowledge.sqlite.transcription_repository import TranscriptionRepository
from .audio_utils import save_audio_to_wav

logger = logging.getLogger(__name__)


STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


@dataclass
class TranscriptionStub:
    """Handle returned by ``begin`` and consumed by ``complete`` / ``fail``.

    ``audio_path`` is always set -- the caller uses it to feed the model.
    ``id`` is ``None`` when this context is excluded from history
    (AssistantSession suggestions, flow context) and therefore no row was created.
    ``complete`` / ``fail`` are no-ops on stubs with ``id is None``, so
    callers can always call them without branching.
    """

    audio_path: Path
    started_at: datetime
    model_name: str
    id: Optional[str] = None
    is_retranscription: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)


def should_persist(context_info: Optional[Dict[str, Any]]) -> bool:
    """Return True when this transcription belongs in the history table.

    AssistantSession suggestions and internal inline flow-context transcriptions
    stay out of the list because they are not user-visible dictations. The
    canonical ``transcription`` flow context identifies the normal short-form
    transcription widget and must remain eligible for history persistence.
    Retranscription is not skipped because it updates an existing row.
    """
    if not context_info:
        return True
    if context_info.get("assistant_session"):
        return False
    flow_context = context_info.get("flowContext")
    if flow_context and flow_context != "transcription":
        return False
    return True


def _recordings_dir() -> Path:
    path = settings.STORAGE_DIR / "Recordings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _uploads_dir() -> Path:
    path = settings.STORAGE_DIR / "Uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def begin(
    audio_data: bytes,
    context_info: Optional[Dict[str, Any]],
    model_name: str,
    *,
    language: Optional[str] = None,
) -> TranscriptionStub:
    """Persist audio and (when appropriate) create a ``pending`` row.

    Always returns a stub with a valid ``audio_path`` so the caller can
    feed the model. The stub's ``id`` is set when this context is
    eligible for history (regular recordings and uploads) and left as
    ``None`` for AssistantSession suggestions / flow context so the row is skipped
    -- ``complete`` / ``fail`` become no-ops for those.

    For a retranscription (``context_info['source'] == 'retranscription'``
    with ``existing_audio_path`` and ``transcription_id``): the on-disk
    audio is reused and the existing row's status is flipped to pending.
    No new row is created.
    """
    ctx = context_info or {}
    source = ctx.get("source", "recording")
    now = datetime.now()

    if source == "retranscription":
        existing_audio_path = ctx.get("existing_audio_path")
        transcription_id = ctx.get("transcription_id")
        if existing_audio_path and transcription_id:
            audio_path = Path(existing_audio_path)
            try:
                await TranscriptionRepository().update_status(
                    transcription_id,
                    STATUS_PENDING,
                    transcription_text="",
                    model_name=model_name,
                    last_transcribed_at=now,
                )
            except Exception as exc:
                logger.warning(
                    f"Failed to mark retranscription row {transcription_id} "
                    f"pending: {exc}"
                )
            return TranscriptionStub(
                audio_path=audio_path,
                started_at=now,
                model_name=model_name,
                id=transcription_id,
                is_retranscription=True,
            )
        logger.warning(
            "Retranscription context missing existing_audio_path or "
            "transcription_id; falling back to fresh persistence"
        )

    try:
        audio_path = save_audio_to_wav(
            audio_data=audio_data,
            recordings_dir=_recordings_dir(),
            uploads_dir=_uploads_dir(),
            source=source,
            original_filename=ctx.get("original_filename"),
        )
    except Exception as exc:
        logger.error(f"Failed to persist transcription audio: {exc}")
        raise

    stub = TranscriptionStub(
        audio_path=audio_path,
        started_at=now,
        model_name=model_name,
        id=None,
        is_retranscription=False,
    )

    if not should_persist(context_info):
        logger.debug(
            f"Audio saved to {audio_path} but history persistence skipped "
            f"per context rules"
        )
        return stub

    record = Transcription(
        id=str(uuid.uuid4()),
        timestamp=now,
        transcription_text="",
        model_name=model_name,
        audio_file_path=str(audio_path),
        duration_seconds=_estimate_duration_seconds(audio_data, source),
        language=language or ctx.get("language") or "en",
        created_at=now,
        last_transcribed_at=now,
        app_name=ctx.get("app_name"),
        window_title=ctx.get("window_title"),
        task_category=ctx.get("task_category"),
        status=STATUS_PENDING,
        error_message=None,
    )

    try:
        await TranscriptionRepository().save_transcription(record)
        stub.id = record.id
        logger.info(
            f"Created pending transcription row id={record.id} "
            f"model={model_name} audio={audio_path}"
        )
    except Exception as exc:
        logger.warning(
            f"Failed to insert pending transcription row for {audio_path}: {exc}"
        )

    return stub


async def complete(
    stub: Optional[TranscriptionStub],
    text: str,
    *,
    processing_time_ms: Optional[int] = None,
    model_name: Optional[str] = None,
) -> None:
    """Mark a pending row as completed with the final transcription text.

    No-op when ``stub`` is ``None`` or ``stub.id`` is ``None`` (history
    persistence was skipped for this context).
    """
    if stub is None or stub.id is None:
        return
    resolved_time = processing_time_ms
    if resolved_time is None:
        resolved_time = int((datetime.now() - stub.started_at).total_seconds() * 1000)
    try:
        await TranscriptionRepository().update_status(
            stub.id,
            STATUS_COMPLETED,
            transcription_text=text,
            processing_time_ms=resolved_time,
            model_name=model_name,
            last_transcribed_at=datetime.now(),
        )
        logger.info(
            f"Transcription {stub.id} completed "
            f"({len(text)} chars, {resolved_time} ms)"
        )
    except Exception as exc:
        logger.warning(f"Failed to mark transcription {stub.id} completed: {exc}")


async def fail(
    stub: Optional[TranscriptionStub],
    error_message: str,
    *,
    processing_time_ms: Optional[int] = None,
    model_name: Optional[str] = None,
) -> None:
    """Mark a pending row as failed, recording the error for the UI.

    No-op when ``stub`` is ``None`` or ``stub.id`` is ``None``.
    """
    if stub is None or stub.id is None:
        return
    resolved_time = processing_time_ms
    if resolved_time is None:
        resolved_time = int((datetime.now() - stub.started_at).total_seconds() * 1000)
    try:
        await TranscriptionRepository().update_status(
            stub.id,
            STATUS_FAILED,
            error_message=error_message,
            processing_time_ms=resolved_time,
            model_name=model_name,
            last_transcribed_at=datetime.now(),
        )
        logger.info(
            f"Transcription {stub.id} marked failed after {resolved_time} ms: "
            f"{error_message}"
        )
    except Exception as exc:
        logger.warning(f"Failed to mark transcription {stub.id} failed: {exc}")


async def sweep_stale_pending_rows() -> int:
    """Mark any lingering ``pending`` transcription rows as ``failed``.

    Rows are left in ``pending`` while a transcription is in flight. If
    the API process is terminated (crash, user quit, OS restart) mid-run,
    those rows will still be ``pending`` on the next boot even though
    nothing is actively transcribing them. They would otherwise render
    as an eternal "Transcribing…" state in the UI. This sweep runs once
    during startup and flips them to ``failed`` with a clear error so
    the Retry button surfaces and the user can finish the job.

    Returns the number of rows that were swept, for logging.
    """
    from ....core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
        get_async_connection,
    )
    try:
        db_path = str(TranscriptionRepository().db_path)
    except Exception as exc:
        logger.warning(f"Startup sweep skipped -- repository init failed: {exc}")
        return 0

    conn = None
    try:
        conn = await get_async_connection(db_path, ensure_schema=False)
        cursor = await conn.execute(
            """
            UPDATE transcriptions
            SET status = ?,
                error_message = COALESCE(
                    error_message,
                    'Transcription was interrupted before it finished. The audio was preserved; use Retry to transcribe again.'
                )
            WHERE status = ?
            """,
            (STATUS_FAILED, STATUS_PENDING),
        )
        await conn.commit()
        count = cursor.rowcount or 0
        if count > 0:
            logger.info(f"Startup sweep: marked {count} stale pending transcription(s) as failed")
        return count
    except Exception as exc:
        logger.warning(f"Startup sweep of stale pending transcriptions failed: {exc}")
        return 0
    finally:
        if conn:
            await conn.close()


def _estimate_duration_seconds(audio_data: bytes, source: str) -> Optional[float]:
    """Best-effort duration for the history row's duration_seconds column.

    Raw Float32 PCM from the websocket clients is sampled at 16 kHz, so
    the math is exact (4 bytes per sample). For ``file_upload`` we don't
    decode the container here; leave it None rather than lie.
    """
    if source == "file_upload":
        return None
    if not audio_data:
        return None
    # Float32 PCM @ 16 kHz
    sample_count = len(audio_data) / 4
    return round(sample_count / 16000.0, 3)
