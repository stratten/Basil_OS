"""Voice listener wake word routes for wake word callback and agent-task capture control."""

from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Dict, Any
import asyncio
import logging

from api.dependencies import get_wake_word_service
from api.services.wake_word import WakeWordService

logger = logging.getLogger(__name__)

# Create the wake word router (no prefix - endpoints will be under /api/v1/voice-listener)
router = APIRouter(tags=["voice-listener-wake-word"])

# Endpoints

@router.post("/wake-word-callback", summary="Trigger Wake Word Callback (Hotkey or Voice)")
async def trigger_wake_word_callback(
    request: Request,
    service: WakeWordService = Depends(get_wake_word_service)
) -> Dict[str, Any]:
    """
    Trigger the same wake word callback that "Hey Basil" uses.
    """
    try:
        # Parse request body
        body = await request.json()
        wake_phrase = body.get("wake_phrase", "hotkey_initiated")
        hotkey_mode = body.get("hotkey_mode", False)
        
        logger.info(f"Triggering wake word callback for phrase: {wake_phrase}")
        
        # Call the exact same wake word manager method that "Hey Basil" triggers
        if service.wake_word_manager:
            # Set hotkey mode flag for extended timeout
            if hotkey_mode and service.agent_task_orchestration_service:
                service.agent_task_orchestration_service._hotkey_mode = True
            
            # CRITICAL: Sync the main service flag before calling wake word callback
            # This ensures the status endpoint returns the correct state
            service._is_capturing_agent_task = True
            
            # Hotkey callbacks arrive on the FastAPI event loop, but the wake-word
            # manager performs a synchronous frontend state query that must wait
            # off-loop while the WebSocket response is handled on the main loop.
            if hotkey_mode:
                await asyncio.to_thread(
                    service.wake_word_manager._handle_wake_word_detected,
                    wake_phrase,
                )
            else:
                service.wake_word_manager._handle_wake_word_detected(wake_phrase)
            
            return {"success": True, "message": f"Wake word callback triggered for: {wake_phrase}"}
        else:
            raise HTTPException(status_code=503, detail="Wake word manager not available")
        
    except Exception as e:
        logger.error(f"Error triggering wake word callback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error triggering wake word callback: {str(e)}")

@router.post("/stop-agent-task-capture", summary="Stop AgentTask Capture")
async def stop_agent_task_capture(
    request: Request,
    service: WakeWordService = Depends(get_wake_word_service)
) -> Dict[str, Any]:
    """
    Stop current agent_task capture by ending streaming sessions.
    """
    try:
        # Parse request body
        body = await request.json()
        reason = body.get("reason", "hotkey_stop")
        
        logger.info(f"Stopping agent_task capture, reason: {reason}")
        
        # End all active streaming sessions (same as 2-second timeout)
        try:
            from api.routes.websocket_routes.agent_task_streaming import streaming_manager
            sessions_ended = 0
            for session_id, processor in list(streaming_manager.active_sessions.items()):
                if processor and not processor.is_capture_complete():
                    logger.info(f"Ending streaming session {session_id} via {reason}")
                    await processor._end_capture(reason)
                    sessions_ended += 1

            # Clear capture flags regardless of session count to support hotkey-mode no-op
            service._is_capturing_agent_task = False
            service._agent_task_cancelled = False
            try:
                orchestration = getattr(service, "agent_task_orchestration_service", None)
                if orchestration is not None and hasattr(orchestration, "consume_active_wake_capture_key"):
                    wake_capture_key = orchestration.consume_active_wake_capture_key()
                    if wake_capture_key:
                        orchestration.release_lifecycle(wake_capture_key, f"{reason}_capture_stopped")
                        logger.info(f"Released wake-capture lifecycle key after {reason}: {wake_capture_key}")
            except Exception as lifecycle_error:
                logger.warning(f"Failed to release wake-capture lifecycle key after {reason}: {lifecycle_error}")
            # Clear hotkey client-owned flag so orchestration can resume wake word detection next time
            try:
                if hasattr(service, "_hotkey_client_owned_capture"):
                    service._hotkey_client_owned_capture = False
            except Exception:
                pass
            logger.info(f"Cleared agent_task capture flags after stopping {sessions_ended} sessions")

            msg = (
                f"AgentTask capture stopped - {sessions_ended} sessions ended"
                if sessions_ended > 0
                else "No active streaming sessions; capture state cleared"
            )
            return {
                "success": True,
                "message": msg,
                "sessions_ended": sessions_ended
            }
        except Exception as e:
            # Be tolerant in hotkey-mode: even if streaming manager isn't available,
            # clear flags so UI can proceed.
            logger.warning(f"Graceful stop without streaming manager: {e}; clearing capture flags only")
            try:
                service._is_capturing_agent_task = False
                service._agent_task_cancelled = False
                orchestration = getattr(service, "agent_task_orchestration_service", None)
                if orchestration is not None and hasattr(orchestration, "consume_active_wake_capture_key"):
                    wake_capture_key = orchestration.consume_active_wake_capture_key()
                    if wake_capture_key:
                        orchestration.release_lifecycle(wake_capture_key, f"{reason}_capture_stopped")
                        logger.info(f"Released wake-capture lifecycle key after graceful {reason}: {wake_capture_key}")
                if hasattr(service, "_hotkey_client_owned_capture"):
                    service._hotkey_client_owned_capture = False
            except Exception:
                pass
            return {
                "success": True,
                "message": "No active streaming sessions; capture state cleared (graceful)",
                "sessions_ended": 0
            }
        
    except Exception as e:
        logger.error(f"Error stopping agent-task capture: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error stopping agent-task capture: {str(e)}")

