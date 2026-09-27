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

        # Resolve the live transcription model:
        # - For Whisper / Distil-Whisper, the CTranslate2 large-model
        #   downgrade in `config_mapper.map_basil_config_to_upstream`
        #   already protects CPU-only Macs from picking an unusably
        #   large model -- so we no longer need to hard-code "Base"
        #   here and can honor the user's preferred Whisper model.
        # - For NVIDIA Parakeet (ONNX), the same config_mapper bypasses
        #   the Whisper downgrade entirely because Parakeet runs on
        #   CPU/CoreML/CUDA via onnxruntime regardless of MPS, so the
        #   user's selected Parakeet model flows straight through.
        #
        # The selection lives in `preferences.models.transcription_model`
        # (display name as shown in the model registry); we fall back to
        # "Base" only if the preference is unset or unparseable, matching
        # the prior implicit default.
        selected_model = "Base"
        try:
            preferred = preferences.models.transcription_model
            if isinstance(preferred, str) and preferred.strip():
                selected_model = preferred.strip()
        except Exception as pref_err:
            logger.debug(
                f"WhisperLive: could not read preferred transcription model "
                f"({pref_err}); defaulting to 'Base'."
            )

        logger.info(
            f"WhisperLive: live transcription model selected = '{selected_model}' "
            f"(downgrade rules apply per config_mapper)."
        )

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
