"""Streaming + non-streaming pipelines for ``POST /assistant-sessions/process_audio/{session_id}``.

Despite the historical endpoint name, this pipeline accepts three input
modalities -- audio bytes, typed text, or no instruction at all -- and
all three converge to the same downstream shape: a single ``transcription``
string the LLM stage operates on. The post-transcription seam (where the
local ``transcription`` variable becomes available) is where the three
modalities merge; everything past that point is identical regardless of
how the instruction was obtained.

Both branches share the same orchestration shape downstream of the seam:

  1. Resolve the active transcription service (preferences may have switched
     between local Whisper and a cloud API since the previous request) -- only
     applicable when the input modality is audio.
  2. Obtain the instruction string: transcribe audio, accept typed text, or
     fall back to ``NO_INSTRUCTION_DEFAULT`` for the no-input modality.
  3. Build an enhanced prompt from OCR + instruction + (optional)
     text-selection + app-name context via the service's context enhancer.
  4. Generate the suggestion via a reasoning model.
  5. Persist the suggestion to history.
  6. Schedule a delayed transcription-model unload (voice-listener-aware,
     only when the audio path actually loaded the transcription model).

The streaming branch additionally:
  - Emits a ``"transcribing"`` stage with chunk-progress ticks while a local
    Whisper transcription is in progress (no-op for cloud APIs and skipped
    entirely for the text and no-input modalities).
  - Emits a ``"transcription_complete"`` stage event for all three modalities
    so client-side stage tracking is modality-symmetric -- the text and
    no-input branches just emit it immediately with the appropriate string.
  - Streams LLM tokens as they arrive via ``assistant_output_token`` /
    ``assistant_output_partial`` events.

The no-input modality replaces the deprecated basic ``/suggestion`` endpoint:
when the user activates AssistantSession without speaking or typing, we substitute
``NO_INSTRUCTION_DEFAULT`` as the instruction so the model still produces
something useful from the captured screen alone, but the response's
``transcription`` field is reported as an empty string (the user didn't
provide one).
"""

import asyncio
import json
import logging
from typing import AsyncIterator, Optional

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
from api.core.knowledge.personalization.session_sample_context import resolve_session_recipient
from .paste_directive import PasteDirectiveFilter, resolve_paste_mode, with_paste_instruction

logger = logging.getLogger(__name__)


# Default instruction substituted when the user submits a AssistantSession request
# with no spoken audio and no typed instruction. Replaces the legacy basic
# ``/suggestion`` behavior: produce something useful from the captured
# screen context alone rather than asking the user what they want.
NO_INSTRUCTION_DEFAULT = (
    "Look at what's on the user's screen and generate the most useful "
    "single piece of output they likely want next: a draft reply, the "
    "next code block, a complete instruction, a summary, or whatever the "
    "context most strongly implies. Make a concrete decision about what "
    "to produce -- do not ask the user what they want."
)


async def stream_process_audio(
    session_id: str,
    audio_data: Optional[bytes],
    instruction_text: Optional[str],
    model_id: Optional[str],
    service: AssistantSessionService,
    voice_listener_service,
) -> AsyncIterator[str]:
    """NDJSON streaming generator for ``/process_audio``.

    Accepts three input modalities, selected by which arguments are
    provided:

    * ``audio_data`` non-empty -> transcribe audio (existing path:
      ``transcribing`` stage + progress ticks + ``transcription_complete``).
    * ``instruction_text`` non-empty -> use the typed string directly,
      skip transcription entirely. Emits ``transcription_complete`` once
      with the typed string for client-side stage symmetry.
    * Neither -> use ``NO_INSTRUCTION_DEFAULT`` as the prompt's
      instruction; emit ``transcription_complete`` with an empty
      transcription string so the client sees the empty user input but
      the model still receives something concrete to act on.

    Selection-context bookkeeping (parsing the ``text_selection`` JSON and
    storing it on the session) happens in the route handler before this
    generator is invoked, so by the time we read ``session["text_selection"]``
    here it is already populated.
    """
    try:
        print(f"🎤 [STREAM] Entered stream_suggestion generator for session {session_id}", flush=True)

        # Hoisted session check: applies to every modality, fails fast
        # before we spend time on transcription or LLM work.
        if session_id not in service.sessions:
            print(f"🎤 [STREAM] ERROR: Session {session_id} not found!", flush=True)
            yield json.dumps({"error": "Session not found", "complete": True}) + "\n"
            return

        # Resolve the user's instruction by input modality. After this
        # block, the local ``transcription`` variable is the string the
        # downstream pipeline operates on, and ``transcription_for_response``
        # is the string we report back to the client in the final
        # ``transcription`` field (empty for the no-input modality).
        typed = (instruction_text or "").strip()
        used_audio_path = False
        if audio_data:
            used_audio_path = True

            # Audio is float32 PCM at 44100 Hz from AudioCaptureService.
            estimated_duration_secs = len(audio_data) / 4 / 44100

            service.transcription_service = resolve_transcription_service()
            progress_queue: asyncio.Queue[ParakeetTranscriptionProgress] = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def _queue_parakeet_progress(progress: ParakeetTranscriptionProgress) -> None:
                loop.call_soon_threadsafe(progress_queue.put_nowait, progress)

            yield json.dumps({
                "stage": "transcribing",
                "estimated_duration": round(estimated_duration_secs, 1)
            }) + "\n"

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
                            "estimated_duration": round(estimated_duration_secs, 1),
                        }) + "\n"
            finally:
                if progress_task is not None:
                    progress_task.cancel()

            transcription_result = await transcription_task
            transcription = transcription_result["transcription"]
            transcription_for_response = transcription
            print(f"🎤 [STREAM] Transcription complete for session {session_id}: '{transcription}' ", flush=True)
        elif typed:
            transcription = typed
            transcription_for_response = typed
            service.sessions[session_id]["transcription"] = transcription
            print(f"🎤 [STREAM] Typed instruction for session {session_id}: '{transcription[:80]}'", flush=True)
        else:
            transcription = NO_INSTRUCTION_DEFAULT
            transcription_for_response = ""
            service.sessions[session_id]["transcription"] = transcription
            print(f"🎤 [STREAM] No-instruction modality for session {session_id}; using default screen-only instruction", flush=True)

        yield json.dumps({
            "transcription": transcription_for_response,
            "stage": "transcription_complete"
        }) + "\n"
        print(f"🎤 [STREAM] Sent transcription chunk for session {session_id}", flush=True)

        print(f"🎤 [STREAM] Getting session data for {session_id}", flush=True)
        session = service.sessions[session_id]
        print(f"🎤 [STREAM] Session {session_id} found, preparing context", flush=True)

        ocr_result = session.get("ocr_result")
        if ocr_result and hasattr(ocr_result, 'cleaned_text'):
            ocr_text = ocr_result.cleaned_text or ""
        else:
            ocr_text = ""

        # Extract app name from session data for application-first context detection
        # Check multiple sources: text_selection, capture_result, app_info.
        app_name = None
        text_selection = session.get("text_selection")
        if text_selection:
            app_name = text_selection.get("application_name")
        if not app_name and "capture_result" in session and isinstance(session["capture_result"], dict):
            app_name = session["capture_result"].get("app_name")
        if not app_name and "app_info" in session:
            app_name = session["app_info"].get("app_name") if isinstance(session["app_info"], dict) else None

        enhancement_result = await service.context_enhancer.enhance_suggestion_context(
            ocr_text, transcription, text_selection=text_selection, app_name=app_name
        )

        logger.info(f"[DEV][OCR] session={session_id}, ocr_full_text_length={len(ocr_text)}")
        logger.info(f"[DEV][OCR] session={session_id}, ocr_preview={ocr_text[:1000]}...")
        if len(ocr_text) > 1000:
            logger.info(f"[DEV][OCR] session={session_id}, ocr_ending={ocr_text[-500:]}")

        enhanced_prompt = enhancement_result["enhanced_prompt"]
        system_prompt = enhancement_result.get("system_prompt")
        logger.info(f"[DEV][LLM Request] session={session_id}, prompt_preview={enhanced_prompt[:2000]}...")
        if len(enhanced_prompt) > 2000:
            logger.info(f"[DEV][LLM Request] session={session_id}, prompt_ending={enhanced_prompt[-500:]}")
        if system_prompt:
            logger.info(f"[DEV][LLM Request] session={session_id}, system_prompt_preview={system_prompt[:500]}...")

        print(f"🎤 [STREAM] Loading reasoning model for session {session_id}, model_id={model_id}", flush=True)
        model = await service.model_usage_service.get_model_for_task(
            capabilities={ModelCapability.REASONING},
            explicit_model_id=model_id
        )

        if not model:
            print(f"🎤 [STREAM] ERROR: No suitable model found for session {session_id}", flush=True)
            yield json.dumps({
                "assistant_output": "[Error: No suitable reasoning model is available. Choose one in Settings.]",
                "complete": True
            }) + "\n"
            return
        model_name = getattr(model, 'model_name', 'unknown')
        print(f"🎤 [STREAM] Model loaded: {model_name} for session {session_id}", flush=True)

        # The system_prompt (Basil identity + the "ignore specialized guidance
        # if the user's request doesn't match the screen" escape hatch) must be
        # a leading system-role message: claude_model._build_streaming_api_params
        # and OpenAI's chat completions API both pull role="system" out of this
        # list. Previously only enhanced_prompt was sent here, so the model never
        # received permission to discard a misclassified specialized prompt.
        paste_mode = resolve_paste_mode()
        if paste_mode == "auto":
            if system_prompt:
                system_prompt = with_paste_instruction(system_prompt)
            else:
                enhanced_prompt = with_paste_instruction(enhanced_prompt)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": enhanced_prompt})
        suggestion_text = ""
        paste_filter = PasteDirectiveFilter()

        print(f"🎤 [STREAM] Sending 'generating_suggestion' stage for session {session_id}", flush=True)
        yield json.dumps({"stage": "generating_suggestion"}) + "\n"
        print(f"🎤 [STREAM] Starting LLM streaming for session {session_id}", flush=True)

        try:
            async for token in model.chat_completion_streaming(messages):
                visible = paste_filter.feed(token)
                if not visible:
                    continue
                suggestion_text += visible
                yield json.dumps({
                    "assistant_output_token": visible,
                    "assistant_output_partial": suggestion_text
                }) + "\n"
            tail = paste_filter.finish()
            if tail:
                suggestion_text += tail
                yield json.dumps({
                    "assistant_output_token": tail,
                    "assistant_output_partial": suggestion_text
                }) + "\n"
            if paste_filter.removed_directive:
                suggestion_text = suggestion_text.rstrip()
        except Exception as streaming_error:
            error_message = str(streaming_error)
            print(f"🎤 [STREAM] LLM streaming error for session {session_id}: {error_message}", flush=True)
            logger.error(f"LLM streaming error for session {session_id}: {error_message}")

            if "rate limit" in error_message.lower() or "429" in error_message:
                user_error = "API rate limit reached. Please wait a moment and try again."
            elif "network" in error_message.lower() or "connection" in error_message.lower():
                user_error = "Network connection issue. Please check your internet and try again."
            elif "authentication" in error_message.lower() or "401" in error_message:
                user_error = "API authentication error. Please check your API key configuration."
            else:
                user_error = f"Error generating output: {error_message}"

            yield json.dumps({
                "error": user_error,
                "assistant_output": f"[Error: {user_error}]",
                "complete": True
            }) + "\n"
            return

        session["suggestion"] = suggestion_text
        session["context_type"] = enhancement_result["context_type"]
        session["metadata"] = enhancement_result["metadata"]

        logger.info(f"[DEV][LLM Response] session={session_id}, full_suggestion={suggestion_text}")

        # Resolve input modality from the branch we took above. NULL is
        # used for the screen-only / NO_INSTRUCTION_DEFAULT case so that
        # neither the Voice nor Text history filter matches it (per the
        # 'two_values_nullable' decision).
        if used_audio_path:
            input_modality = "voice"
        elif typed:
            input_modality = "text"
        else:
            input_modality = None

        try:
            history_svc = get_assistant_output_history_service()
            persist_id = await history_svc.persist_assistant_output(
                output_text=suggestion_text,
                output_type="assistant_session",
                input_modality=input_modality,
                user_request=transcription_for_response,
                context_text=ocr_text[:2000] if ocr_text else None,
                model_name=model_name,
                app_name=app_name,
                context_type=session.get("context_type"),
                recipient=resolve_session_recipient(session.get("context_type"), session.get("metadata"))[0],
            )
            session["persisted_assistant_output_id"] = persist_id
            logger.info(
                f"Persisted AssistantSession id={persist_id} (modality={input_modality or 'n/a'}) "
                f"for session {session_id}"
            )
        except Exception as persist_err:
            logger.error(f"Failed to persist AssistantSession for session {session_id}: {persist_err}")

        yield json.dumps({
            "transcription": transcription_for_response,
            "assistant_output": suggestion_text,
            "paste_decision": paste_filter.decision if paste_mode == "auto" else None,
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
                logger.info(f"Scheduled transcription model unload with {delay}s delay for session: {session_id}")
            except Exception as unloadErr:
                logger.error(f"Failed to schedule model unload: {unloadErr}")

    except Exception as e:
        print(f"🎤 [STREAM] FATAL ERROR in stream_suggestion for session {session_id}: {e}", flush=True)
        print(f"🎤 [STREAM] Exception type: {type(e).__name__}", flush=True)
        import traceback
        print(f"🎤 [STREAM] Traceback: {traceback.format_exc()}", flush=True)
        logger.error(f"Error in streaming suggestion: {e}")
        yield json.dumps({"error": str(e), "complete": True}) + "\n"


async def run_process_audio(
    session_id: str,
    audio_data: Optional[bytes],
    instruction_text: Optional[str],
    model_id: Optional[str],
    service: AssistantSessionService,
    voice_listener_service,
) -> dict:
    """Non-streaming branch of ``/process_audio``.

    Mirrors the streaming branch's modality dispatch: audio bytes go
    through ``service.process_audio_for_suggestion`` (which transcribes
    + generates), typed text bypasses transcription and goes straight
    to ``service.generate_suggestion``, and the no-input modality
    substitutes ``NO_INSTRUCTION_DEFAULT`` as the prompt instruction
    while reporting an empty ``transcription`` to the client.

    Returns the dict that the route handler turns into a
    ``AssistantSessionOutputResponse``. The transcription-model unload is only
    scheduled for the audio modality, since text/no-input never loaded
    the transcription model.
    """
    if session_id not in service.sessions:
        raise ValueError("Session not found")

    typed = (instruction_text or "").strip()

    if audio_data:
        print(f"🎤 [ROUTER] NON-STREAMING PATH (audio): session {session_id}", flush=True)
        result = await service.process_audio_for_suggestion(session_id, audio_data, model_id)

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
            logger.info(f"Scheduled transcription model unload with {delay}s delay for session: {session_id}")
        except Exception as unloadErr:
            logger.error(f"Failed to schedule model unload: {unloadErr}")

        # Parity persistence: the streaming branch always persists; the
        # non-streaming branch did not, so historically only AssistantSession
        # widgets that streamed produced history rows. Mirror the
        # streaming behavior here so non-streaming clients also show
        # up in Assistant Output History.
        await _persist_non_streaming_assistant_output(
            service=service,
            session_id=session_id,
            output_text=result.get("suggestion", "") if isinstance(result, dict) else "",
            transcription_for_response=result.get("transcription", "") if isinstance(result, dict) else "",
            input_modality="voice",
        )

        return result

    # Non-audio modality: skip transcription entirely. Set the session's
    # transcription field directly so generate_suggestion (which reads
    # session["transcription"]) sees the right input, then call it.
    # Report transcription="" to the client for the no-input case so the
    # client can distinguish "user typed nothing" from "user typed text"
    # without inspecting NO_INSTRUCTION_DEFAULT itself.
    if typed:
        service.sessions[session_id]["transcription"] = typed
        transcription_for_response = typed
        non_streaming_modality: Optional[str] = "text"
        print(f"🎤 [ROUTER] NON-STREAMING PATH (text): session {session_id}", flush=True)
    else:
        service.sessions[session_id]["transcription"] = NO_INSTRUCTION_DEFAULT
        transcription_for_response = ""
        non_streaming_modality = None
        print(f"🎤 [ROUTER] NON-STREAMING PATH (no-input): session {session_id}", flush=True)

    suggestion_result = await service.generate_suggestion(session_id, model_id)

    await _persist_non_streaming_assistant_output(
        service=service,
        session_id=session_id,
        output_text=suggestion_result["suggestion"],
        transcription_for_response=transcription_for_response,
        input_modality=non_streaming_modality,
    )

    return {
        "transcription": transcription_for_response,
        "suggestion": suggestion_result["suggestion"],
    }


async def _persist_non_streaming_assistant_output(
    *,
    service: AssistantSessionService,
    session_id: str,
    output_text: str,
    transcription_for_response: str,
    input_modality: Optional[str],
) -> None:
    """Mirror the streaming branch's history persistence for the non-streaming path.

    Pulls OCR text and app name off the session (already populated by the
    route handler before this pipeline runs) so the persisted row matches
    what the streaming branch would write. Failures are logged but never
    propagated -- the user already got their generation result back.
    """
    try:
        session = service.sessions.get(session_id, {})

        ocr_result = session.get("ocr_result")
        if ocr_result and hasattr(ocr_result, "cleaned_text"):
            ocr_text = ocr_result.cleaned_text or ""
        else:
            ocr_text = ""

        app_name = None
        text_selection = session.get("text_selection")
        if text_selection:
            app_name = text_selection.get("application_name")
        if not app_name and "capture_result" in session and isinstance(session["capture_result"], dict):
            app_name = session["capture_result"].get("app_name")
        if not app_name and "app_info" in session:
            app_name = session["app_info"].get("app_name") if isinstance(session["app_info"], dict) else None

        history_svc = get_assistant_output_history_service()
        persist_id = await history_svc.persist_assistant_output(
            output_text=output_text,
            output_type="assistant_session",
            input_modality=input_modality,
            user_request=transcription_for_response,
            context_text=ocr_text[:2000] if ocr_text else None,
            app_name=app_name,
            context_type=session.get("context_type"),
            recipient=resolve_session_recipient(session.get("context_type"), session.get("metadata"))[0],
        )
        service.sessions[session_id]["persisted_assistant_output_id"] = persist_id
        logger.info(
            f"Persisted AssistantSession id={persist_id} (modality={input_modality or 'n/a'}, "
            f"non-streaming) for session {session_id}"
        )
    except Exception as persist_err:
        logger.error(
            f"Failed to persist non-streaming AssistantSession for session {session_id}: {persist_err}"
        )
