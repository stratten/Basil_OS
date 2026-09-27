"""Streaming pipeline for ``POST /assistant-sessions/start``.

Captures the screen image (already provided by the Swift client) and runs OCR
in a worker thread, streaming first the assigned ``session_id`` and then the
extracted text (or an error) back to the client over NDJSON.

The OCR ``asyncio.Task`` is registered in ``assistant_session_state.active_ocr_tasks``
keyed by session ID so that ``DELETE /cancel/{session_id}`` can cancel an
in-flight OCR pass when the user dismisses the widget.
"""

import asyncio
import json
import logging
from typing import AsyncIterator

from . import assistant_session_state
from ..assistant_session_service import AssistantSessionService

logger = logging.getLogger(__name__)


async def stream_start_session(
    session_id: str,
    image_path: str,
    service: AssistantSessionService,
) -> AsyncIterator[str]:
    """NDJSON event generator for ``/start``.

    Emits, in order:
      1. ``{"session_id": "..."}`` immediately.
      2. ``{"session_id": "...", "ocr_text": "..."}`` on success, or
         ``{"session_id": "...", "ocr_text": "", "error": "..."}`` on
         failure / cancellation.

    The OCR call itself runs in a worker thread (``asyncio.to_thread``) so
    the event loop can keep emitting and so the task is cancellable by
    ``DELETE /cancel/{session_id}`` via ``assistant_session_state.active_ocr_tasks``.
    """
    print(f"🎤 [START] Event generator entered for session {session_id}", flush=True)
    logger.info(f"🎤 [ROUTER] Streaming session_id: {session_id}")
    yield json.dumps({"session_id": session_id}) + "\n"
    print(f"🎤 [START] Session ID sent for session {session_id}", flush=True)

    try:
        print(f"🎤 [START] Starting OCR task for session {session_id}, image: {image_path}", flush=True)
        logger.info(f"🎤 [ROUTER] Calling service.capture_screen_and_extract_text for session {session_id} via asyncio.to_thread")

        ocr_task = asyncio.create_task(
            asyncio.to_thread(service.capture_screen_and_extract_text, image_path, session_id)
        )
        assistant_session_state.active_ocr_tasks[session_id] = ocr_task

        try:
            await ocr_task
            print(f"🎤 [START] OCR task completed for session {session_id}", flush=True)
            logger.info(f"🎤 [ROUTER] asyncio.to_thread for OCR completed for session {session_id}")
        except asyncio.CancelledError:
            print(f"🎤 [START] OCR task CANCELLED for session {session_id}", flush=True)
            logger.info(f"🎤 [ROUTER] OCR task cancelled for session {session_id}")
            yield json.dumps({"session_id": session_id, "ocr_text": "", "error": "Operation cancelled by user"}) + "\n"
            return
        finally:
            assistant_session_state.active_ocr_tasks.pop(session_id, None)

        ocr_result_from_session = service.sessions.get(session_id, {}).get("ocr_result")
        print(f"🎤 [START] OCR result retrieved for session {session_id}: {ocr_result_from_session is not None}", flush=True)

        if ocr_result_from_session is not None:
            if hasattr(ocr_result_from_session, 'status') and ocr_result_from_session.status == "error":
                print(f"🎤 [START] OCR FAILED for session {session_id}: {ocr_result_from_session.error}", flush=True)
                logger.error(f"❌ [ROUTER] OCR failed for session {session_id}: {ocr_result_from_session.error}")
                yield json.dumps({"session_id": session_id, "ocr_text": "", "error": ocr_result_from_session.error}) + "\n"
            else:
                text = ocr_result_from_session.cleaned_text if hasattr(ocr_result_from_session, 'cleaned_text') else ""
                print(f"🎤 [START] OCR SUCCESS for session {session_id}, text length: {len(text) if text else 0}", flush=True)
                logger.info(f"🎤 [ROUTER] OCR succeeded for session {session_id}, sending text: {text[:100] if text else '(empty)'}...")
                yield json.dumps({"session_id": session_id, "ocr_text": text}) + "\n"
                print(f"🎤 [START] OCR text sent for session {session_id}", flush=True)
        else:
            print(f"🎤 [START] ERROR: OCR result MISSING in session for {session_id}", flush=True)
            logger.error(f"❌ [ROUTER] OCR result not found in session {session_id} after to_thread call. This is unexpected.")
            yield json.dumps({"session_id": session_id, "ocr_text": "", "error": "OCR result missing after processing"}) + "\n"

    except Exception as stream_error:
        logger.error(f"❌ [ROUTER] Error during OCR streaming/processing for session {session_id}: {stream_error}")
        try:
            yield json.dumps({"session_id": session_id, "ocr_text": "", "error": str(stream_error)}) + "\n"
        except Exception as final_error:
            logger.error(f"❌ [ROUTER] Critical error sending stream error for session {session_id}: {final_error}")
