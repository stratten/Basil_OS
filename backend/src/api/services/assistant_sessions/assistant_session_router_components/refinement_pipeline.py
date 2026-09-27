"""Streaming + non-streaming pipelines for ``POST /assistant-sessions/{session_id}/refine``,
plus the session factory used by ``POST /assistant-sessions/rehydrate-from-history/{assistant_output_id}``.

Refinement reuses the original session's OCR context and previous LLM
output, treating the new instruction as a refinement input. The pipeline
accepts two input modalities at the post-transcription seam -- spoken
audio (transcribed in-pipeline) or typed text (used directly) -- which
both converge to the same ``current_transcription`` session field that
``_build_refinement_prompt`` consumes. Refinement does not support a
no-input modality: there is nothing to refine toward without an
instruction, so an empty/missing instruction is rejected with 400 at the
route layer.

The streaming branch sends the transcription event as soon as the
instruction string is available (immediately for typed input, after
transcription for audio), then streams LLM tokens; the non-streaming
branch defers to ``service.process_refinement_audio`` /
``service.process_refinement_text`` depending on modality.

Rehydration materialises a fresh in-memory session from a persisted history
row whose shape matches what ``service._build_refinement_prompt`` expects --
this is the only way the refinement endpoints can run against a history
item without forcing the user to recapture their screen and re-record an
initial prompt.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, AsyncIterator, Dict, Optional, Tuple

from fastapi import HTTPException
from starlette.status import HTTP_400_BAD_REQUEST

from . import assistant_session_state
from .model_unload_scheduling import schedule_transcription_model_unload_with_voice_listener_check
from .assistant_session_state import get_assistant_output_history_service
from ..assistant_session_service import AssistantSessionService
from ....core.models.model_types import ModelCapability
from ....dependencies import resolve_transcription_service
from ....services.transcription.backends.parakeet_components import (
    PARAKEET_PROGRESS_CALLBACK_CONTEXT_KEY,
    ParakeetTranscriptionProgress,
)
from api.core.preferences.preferences_io import load_preferences

logger = logging.getLogger(__name__)


async def stream_refinement(
    session_id: str,
    audio_data: Optional[bytes],
    instruction_text: Optional[str],
    model_id: Optional[str],
    service: AssistantSessionService,
    voice_listener_service,
) -> AsyncIterator[str]:
    """NDJSON streaming generator for ``/{session_id}/refine``.

    Accepts spoken (``audio_data``) or typed (``instruction_text``)
    refinement input. The route layer guarantees exactly one of the two
    is provided (no-input refinement is meaningless).
    """
    try:
        # Hoisted session check: fails fast before transcription / LLM work.
        if session_id not in service.sessions:
            yield json.dumps({"error": "Session not found", "complete": True}) + "\n"
            return

        # Resolve the refinement instruction by input modality. After this
        # block, the local ``new_transcription`` variable is the string
        # the downstream pipeline writes into ``session["current_transcription"]``.
        typed = (instruction_text or "").strip()
        used_audio_path = False
        if audio_data:
            used_audio_path = True
            service.transcription_service = resolve_transcription_service()
            progress_queue: asyncio.Queue[ParakeetTranscriptionProgress] = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def _queue_parakeet_progress(progress: ParakeetTranscriptionProgress) -> None:
                loop.call_soon_threadsafe(progress_queue.put_nowait, progress)

            yield json.dumps({"stage": "transcribing"}) + "\n"
            transcription_task = asyncio.create_task(
                service.transcribe_audio(
                    session_id,
                    audio_data,
                    {
                        "assistant_session": True,
                        PARAKEET_PROGRESS_CALLBACK_CONTEXT_KEY: _queue_parakeet_progress,
                    },
                )
            )
            progress_task: Optional[asyncio.Task[ParakeetTranscriptionProgress]] = None

            try:
                while not transcription_task.done():
                    if progress_task is None:
                        progress_task = asyncio.create_task(progress_queue.get())
                    done, _ = await asyncio.wait(
                        {transcription_task, progress_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if progress_task in done:
                        progress = progress_task.result()
                        progress_task = None
                        yield json.dumps({
                            "stage": "transcribing",
                            "progress": progress.to_payload(),
                        }) + "\n"
            finally:
                if progress_task is not None:
                    progress_task.cancel()

            transcription_result = await transcription_task
            new_transcription = transcription_result["transcription"]
        else:
            new_transcription = typed

        yield json.dumps({
            "transcription": new_transcription,
            "stage": "transcription_complete"
        }) + "\n"

        session = service.sessions[session_id]

        if not session.get("refinement_mode", False):
            session["initial_transcription"] = session.get("transcription", "")
            session["initial_suggestion"] = session.get("suggestion", "")
            session["refinement_mode"] = True
            session["iteration_count"] = 0
            logger.info(f"🎤 [ROUTER] Session {session_id} converted to refinement mode")

        session["current_transcription"] = new_transcription
        session["iteration_count"] += 1

        refinement_prompt = await service._build_refinement_prompt(session)

        model = await service.model_usage_service.get_model_for_task(
            capabilities={ModelCapability.REASONING},
            explicit_model_id=model_id
        )

        if not model:
            yield json.dumps({
                "assistant_output": "[Error: No suitable model found for refinement.]",
                "iteration_count": session["iteration_count"],
                "complete": True
            }) + "\n"
            return

        # Step 3: Stream LLM refinement response.
        messages = [{"role": "user", "content": refinement_prompt}]
        suggestion_text = ""

        yield json.dumps({
            "stage": "generating_refinement",
            "iteration_count": session["iteration_count"]
        }) + "\n"

        try:
            async for token in model.chat_completion_streaming(messages):
                suggestion_text += token
                yield json.dumps({
                    "assistant_output_token": token,
                    "assistant_output_partial": suggestion_text
                }) + "\n"
        except Exception as streaming_error:
            error_message = str(streaming_error)
            logger.error(f"LLM streaming error for refinement session {session_id}: {error_message}")

            if "rate limit" in error_message.lower() or "429" in error_message:
                user_error = "API rate limit reached. Please wait a moment and try again."
            elif "network" in error_message.lower() or "connection" in error_message.lower():
                user_error = "Network connection issue. Please check your internet and try again."
            elif "authentication" in error_message.lower() or "401" in error_message:
                user_error = "API authentication error. Please check your API key configuration."
            else:
                user_error = f"Error generating refinement: {error_message}"

            yield json.dumps({
                "error": user_error,
                "assistant_output": f"[Error: {user_error}]",
                "complete": True
            }) + "\n"
            return

        session["current_suggestion"] = suggestion_text

        try:
            persisted_id = session.get("persisted_assistant_output_id")
            if persisted_id:
                history_svc = get_assistant_output_history_service()
                await history_svc.update_refinement(
                    assistant_output_id=persisted_id,
                    instruction=new_transcription,
                    output=suggestion_text,
                )
                logger.info(f"Persisted refinement for assistant_output {persisted_id}")
        except Exception as persist_err:
            logger.error(f"Failed to persist refinement for session {session_id}: {persist_err}")

        yield json.dumps({
            "transcription": new_transcription,
            "assistant_output": suggestion_text,
            "iteration_count": session["iteration_count"],
            "complete": True
        }) + "\n"

        if used_audio_path:
            try:
                preferences = load_preferences()
                delay = preferences.transcription.model_unload_delay
                assistant_session_state.model_unload_task = schedule_transcription_model_unload_with_voice_listener_check(
                    service.transcription_service,
                    voice_listener_service,
                    delay,
                    assistant_session_state.model_unload_task,
                    session_id,
                )
                logger.info(f"Scheduled transcription model unload with {delay}s delay for refinement session: {session_id}")
            except Exception as unloadErr:
                logger.error(f"Failed to schedule model unload: {unloadErr}")

    except Exception as e:
        logger.error(f"Error in refinement streaming: {e}")
        yield json.dumps({"error": str(e), "complete": True}) + "\n"


async def run_refinement(
    session_id: str,
    audio_data: Optional[bytes],
    instruction_text: Optional[str],
    model_id: Optional[str],
    service: AssistantSessionService,
    voice_listener_service,
) -> dict:
    """Non-streaming branch of ``/{session_id}/refine``.

    Mirrors the streaming branch's modality dispatch: audio bytes go
    through ``service.process_refinement_audio`` (which transcribes +
    refines), typed text goes through ``service.process_refinement_text``
    (which skips transcription). Refinement has no no-input modality;
    the route layer rejects empty/missing input with 400 before
    reaching this function.

    Returns the dict the route handler shapes into the JSON response.
    The transcription-model unload is only scheduled for the audio
    modality, since the text path never loaded the transcription model.
    """
    if audio_data:
        result = await service.process_refinement_audio(session_id, audio_data, model_id)

        try:
            preferences = load_preferences()
            delay = preferences.transcription.model_unload_delay
            assistant_session_state.model_unload_task = schedule_transcription_model_unload_with_voice_listener_check(
                service.transcription_service,
                voice_listener_service,
                delay,
                assistant_session_state.model_unload_task,
                session_id,
            )
            logger.info(f"Scheduled transcription model unload with {delay}s delay for refinement session: {session_id}")
        except Exception as unloadErr:
            logger.error(f"Failed to schedule model unload: {unloadErr}")
    else:
        result = await service.process_refinement_text(session_id, instruction_text or "", model_id)

    return {
        "transcription": result["transcription"],
        "assistant_output": result["suggestion"],
        "iteration_count": result["iteration_count"],
    }


async def materialize_session_from_history(
    assistant_output_id: int,
    service: AssistantSessionService,
) -> Tuple[str, Dict[str, Any]]:
    """Build a fresh in-memory AssistantSession session from a persisted row.

    Returns ``(session_id, history_detail)`` so the route handler can both
    populate the response and use the new ``session_id`` for refinement.
    Raises ``HTTPException`` if the id is not found or is not a AssistantSession
    output.

    The persisted AssistantSession output only stores text fields (no live OCR
    object, no transcription pipeline state). To make the existing
    ``/assistant-sessions/{session_id}/refine`` endpoint usable against
    history items, we materialise a synthetic session whose shape matches
    what the refinement code path expects:

    - ``ocr_result`` exposes ``.cleaned_text`` so ``_build_refinement_prompt``
      can read the original screen context.
    - ``transcription`` and ``suggestion`` carry the original user request
      and model output, which the refinement route promotes to
      ``initial_transcription`` / ``initial_suggestion`` on first
      refinement iteration.
    - ``persisted_assistant_output_id`` ensures any new refinement is
      appended to the original history row instead of creating a
      duplicate record.
    """
    history_svc = get_assistant_output_history_service()
    detail = await history_svc.get_assistant_output_detail(assistant_output_id)
    if not detail:
        raise HTTPException(status_code=404, detail="AssistantSession output not found")
    if (detail.get("output_type") or "regular") != "assistant_session":
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="rehydrate-from-history is only valid for AssistantSession outputs",
        )

    from ...ocr.ocr_models import OCRResult

    service._cleanup_old_sessions()
    session_id = service._generate_session_id()

    context_text = detail.get("context_text") or ""
    output_text = detail.get("output_text") or ""
    user_request = detail.get("user_request") or ""

    # Synthesize an OCRResult so refinement prompt construction can read
    # the original screen context via session["ocr_result"].cleaned_text.
    synthetic_ocr = OCRResult(
        status="success",
        cleaned_text=context_text,
        image_path="",
        processing_time_ms=0,
    )

    service.sessions[session_id] = {
        "created_at": datetime.now(),
        "ocr_result": synthetic_ocr,
        "transcription": user_request,
        "suggestion": output_text,
        "persisted_assistant_output_id": assistant_output_id,
        "rehydrated_from_history": True,
    }

    logger.info(
        f"🎤 [ROUTER] Rehydrated AssistantSession session {session_id} "
        f"from history id={assistant_output_id}"
    )

    return session_id, detail
