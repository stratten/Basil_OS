"""
Router for WhisperLive transcription service.

This router handles initialization and routes for the WhisperLive service,
which provides real-time transcription capabilities.
"""

import logging

from fastapi import APIRouter

from api.core.models.preferences import Preferences
from api.services.live_transcription.whisper_live_service import WhisperLiveService


logger = logging.getLogger(__name__)

# Create a router
router = APIRouter(
    prefix="/whisper-live",
    tags=["whisper-live"],
    responses={404: {"description": "Not found"}},
)

# Initialize the WhisperLive service
whisper_live_service = WhisperLiveService()

# Global service initialized flag
is_registered = False


@router.on_event("startup")
async def startup_event():
    """Initialize the WhisperLive router and register routes."""
    global is_registered
    
    if is_registered:
        return
    
    logger.info("Registering WhisperLive service...")
    
    try:
        # Get current preferences
        preferences = Preferences.load()

        # The live notetaker's local engine is always Whisper Base. It is not a user setting: Parakeet and the other local models are for file, dictation and post-meeting transcription only, and `preferences.models.transcription_model` (the model those use) must never reach the live path. Cloud streaming engines are chosen per recording through the `live_engine` socket choice, not here.
        selected_model = "Base"

        logger.info(f"WhisperLive: live transcription model = '{selected_model}' (fixed; it does not follow the saved transcription model).")

        config = {
            "model": selected_model,
            "language": preferences.behavior.transcription_language or "en",
            "diarization": False,  # Disable for live transcription; only use in post-processing
            "vad": True,  # Always enable Voice Activity Detection
            "transcription": True,
            "pcm_input": True,  # Swift client sends pre-processed PCM audio
        }
        
        # Register with the application
        from api.main import app
        success = await whisper_live_service.register_with_app(app, **config)
        
        if success:
            logger.info("WhisperLive service registered successfully")
            is_registered = True
        else:
            logger.error("Failed to register WhisperLive service")
            
    except Exception as e:
        logger.error(f"Error registering WhisperLive service: {e}", exc_info=True)


@router.on_event("shutdown")
async def shutdown_event():
    """Shut down the WhisperLive service."""
    logger.info("Shutting down WhisperLive service...")
    await whisper_live_service.shutdown()


# This router doesn't need additional endpoints since the WebSocket and web
# interface endpoints are registered directly by the service during initialization
