"""Wake/hotkey capture flow helpers for agent task orchestration."""

import asyncio
import logging
import time
import uuid

logger = logging.getLogger(__name__)


async def capture_and_process_agent_task(service, wake_phrase: str) -> None:
    """
    Capture agent_task after wake word and process it through the agent-task pipeline.

    Args:
        wake_phrase: The detected wake phrase
    """
    was_canceled = False
    # Acquire the wake-capture lifecycle key BEFORE notifying the frontend
    # so the gate is busy from the moment the user's wake word commits us
    # to a capture session. Released either by audio_routes (transferred
    # to a task key on success, or fully released on no-speech), by the
    # cancellation path below, or by the safety-timeout fallback.
    capture_key = f"wake_capture:{uuid.uuid4()}"
    with service._lifecycle_lock:
        service._active_wake_capture_key = capture_key
    service.acquire_lifecycle(capture_key, source=f"wake_capture:{wake_phrase}")
    capture_key_owned_locally = True
    try:
        service._agent_task_canceled = False  # Reset cancellation flag at start
        logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] Starting agent-task capture after wake word detection for phrase: '{wake_phrase}'...")

        # Notify frontend to show the agent_task capture widget
        # Frontend will decide if this is a follow-up (same as hotkey flow)
        logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] About to notify frontend of agent_task started...")
        await service._notify_agent_task_started()
        logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] Frontend notification sent successfully")

        # Step 1: Capture the agent_task
        logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] About to start agent_task capture...")

        # Check if this is hotkey mode (different timeout behavior)
        hotkey_mode = getattr(service, '_hotkey_mode', False)
        # Single-use semantics: hotkey mode applies only to the current capture
        # Immediately clear the flag so subsequent sessions (e.g., wake-word) are unaffected
        try:
            if hasattr(service, '_hotkey_mode'):
                service._hotkey_mode = False
        except Exception:
            # Non-fatal; proceed without persisting hotkey mode
            service._hotkey_mode = False
        if hotkey_mode:
            logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] Using hotkey mode with extended timeout")
            # Retain capture-active state until client explicitly stops (press-to-stop)
            try:
                if service.main_service:
                    setattr(service.main_service, "_hotkey_client_owned_capture", True)
                    # Ensure backend status shows capturing for the client stop check
                    if hasattr(service.main_service, "_is_capturing_agent_task"):
                        service.main_service._is_capturing_agent_task = True
            except Exception:
                pass

        # Diagnostic-only handshake: stamps when processing_started signals
        # become valid (used for latency logging). The wake-resume decision
        # itself is no longer keyed off this event - lifecycle release is.
        service._capture_handoff_ts = time.monotonic()
        service.processing_started_event.clear()

        agent_task = await service.agent_task_capture_service._capture_agent_task(hotkey_mode=hotkey_mode)
        logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] AgentTask capture completed, result: '{agent_task}'")

        # Check for cancellation after audio capture
        if service._agent_task_canceled:
            logger.info("🎤 [VOICE_CAPTURE_DEBUG] Agent-task processing canceled after audio capture")
            was_canceled = True
            return

        if not agent_task:
            logger.warning("No agent_task captured or request was empty")
            await service._provide_feedback("I didn't hear an agent task. Please try again.")
            # Capture produced nothing actionable - release the wake-capture
            # key so the gate can become idle and the listener can resume.
            service._release_local_capture_key_if_owned(
                capture_key,
                capture_key_owned_locally,
                reason="no_agent_task_captured",
            )
            capture_key_owned_locally = False
            return

        # Check if this is the FFmpeg placeholder response
        if agent_task in ["ffmpeg_complete_awaiting_swift_transcription", "ffmpeg_fallback_complete_awaiting_swift_transcription"]:
            logger.info(f"FFmpeg track completed with placeholder: {agent_task}")
            logger.info("Dual-track system: FFmpeg provided real-time feedback, Swift will handle final transcription")
            # Hand the wake-capture key off to whichever caller next picks it
            # up via consume_active_wake_capture_key() (audio_routes for the
            # Swift upload path). A safety timeout guards against the upload
            # never arriving so the listener can recover.
            service._schedule_wake_capture_safety_release(capture_key)
            capture_key_owned_locally = False
            return

        logger.info(f"AgentTask captured: '{agent_task}'")
        logger.info("Wake word flow: AgentTask detection complete - Swift audio route will handle processing")

        # FFmpeg wake word flow stops here - no agent-task processing
        # Swift audio capture and processing will handle the actual agent-task pipeline
        # (Screenshot data was already synced to main service immediately after capture)
        service._schedule_wake_capture_safety_release(capture_key)
        capture_key_owned_locally = False
        return

    except asyncio.CancelledError:
        logger.info("AgentTask capture was canceled - resuming wake word detection immediately")
        was_canceled = True
    except Exception as e:
        logger.error(f"Error during agent-task capture and processing: {e}", exc_info=True)
        await service._provide_feedback("I encountered an error processing your agent task. Please try again.")
    finally:
        service._agent_task_canceled = False  # Clear cancellation flag

        # If hotkey client-owned capture is active, do NOT resume wake word detection yet.
        # The client will stop capture (second press) and that path will clear state and resume as needed.
        if service.main_service and getattr(service.main_service, "_hotkey_client_owned_capture", False):
            logger.info("🎤 [VOICE_CAPTURE_DEBUG] Hotkey client-owned capture active - deferring resume of wake word detection")
            # Hand the key off to the hotkey stop / audio_routes path with a
            # safety net rather than holding it on this coroutine.
            if capture_key_owned_locally:
                service._schedule_wake_capture_safety_release(capture_key)
                capture_key_owned_locally = False
            return

        if was_canceled:
            # Cancel path: release the key immediately so the lifecycle gate
            # becomes idle and wake/listener can resume right away through
            # the normal release-triggered idle-resume callback.
            service._release_local_capture_key_if_owned(
                capture_key,
                capture_key_owned_locally,
                reason="wake_capture_canceled",
            )
            capture_key_owned_locally = False
            return

        # Normal completion: if we never released or transferred the key
        # above (e.g., an exception path), schedule a safety release so the
        # gate cannot stay busy forever. Successful paths above have
        # already cleared `capture_key_owned_locally` and scheduled the
        # safety net.
        if capture_key_owned_locally:
            logger.info(
                "Wake-triggered capture coroutine exiting with key still owned locally; "
                "scheduling safety release"
            )
            service._schedule_wake_capture_safety_release(capture_key)
            capture_key_owned_locally = False


def release_local_capture_key_if_owned(
    service, capture_key: str, owned_locally: bool, reason: str
) -> None:
    """Release a wake-capture key only if this coroutine still owns it.

    Also clears the shared ``_active_wake_capture_key`` slot so a later
    consumer cannot accidentally pick up a stale key.
    """
    if not owned_locally or not capture_key:
        return
    with service._lifecycle_lock:
        if service._active_wake_capture_key == capture_key:
            service._active_wake_capture_key = None
    service.release_lifecycle(capture_key, reason)
