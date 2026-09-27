"""Voice-listener-aware wrapper around the transcription model unload helper.

The AssistantSession pipelines call this after each suggestion / refinement
to schedule a delayed unload of the local Whisper model. The wrapper exists
because the voice-listener service shares the same transcription pipeline,
and we must not unload it out from under an active wake-word capture or
instruction-utterance transcription.
"""

import asyncio
import logging
from typing import Optional

from api.services.transcription.local_model.model_unload_scheduler import schedule_model_unload

logger = logging.getLogger(__name__)


def schedule_transcription_model_unload_with_voice_listener_check(
    transcription_service,
    voice_listener_service,
    delay_seconds: int,
    current_task: Optional[asyncio.Task],
    session_id: str,
) -> Optional[asyncio.Task]:
    """
    Enhanced model unload scheduling that respects voice listener state.

    Logic:
    - If voice listener is actively listening: DO NOT schedule unload (transcription needed for agent_tasks)
    - If voice listener is disabled/inactive: Use normal user preference scheduling

    Args:
        transcription_service: The transcription service instance
        voice_listener_service: The voice listener service instance
        delay_seconds: User's preferred delay from settings
        current_task: Existing unload task to cancel if needed
        session_id: Session ID for logging context

    Returns:
        New model unload task or None
    """
    try:
        voice_status = voice_listener_service.get_status()
        is_voice_listener_active = voice_status.get("is_actively_listening", False)
        is_capturing_agent_task = voice_status.get("is_capturing_agent_task", False)

        if is_voice_listener_active or is_capturing_agent_task:
            logger.info(f"🎤 [MODEL_UNLOAD] Voice listener is active (listening: {is_voice_listener_active}, capturing: {is_capturing_agent_task}) - "
                       f"blocking transcription model unload for session: {session_id}")

            if current_task and not current_task.done():
                logger.info(f"🎤 [MODEL_UNLOAD] Cancelling existing model unload task due to active voice listener")
                current_task.cancel()

            return None
        else:
            logger.info(f"🎤 [MODEL_UNLOAD] Voice listener inactive - proceeding with normal model unload scheduling "
                       f"({delay_seconds}s delay) for session: {session_id}")

            return schedule_model_unload(
                transcription_service,
                delay_seconds,
                current_task,
            )

    except Exception as e:
        logger.error(f"🎤 [MODEL_UNLOAD] Error checking voice listener status for session {session_id}: {e}")
        logger.warning(f"🎤 [MODEL_UNLOAD] Falling back to normal model unload scheduling due to error")
        return schedule_model_unload(
            transcription_service,
            delay_seconds,
            current_task,
        )
