"""Hotkeys routes for managing hotkey settings."""

from typing import Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...core.models.preferences import Preferences, HotkeySettings, HotkeyBinding
from ...core.models.responses import SettingsResponse, UpdateResponse
from ...core.logging.api_logger import api_logger

# Create the hotkeys router
router = APIRouter(prefix="/hotkeys", tags=["hotkeys"])

# Import shared utilities from main settings
def load_preferences() -> Preferences:
    """Load preferences from file or return defaults."""
    from api.core.preferences.preferences_io import load_preferences as _load_preferences
    return _load_preferences()

def save_preferences(preferences: Preferences) -> None:
    """Save preferences to file."""
    from api.core.preferences.preferences_io import save_preferences as _save_preferences
    return _save_preferences(preferences)

def enforce_hotkey_defaults(prefs: Preferences) -> bool:
    """Enforce default values for any missing or disabled hotkeys.
    Returns True if any changes were made that need to be saved."""
    default_settings = HotkeySettings()
    changed = False
    
    # For each hotkey field in HotkeySettings
    for field_name, field in HotkeySettings.model_fields.items():
        current_binding = getattr(prefs.hotkeys, field_name)
        default_binding = getattr(default_settings, field_name)
        
        # If the binding is disabled or empty, use the default
        if not current_binding.enabled or not current_binding.key:
            setattr(prefs.hotkeys, field_name, default_binding)
            changed = True
            api_logger.debug(f"🔑 Enforcing default for {field_name}: {default_binding.model_dump()}")
    
    return changed

# Models
class HotkeySettingsUpdate(BaseModel):
    """Model for updating hotkey settings.

    NOTE: `get_suggestions` (legacy F9) and `enhanced_suggestions`
    (legacy F10) were removed as part of the assistant-session unification. Both
    modalities now live behind the unified `assistant_session` hotkey with an
    in-widget speak/type toggle, so the settings PUT payload no longer
    accepts those fields. The legacy `insert_suggestion` field was
    renamed to `insert_assistant_output` in the team identity rename rollout.
    """
    capture_screen: Dict[str, Any]
    transcribe_audio: Dict[str, Any]
    streaming_transcription: Dict[str, Any]
    conversation_toggle: Dict[str, Any]
    insert_assistant_output: Dict[str, Any]
    assistant_session: Dict[str, Any]
    agent_task: Dict[str, Any]
    home_board_toggle: Dict[str, Any]

# Endpoints

@router.get("", response_model=SettingsResponse[Dict[str, HotkeyBinding]])
async def get_hotkey_bindings() -> SettingsResponse[Dict[str, HotkeyBinding]]:
    """Get current hotkey bindings."""
    try:
        api_logger.info("🔑 API: GET /hotkeys called")
        prefs = load_preferences()
        api_logger.info(f"🔑 API: Loaded preferences with {len(prefs.hotkeys)} hotkey bindings")
        
        # Log each hotkey being returned
        for key, binding in prefs.hotkeys.items():
            api_logger.debug(f"🔑 API RESPONSE: {key} -> {binding.key} (enabled: {binding.enabled})")
        
        api_logger.info(f"🔑 API: Returning hotkeys: {list(prefs.hotkeys.keys())}")
        return SettingsResponse(settings=prefs.hotkeys)
    except Exception as e:
        api_logger.error(f"❌ API: Error getting hotkey bindings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.put("", response_model=UpdateResponse[HotkeySettings])
async def update_hotkey_settings(settings: HotkeySettingsUpdate) -> UpdateResponse[HotkeySettings]:
    """Update hotkey settings."""
    try:
        api_logger.info("🔑 API: PUT /hotkeys called")
        api_logger.debug(f"🔑 API: Raw settings data: {settings.model_dump()}")
        
        preferences = load_preferences()
        api_logger.info(f"🔑 API: Loaded current preferences with {len(preferences.hotkeys)} hotkeys")
        
        # Update hotkeys
        api_logger.info("🔑 API: Converting HotkeySettingsUpdate to HotkeySettings")
        hotkey_settings = HotkeySettings(**settings.model_dump())
        api_logger.debug(f"🔑 API: Created HotkeySettings with fields: {list(hotkey_settings.model_fields.keys())}")
        
        # Convert HotkeySettings object to Dict[str, HotkeyBinding] as expected by preferences.hotkeys
        api_logger.info("🔑 API: Converting HotkeySettings to Dict[str, HotkeyBinding]")
        old_hotkeys = dict(preferences.hotkeys)  # Keep a copy for comparison
        preferences.hotkeys = {
            field_name: getattr(hotkey_settings, field_name) 
            for field_name in hotkey_settings.model_fields
        }
        
        api_logger.info(f"🔑 API: Updated preferences.hotkeys with {len(preferences.hotkeys)} bindings")
        
        # Log changes
        for key in preferences.hotkeys:
            old_binding = old_hotkeys.get(key)
            new_binding = preferences.hotkeys[key]
            if old_binding != new_binding:
                old_key = old_binding.key if old_binding else "None"
                api_logger.info(f"🔑 API CHANGE: {key}: {old_key} -> {new_binding.key}")
        
        api_logger.info("🔑 API: Saving updated preferences")
        save_preferences(preferences)
        api_logger.info("✅ Successfully saved new hotkey settings")
        
        return UpdateResponse(
            status="updated",
            updated_settings=hotkey_settings,
            message="Hotkey settings updated successfully"
        )
    except Exception as e:
        api_logger.error(f"❌ Error updating hotkey settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

