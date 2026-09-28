"""Auth routes for managing authentication and authorization settings."""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core.models.preferences import Preferences, AuthSettings, APIKeyPreference
from ...core.models.responses import SettingsResponse, UpdateResponse, StatusResponse
from ...core.logging.api_logger import api_logger

# Create the auth router
router = APIRouter(prefix="/auth", tags=["auth"])

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
class AuthSettingsUpdate(BaseModel):
    """Model for updating auth settings from Swift client.
    
    Only api_key_preference is required. If is_authenticated or user_email are not provided,
    existing values are preserved. This allows APIKeyPreferenceManager to update ONLY the
    preference without needing to access AuthService (which would trigger keychain prompts).
    """
    api_key_preference: str = Field(description="How to access API models: basil_cloud, own_keys, or local. app_keys and trial are accepted legacy aliases.")
    is_authenticated: Optional[bool] = Field(default=None, description="Whether user is authenticated with Basil service. If None, existing value is preserved.")
    user_email: Optional[str] = Field(default=None, description="Authenticated user's email. If None, existing value is preserved.")

class AuthTokenUpdate(BaseModel):
    """Model for updating the auth access token."""
    access_token: str = Field(description="JWT access token from auth service")

# Endpoints

@router.get("", response_model=SettingsResponse[AuthSettings])
async def get_auth_settings() -> SettingsResponse[AuthSettings]:
    """Get current auth settings."""
    try:
        preferences = load_preferences()
        return SettingsResponse(settings=preferences.auth)
    except Exception as e:
        api_logger.error(f"❌ Error getting auth settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.put("", response_model=UpdateResponse[AuthSettings])
async def update_auth_settings(settings: AuthSettingsUpdate) -> UpdateResponse[AuthSettings]:
    """Update auth settings."""
    try:
        api_logger.debug("🔐 Received auth settings update request")
        api_logger.debug(f"🔐 Raw settings data: {settings.model_dump()}")
        
        preferences = load_preferences()
        
        # Validate and update api_key_preference. Legacy cloud values are normalized
        # so persisted preferences only expose the current Basil Cloud mode.
        try:
            requested_preference = APIKeyPreference(settings.api_key_preference)
            if requested_preference in {APIKeyPreference.APP_KEYS, APIKeyPreference.TRIAL}:
                requested_preference = APIKeyPreference.BASIL_CLOUD
            preferences.auth.api_key_preference = requested_preference
        except ValueError:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid api_key_preference: {settings.api_key_preference}. Must be one of: basil_cloud, own_keys, local"
            )
        
        # Only update auth fields if explicitly provided - preserve existing values otherwise
        # This allows preference-only updates without requiring AuthService access
        if settings.is_authenticated is not None:
            preferences.auth.is_authenticated = settings.is_authenticated
        if settings.user_email is not None:
            preferences.auth.user_email = settings.user_email
        
        save_preferences(preferences)
        
        api_logger.info(f"🔐 Auth settings updated: preference={settings.api_key_preference}, authenticated={preferences.auth.is_authenticated}")
        
        return UpdateResponse(
            status="updated",
            updated_settings=preferences.auth,
            message="Auth settings updated successfully."
        )
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Error updating auth settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# Auth token management - allows Swift client to pass access token for auth service routing

@router.post("/token", response_model=StatusResponse)
async def set_auth_token(token_update: AuthTokenUpdate) -> StatusResponse:
    """Set the access token for auth service routing.
    
    Called by Swift client when user authenticates or on app startup
    if user is already authenticated.
    """
    try:
        from ...core.services.model_service import set_auth_access_token
        set_auth_access_token(token_update.access_token)
        
        api_logger.info("🔐 Auth access token received from client")
        
        return StatusResponse(
            status="success",
            message="Access token set successfully."
        )
    except Exception as e:
        api_logger.error(f"❌ Error setting auth token: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/token", response_model=StatusResponse)
async def clear_auth_token() -> StatusResponse:
    """Clear the access token (called on logout)."""
    try:
        from ...core.services.model_service import clear_auth_access_token
        clear_auth_access_token()
        
        api_logger.info("🔐 Auth access token cleared")
        
        return StatusResponse(
            status="success",
            message="Access token cleared."
        )
    except Exception as e:
        api_logger.error(f"❌ Error clearing auth token: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
