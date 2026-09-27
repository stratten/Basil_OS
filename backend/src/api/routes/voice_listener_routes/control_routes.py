"""Voice listener control routes for service status and lifecycle management."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
import logging

from api.dependencies import get_wake_word_service
from api.services.wake_word import WakeWordService

logger = logging.getLogger(__name__)

# Create the control router (no prefix - endpoints will be under /api/v1/voice-listener)
router = APIRouter(tags=["voice-listener-control"])

# Response Models

class VoiceListenerStatusResponse(BaseModel):
    voice_listener_enabled: bool
    is_actively_listening: bool
    is_capturing_agent_task: bool
    detector_model_loaded: bool
    detector_models: list[str]
    agent_task_processor_ready: bool

class VoiceListenerControlResponse(BaseModel):
    success: bool
    message: str
    status: VoiceListenerStatusResponse

# Endpoints

@router.get("/status", response_model=VoiceListenerStatusResponse, summary="Get Voice Listener Status")
async def get_service_status(service: WakeWordService = Depends(get_wake_word_service)) -> VoiceListenerStatusResponse:
    """
    Retrieves the current operational status of the voice listener service,
    including whether it's actively listening, agent-task processing state, and model status.
    """
    try:
        status_data = service.get_status()
        return VoiceListenerStatusResponse(**status_data)
    except NotImplementedError:
        raise HTTPException(status_code=503, detail="VoiceListenerService not available. Setup required.")
    except Exception as e:
        logger.error(f"Error retrieving voice listener status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error retrieving voice listener status: {str(e)}")

@router.post("/start", response_model=VoiceListenerControlResponse, summary="Start Voice Listener")
async def start_voice_listener(service: WakeWordService = Depends(get_wake_word_service)) -> VoiceListenerControlResponse:
    """
    Manually start the voice listener service.
    Note: The service must be enabled in settings to start successfully.
    """
    try:
        if not service.current_settings.voice_listener_enabled:
            raise HTTPException(
                status_code=400, 
                detail="Voice listener is disabled in settings. Enable it first before starting."
            )
        
        service.start_listening()
        status_data = service.get_status()
        
        success = status_data.get("is_actively_listening", False)
        message = "Voice listener started successfully" if success else "Voice listener failed to start"
        
        return VoiceListenerControlResponse(
            success=success,
            message=message,
            status=VoiceListenerStatusResponse(**status_data)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting voice listener: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error starting voice listener: {str(e)}")

@router.post("/stop", response_model=VoiceListenerControlResponse, summary="Stop Voice Listener")
async def stop_voice_listener(service: WakeWordService = Depends(get_wake_word_service)) -> VoiceListenerControlResponse:
    """
    Manually stop the voice listener service.
    """
    try:
        service.stop_listening()
        status_data = service.get_status()
        
        success = not status_data.get("is_actively_listening", True)
        message = "Voice listener stopped successfully" if success else "Voice listener may still be running"
        
        return VoiceListenerControlResponse(
            success=success,
            message=message,
            status=VoiceListenerStatusResponse(**status_data)
        )
    except Exception as e:
        logger.error(f"Error stopping voice listener: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error stopping voice listener: {str(e)}")

@router.get("/health", response_model=Dict[str, Any], summary="Health Check")
async def health_check(service: WakeWordService = Depends(get_wake_word_service)) -> Dict[str, Any]:
    """
    Perform a health check on the voice listener service and its components.
    """
    try:
        status = service.get_status()
        
        # Determine overall health
        health_issues = []
        
        if not status.get("detector_model_loaded", False):
            health_issues.append("Wake word detector model not loaded")
        
        if not status.get("agent_task_processor_ready", False):
            health_issues.append("Agent-task processor not ready")
        
        is_healthy = len(health_issues) == 0
        
        return {
            "healthy": is_healthy,
            "status": "ok" if is_healthy else "degraded",
            "issues": health_issues,
            "service_status": status,
            "timestamp": None  # Could add timestamp if needed
        }
    except Exception as e:
        logger.error(f"Error during health check: {e}", exc_info=True)
        return {
            "healthy": False,
            "status": "error",
            "issues": [f"Health check failed: {str(e)}"],
            "service_status": None
        }

