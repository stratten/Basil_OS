"""Refinement routes:

* ``POST /{session_id}/refine`` -- transcribe (or accept typed text)
  and refine using the original session's OCR + previous output as
  context.
* ``POST /rehydrate-from-history/{assistant_output_id}`` -- materialise a
  fresh in-memory session from a persisted history row so refinement can
  run against historical state.

The endpoint accepts spoken or typed refinement input.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from starlette.status import HTTP_400_BAD_REQUEST

from .refinement_pipeline import (
    materialize_session_from_history,
    run_refinement,
    stream_refinement,
)
from .assistant_session_models import AssistantSessionRehydrateResponse
from .assistant_session_state import get_assistant_session_service
from ..assistant_session_service import AssistantSessionService
from ....dependencies import get_wake_word_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{session_id}/refine", response_class=StreamingResponse)
async def refine_assistant_session_audio(
    session_id: str,
    request: Request,
    audio_file: Optional[UploadFile] = File(None, description="Refinement audio recording. Mutually exclusive with instruction_text."),
    instruction_text: Optional[str] = Form(None, description="Typed refinement instruction. Mutually exclusive with audio_file."),
    model_id: Optional[str] = Form(None, description="Reasoning model to use"),
    service: AssistantSessionService = Depends(get_assistant_session_service),
    voice_listener_service=Depends(get_wake_word_service),
) -> StreamingResponse:
    """Process a refinement request for an existing AssistantSession session.

    Accepts spoken (multipart ``audio_file``) or typed (form field
    ``instruction_text``) refinement input; the two are mutually
    exclusive and exactly one is required (refinement has no no-input
    modality -- there is nothing to refine toward without an
    instruction).
    """
    try:
        typed = (instruction_text or "").strip()
        if audio_file is not None and typed:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="Provide either audio_file or instruction_text, not both.",
            )
        if audio_file is None and not typed:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="Refinement requires either audio_file or instruction_text.",
            )

        audio_data: Optional[bytes] = None
        if audio_file is not None:
            audio_data = await audio_file.read()
            logger.info(f"🎤 [ROUTER] Refinement audio received: {len(audio_data)} bytes for session {session_id}")
        else:
            logger.info(f"🎤 [ROUTER] Refinement typed instruction received ({len(typed)} chars) for session {session_id}")

        accept_header = request.headers.get("accept", "")
        logger.info(f"🎤 [ROUTER] Refinement Accept header for session {session_id}: '{accept_header}'")
        wants_streaming = "text/stream" in accept_header or "application/x-ndjson" in accept_header
        logger.info(f"🎤 [ROUTER] Refinement streaming mode for session {session_id}: {wants_streaming}")

        if wants_streaming:
            return StreamingResponse(
                stream_refinement(
                    session_id=session_id,
                    audio_data=audio_data,
                    instruction_text=typed or None,
                    model_id=model_id,
                    service=service,
                    voice_listener_service=voice_listener_service,
                ),
                media_type="application/x-ndjson",
            )

        return await run_refinement(
            session_id=session_id,
            audio_data=audio_data,
            instruction_text=typed or None,
            model_id=model_id,
            service=service,
            voice_listener_service=voice_listener_service,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [ROUTER] Failed to process refinement audio: {e}")
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=f"Refinement processing failed: {e}")


@router.post("/rehydrate-from-history/{assistant_output_id}", response_model=AssistantSessionRehydrateResponse)
async def rehydrate_assistant_session_from_history(
    assistant_output_id: int,
    service: AssistantSessionService = Depends(get_assistant_session_service),
) -> AssistantSessionRehydrateResponse:
    """Recreate an in-memory AssistantSession session from a persisted history row.

    See ``materialize_session_from_history`` in ``refinement_pipeline`` for
    the full rationale; in short, this is the entry point that lets the
    client refine an old AssistantSession output without forcing them to re-capture
    the screen and re-record an initial prompt.
    """
    session_id, detail = await materialize_session_from_history(assistant_output_id, service)

    return AssistantSessionRehydrateResponse(
        session_id=session_id,
        assistant_output_id=assistant_output_id,
        output_text=detail.get("output_text") or "",
        input_modality=detail.get("input_modality"),
        user_request=(detail.get("user_request") or None),
        context_text=(detail.get("context_text") or None),
        explanation_text=detail.get("explanation_text"),
        model_name=detail.get("model_name"),
        app_name=detail.get("app_name"),
        refinement_count=detail.get("refinement_count") or 0,
    )
