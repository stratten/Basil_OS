"""Session-lifecycle routes: ``/ping``, ``POST /start``, ``POST /start_from_text``, ``DELETE /{session_id}``.

This module defines an unprefixed ``APIRouter`` that the facade aggregates
under ``/assistant-sessions``. The handlers stay thin -- session bookkeeping
stays here, but the actual OCR streaming work lives in
``start_session_pipeline``.
"""

import json
import logging
from datetime import datetime
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from . import assistant_session_state
from .assistant_session_models import (
    CancelSessionResponse,
    ContextTextRequest,
    ImagePathRequest,
)
from .assistant_session_state import get_assistant_session_service
from .start_session_pipeline import stream_start_session
from ..assistant_session_service import AssistantSessionService
from ...ocr.ocr_models import OCRResult
from ....core.models.responses import StatusResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/ping", response_model=StatusResponse)
async def ping_assistant_session() -> StatusResponse:
    logger.info("🎤 [ROUTER] /assistant-sessions/ping received")
    return StatusResponse(status="success", message="pong from AssistantSession")


@router.post("/start", response_class=StreamingResponse)
async def start_assistant_session(
    request_data: ImagePathRequest,
    service: AssistantSessionService = Depends(get_assistant_session_service),
) -> StreamingResponse:
    """Start the AssistantSession flow with a provided image path (from Swift capture).

    Returns a session ID immediately. OCR text is streamed when ready.
    """
    image_path = request_data.image_path
    try:
        # File existence is implicitly checked by the OCR service when it
        # attempts to read the file; failures surface through ocr_result.
        logger.info(f"🎤 [ROUTER] Starting AssistantSession with Swift-captured image: {image_path}")

        # Create session and store placeholder before starting any async work.
        service._cleanup_old_sessions()
        session_id = service._generate_session_id()
        service.sessions[session_id] = {
            "created_at": datetime.now(),
            "ocr_result": None,
            "transcription": None,
            "suggestion": None,
        }

        return StreamingResponse(
            stream_start_session(session_id, image_path, service),
            media_type="application/x-ndjson",
        )

    except Exception as e:
        logger.error(f"❌ [ROUTER] Failed to start AssistantSession endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start AssistantSession: {str(e)}")


@router.post("/start_from_text", response_class=StreamingResponse)
async def start_assistant_session_from_text(
    request_data: ContextTextRequest,
    service: AssistantSessionService = Depends(get_assistant_session_service),
) -> StreamingResponse:
    """Start an AssistantSession whose context is provided directly as text.

    Used by setup-launched Dill sessions, where the grounding is a specific
    pulled email body rather than a screen capture. Skips the OCR worker
    thread entirely and seeds the session's ``ocr_result`` slot with a
    synthetic OCRResult carrying the provided text, so downstream prompt
    construction (process_audio / process_text / refinement) finds the
    context exactly where it would for an OCR-driven session.

    The streamed body mirrors ``/start`` for client compatibility: an
    initial ``{"session_id": "..."}`` frame, then a single
    ``{"session_id": "...", "ocr_text": "..."}`` frame echoing the text
    back, so the Swift view model's existing NDJSON consumer needs no
    changes.
    """
    context_text = request_data.context_text or ""
    try:
        logger.info(
            f"🎤 [ROUTER] Starting AssistantSession from text "
            f"(context_text length={len(context_text)} chars)"
        )

        # Mirrors /start: allocate id and reserve the session slot before
        # any async work so the cancel route and the streaming body see a
        # consistent session dict.
        service._cleanup_old_sessions()
        session_id = service._generate_session_id()
        synthetic_ocr = OCRResult(
            status="success",
            cleaned_text=context_text,
            image_path="",
            processing_time_ms=0,
        )
        service.sessions[session_id] = {
            "created_at": datetime.now(),
            "ocr_result": synthetic_ocr,
            "transcription": None,
            "suggestion": None,
        }

        return StreamingResponse(
            _stream_seeded_session(session_id, context_text),
            media_type="application/x-ndjson",
        )

    except Exception as exc:
        logger.error(
            f"❌ [ROUTER] Failed to start AssistantSession from text: {exc}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start AssistantSession from text: {exc}",
        )


async def _stream_seeded_session(
    session_id: str,
    context_text: str,
) -> AsyncIterator[str]:
    """Emit the two NDJSON frames an /start-shaped client expects.

    No OCR work happens here — the synthetic OCRResult was already placed
    into ``service.sessions`` by the caller. We just yield the session id
    and an immediate ``ocr_text`` frame echoing what the client supplied.
    """
    yield json.dumps({"session_id": session_id}) + "\n"
    yield json.dumps({"session_id": session_id, "ocr_text": context_text}) + "\n"


@router.delete("/{session_id}", response_model=CancelSessionResponse)
async def cancel_assistant_session_session(
    session_id: str,
    service: AssistantSessionService = Depends(get_assistant_session_service),
) -> CancelSessionResponse:
    """Cancel an active AssistantSession session and clean up resources."""
    try:
        logger.info(f"🎤 [ROUTER] Canceling AssistantSession session: {session_id}")

        if session_id in assistant_session_state.active_ocr_tasks:
            task = assistant_session_state.active_ocr_tasks[session_id]
            if not task.done():
                task.cancel()
                logger.info(f"🎤 [ROUTER] Canceled active OCR task for session: {session_id}")
            del assistant_session_state.active_ocr_tasks[session_id]

        if session_id in service.sessions:
            del service.sessions[session_id]
            logger.info(f"🎤 [ROUTER] Removed session: {session_id}")

        return CancelSessionResponse(status="canceled", session_id=session_id)

    except Exception as e:
        logger.error(f"❌ [ROUTER] Failed to cancel session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel session: {str(e)}")
