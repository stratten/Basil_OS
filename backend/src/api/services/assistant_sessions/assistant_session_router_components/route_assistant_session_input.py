"""Route module for ``POST /assistant-sessions/{session_id}/process-input``.

Despite the historical endpoint name, this route accepts three input
modalities -- spoken (multipart ``audio_file``), typed (form field
``instruction_text``), or no instruction at all -- and dispatches all
three to the same downstream pipeline. The endpoint name is preserved
for backwards compatibility with existing clients.

Parses the multipart audio (or text) + optional text-selection JSON,
stores selection context on the session, then dispatches to the
streaming or non-streaming branch of ``process_audio_pipeline`` based
on the client's ``Accept`` header.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from starlette.status import HTTP_400_BAD_REQUEST

from .process_audio_pipeline import run_process_audio, stream_process_audio
from .assistant_session_models import AssistantSessionOutputResponse
from .assistant_session_state import get_assistant_session_service
from ..assistant_session_service import AssistantSessionService
from ....dependencies import get_wake_word_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{session_id}/process-input", response_class=StreamingResponse)
async def process_assistant_session_audio(
    session_id: str,
    request: Request,
    audio_file: Optional[UploadFile] = File(None, description="Audio recording to transcribe and process. Mutually exclusive with instruction_text. Omit both for the no-instruction modality."),
    instruction_text: Optional[str] = Form(None, description="Typed instruction. Mutually exclusive with audio_file."),
    text_selection: Optional[str] = Form(None, description="Text selection context as JSON"),
    model_id: Optional[str] = Form(None, description="Reasoning model to use"),
    service: AssistantSessionService = Depends(get_assistant_session_service),
    voice_listener_service=Depends(get_wake_word_service),
) -> StreamingResponse:
    """Process a AssistantSession request in any of three input modalities.

    The session must have been started with ``/start`` to capture OCR text.
    Returns transcription (or empty for the no-input modality) and
    AssistantSession output, with optional streaming if the ``Accept`` header
    includes ``text/stream`` or ``application/x-ndjson``.

    Modality is selected by which body fields are populated:

    * ``audio_file`` only -> spoken modality (existing behavior).
    * ``instruction_text`` only -> typed modality, transcription is skipped.
    * Neither -> no-instruction modality, server substitutes a default
      screen-only instruction so the model still produces something
      useful from the captured screen alone.

    Sending both ``audio_file`` and ``instruction_text`` is rejected with
    400, since the resulting prompt instruction would be ambiguous.
    """
    print(f"🎤 [ROUTER] ===== PROCESS_AUDIO CALLED FOR SESSION {session_id} =====", flush=True)
    logger.warning(f"🎤 [ROUTER] ===== PROCESS_AUDIO CALLED FOR SESSION {session_id} =====")
    try:
        typed = (instruction_text or "").strip()
        if audio_file is not None and typed:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="Provide either audio_file or instruction_text, not both.",
            )

        audio_data: Optional[bytes] = None
        if audio_file is not None:
            audio_data = await audio_file.read()
            print(f"🎤 [ROUTER] Audio data read: {len(audio_data)} bytes for session {session_id}", flush=True)
            logger.warning(f"🎤 [ROUTER] Audio data read: {len(audio_data)} bytes for session {session_id}")
        elif typed:
            print(f"🎤 [ROUTER] Typed instruction received ({len(typed)} chars) for session {session_id}", flush=True)
            logger.info(f"🎤 [ROUTER] Typed instruction received ({len(typed)} chars) for session {session_id}")
        else:
            print(f"🎤 [ROUTER] No-instruction modality for session {session_id}", flush=True)
            logger.info(f"🎤 [ROUTER] No-instruction modality for session {session_id}")

        selection_data = None
        if text_selection:
            try:
                selection_data = json.loads(text_selection)
                selected_text = selection_data.get('selected_text', '')
                logger.info(f"🎤 [ROUTER] Text selection received for session {session_id}")
                logger.info(f"🎤 [ROUTER] Selection length: {len(selected_text)} chars")
                logger.info(f"🎤 [ROUTER] Selection preview: {selected_text[:100]}...")
                if len(selected_text) > 100:
                    logger.info(f"🎤 [ROUTER] Selection ending: ...{selected_text[-100:]}")
            except json.JSONDecodeError as e:
                logger.warning(f"🎤 [ROUTER] Invalid text selection JSON for session {session_id}: {e}")

        # Store selection data on the session so the pipeline can read it.
        if selection_data and session_id in service.sessions:
            service.sessions[session_id]["text_selection"] = selection_data
            service.sessions[session_id]["has_selection_context"] = selection_data.get("has_selection", False)
            logger.info(f"🎤 [ROUTER] Stored text selection context in session {session_id}")

        accept_header = request.headers.get("accept", "")
        print(f"🎤 [ROUTER] Accept header for session {session_id}: '{accept_header}'", flush=True)
        logger.info(f"🎤 [ROUTER] Accept header for session {session_id}: '{accept_header}'")
        wants_streaming = "text/stream" in accept_header or "application/x-ndjson" in accept_header
        print(f"🎤 [ROUTER] Streaming mode for session {session_id}: {wants_streaming}", flush=True)
        logger.info(f"🎤 [ROUTER] Streaming mode for session {session_id}: {wants_streaming}")

        if wants_streaming:
            return StreamingResponse(
                stream_process_audio(
                    session_id=session_id,
                    audio_data=audio_data,
                    instruction_text=typed or None,
                    model_id=model_id,
                    service=service,
                    voice_listener_service=voice_listener_service,
                ),
                media_type="application/x-ndjson",
            )

        result = await run_process_audio(
            session_id=session_id,
            audio_data=audio_data,
            instruction_text=typed or None,
            model_id=model_id,
            service=service,
            voice_listener_service=voice_listener_service,
        )
        # The pipeline returns {"transcription": ..., "suggestion": ...} for
        # backward-compat internally; remap to the new wire field name.
        return AssistantSessionOutputResponse(
            transcription=result.get("transcription", ""),
            assistant_output=result.get("suggestion", ""),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [ROUTER] Failed to process AssistantSession audio: {e}")
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=f"Audio processing failed: {e}")
