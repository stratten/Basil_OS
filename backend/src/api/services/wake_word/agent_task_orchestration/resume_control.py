"""Wake/listening resume helpers for agent task orchestration."""

import logging

logger = logging.getLogger(__name__)


async def resume_wake_word_detection(service) -> None:
    """
    Resume wake word detection after agent-task processing.
    Delegates to main service.
    """
    logger.info("🔄 [RESUME_DEBUG] _resume_wake_word_detection() called in orchestration service")
    try:
        if service.main_service:
            logger.info("🔄 [RESUME_DEBUG] Delegating to main service _resume_wake_word_detection()")
            service.main_service._resume_wake_word_detection()
            logger.info("✅ Wake word detection resumed via main service")
        else:
            logger.error("❌ Cannot resume wake word detection - main service not available")

    except Exception as e:
        logger.error(f"Error resuming wake word detection: {e}")


async def resume_listening_if_enabled(service) -> None:
    """
    Resume voice listening if it's enabled by user settings.
    Delegates to main service and lets start_listening() handle the state logic.

    IMPORTANT: Does NOT resume if an agent task is still processing in the frontend.
    """
    try:
        # If hotkey capture is active, do nothing here. The stop endpoint will manage state.
        if service.main_service and getattr(service.main_service, "_hotkey_client_owned_capture", False):
            logger.info("🎤 [VOICE_CAPTURE_DEBUG] Hotkey client-owned capture active - skipping backend resume")
            return

        # Check if widget is still processing before resuming
        widget_state = service.query_widget_state_sync(timeout_seconds=0.2)
        if widget_state.get('is_processing', False):
            logger.info("🔄 [LISTENER_RESUME] Widget still processing agent task - deferring listener resume until agent task completes")
            logger.info("🔄 [LISTENER_RESUME] Listener will be re-enabled when result widget closes or agent task completes")
            return

        if service.main_service and hasattr(service.main_service, '_is_globally_enabled_by_user'):
            if service.main_service._is_globally_enabled_by_user:
                try:
                    # Reset the agent-task capture flag first to ensure start_listening() can proceed
                    if hasattr(service.main_service, '_is_capturing_agent_task'):
                        service.main_service._is_capturing_agent_task = False
                        logger.info("🔧 Reset agent-task capture flag before resuming listening")

                    # Call start_listening and let it handle the state logic
                    service.main_service.start_listening()
                    logger.info("✅ Voice listening resumed via main service")
                except Exception as e:
                    logger.error(f"❌ Error restarting listening via main service: {e}")
            else:
                logger.info("Voice listening not resumed - disabled by user settings")
        else:
            logger.error("❌ Cannot resume listening - main service not available or missing attributes")

    except Exception as e:
        logger.error(f"Error resuming listening: {e}")
