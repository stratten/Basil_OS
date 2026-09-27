"""Voice listener settings routes for managing wake-word listener configuration."""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from ...core.models.preferences import Preferences
from ...core.models.responses import SettingsResponse, UpdateResponse
from ...core.logging.api_logger import api_logger
from api.dependencies import get_wake_word_service
from api.services.wake_word import WakeWordService

# Create the voice listener settings router (no prefix - endpoints will be under /settings)
router = APIRouter(tags=["voice-listener-settings"])

# Import shared utilities from main settings
def load_preferences() -> Preferences:
    """Load preferences from file or return defaults."""
    from api.core.preferences.preferences_io import load_preferences as _load_preferences
    return _load_preferences()

def save_preferences(preferences: Preferences) -> None:
    """Save preferences to file."""
    from api.core.preferences.preferences_io import save_preferences as _save_preferences
    return _save_preferences(preferences)

# Models

class VoiceListenerSettingsUpdate(BaseModel):
    """Model for updating voice listener enabled state."""
    voice_listener_enabled: bool = Field(description="Whether voice listener is enabled")

class VoiceListenerSettingsResponse(BaseModel):
    """Response model for voice listener settings."""
    voice_listener_enabled: bool

# Voice Listener Enable/Disable Endpoints

@router.get("/voice-listener/settings", response_model=SettingsResponse[VoiceListenerSettingsResponse])
async def get_voice_listener_settings(
    service: WakeWordService = Depends(get_wake_word_service)
) -> SettingsResponse[VoiceListenerSettingsResponse]:
    """Get voice listener enabled state."""
    try:
        if not service:
            # If service not available, read from preferences directly
            preferences = load_preferences()
            # Note: There's no voice_listener_enabled in preferences yet
            # We'll return False as default for now
            return SettingsResponse(
                settings=VoiceListenerSettingsResponse(voice_listener_enabled=False)
            )
        
        current_settings = service.current_settings
        return SettingsResponse(
            settings=VoiceListenerSettingsResponse(
                voice_listener_enabled=current_settings.voice_listener_enabled
            )
        )
    except Exception as e:
        api_logger.error(f"❌ Error getting voice listener settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/voice-listener/settings", response_model=UpdateResponse[VoiceListenerSettingsResponse])
async def update_voice_listener_settings(
    settings: VoiceListenerSettingsUpdate,
    service: WakeWordService = Depends(get_wake_word_service)
) -> UpdateResponse[VoiceListenerSettingsResponse]:
    """Update voice listener enabled state."""
    try:
        api_logger.debug("⚙️ Received voice listener settings update request")
        api_logger.debug(f"⚙️ Raw settings data: {settings.model_dump()}")
        
        if not service:
            raise HTTPException(
                status_code=503,
                detail="Voice listener service not available. Setup required."
            )
        
        # Update the voice listener enabled state
        service.set_voice_listener_enabled(enabled=settings.voice_listener_enabled)
        
        # Get updated settings
        updated_settings = service.current_settings
        
        return UpdateResponse(
            status="updated",
            updated_settings=VoiceListenerSettingsResponse(
                voice_listener_enabled=updated_settings.voice_listener_enabled
            ),
            message="Voice listener settings updated successfully"
        )
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Error updating voice listener settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

