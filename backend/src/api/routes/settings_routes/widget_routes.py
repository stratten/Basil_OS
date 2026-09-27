"""Widget routes for managing widget-specific settings (transcription, UI preferences)."""

from typing import Dict, Any
from fastapi import APIRouter, HTTPException

from ...core.models.preferences import Preferences, UIPreferences, TranscriptionSettings
from ...core.models.responses import SettingsResponse, UpdateResponse
from ...core.logging.api_logger import api_logger

# Create the widget router (no prefix - endpoints will be under /settings)
router = APIRouter(tags=["widget"])

# Import shared utilities from main settings
def load_preferences() -> Preferences:
    """Load preferences from file or return defaults."""
    from api.core.preferences.preferences_io import load_preferences as _load_preferences
    return _load_preferences()

def save_preferences(preferences: Preferences) -> None:
    """Save preferences to file."""
    from api.core.preferences.preferences_io import save_preferences as _save_preferences
    return _save_preferences(preferences)

def _migrate_widget_settings_if_needed(preferences: Preferences) -> None:
    """
    Migrate widget size and position from UI preferences to transcription settings.
    This is only needed during the transition period as we move these settings.
    """
    try:
        # This handles the case where we need to migrate settings from the old location to the new one
        # Check if the data exists in the UI prefs model
        ui_data = getattr(preferences.ui, "model_dump", lambda: {})()
        
        # Look for the deprecated fields in the UI data
        has_size = "transcription_widget_size" in ui_data
        has_position = "transcription_widget_position" in ui_data
        
        if has_size or has_position:
            api_logger.info("ℹ️ Found legacy widget settings to migrate")
            
            # Copy size if needed
            if has_size and not preferences.transcription.widget_size:
                try:
                    old_size = ui_data.get("transcription_widget_size")
                    if old_size and len(old_size) >= 2:
                        preferences.transcription.widget_size = (old_size[0], old_size[1])
                        api_logger.info(f"✅ Migrated widget size: {old_size}")
                except Exception as e:
                    api_logger.error(f"❌ Error migrating widget size: {e}")
            
            # Copy position if needed
            if has_position and not preferences.transcription.widget_position:
                try:
                    old_position = ui_data.get("transcription_widget_position")
                    if old_position:
                        # Old format might be different, handle conversion
                        if isinstance(old_position, str):
                            # Convert string format if needed
                            parts = old_position.replace("(", "").replace(")", "").split(",")
                            if len(parts) >= 2:
                                x = float(parts[0].strip())
                                y = float(parts[1].strip())
                                # Use default screen ID of 0 if not present
                                preferences.transcription.widget_position = (x, y, 0)
                                api_logger.info(f"✅ Migrated widget position: {(x, y, 0)}")
                        elif isinstance(old_position, (list, tuple)) and len(old_position) >= 2:
                            # Already in tuple/list format
                            x, y = old_position[0], old_position[1]
                            screen_id = old_position[2] if len(old_position) > 2 else 0
                            preferences.transcription.widget_position = (x, y, screen_id)
                            api_logger.info(f"✅ Migrated widget position: {(x, y, screen_id)}")
                except Exception as e:
                    api_logger.error(f"❌ Error migrating widget position: {e}")
            
            # Save the updated preferences
            save_preferences(preferences)
    except Exception as e:
        api_logger.error(f"❌ Error in widget settings migration: {e}", exc_info=True)

# UI Preferences Endpoints

@router.get("/ui", response_model=SettingsResponse[UIPreferences])
async def get_ui_settings() -> SettingsResponse[UIPreferences]:
    """Get UI settings."""
    try:
        preferences = load_preferences()
        return SettingsResponse(settings=preferences.ui)
    except Exception as e:
        api_logger.error(f"❌ Error getting UI settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/ui", response_model=UpdateResponse[UIPreferences])
async def update_ui_settings(settings: Dict[str, Any]) -> UpdateResponse[UIPreferences]:
    """Update UI settings."""
    try:
        api_logger.debug("⚙️ Received UI settings update request")
        api_logger.debug(f"⚙️ Raw settings data: {settings}")
        
        preferences = load_preferences()
        
        # Update only the provided settings
        current_ui_dict = preferences.ui.model_dump()
        current_ui_dict.update(settings)
        
        preferences.ui = UIPreferences(**current_ui_dict)
        save_preferences(preferences)
        
        return UpdateResponse(
            status="updated",
            updated_settings=preferences.ui,
            message="UI settings updated successfully"
        )
    except Exception as e:
        api_logger.error(f"❌ Error updating UI settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# Transcription Widget Endpoints

@router.get("/transcription", response_model=SettingsResponse[TranscriptionSettings])
async def get_transcription_settings() -> SettingsResponse[TranscriptionSettings]:
    """Get consolidated transcription settings."""
    try:
        preferences = load_preferences()
        settings = TranscriptionSettings(
            model_unload_delay=preferences.transcription.model_unload_delay,
            auto_paste=preferences.transcription.auto_paste,
            auto_close_on_paste=preferences.transcription.auto_close_on_paste,
            language=preferences.transcription.language,
            selected_model=preferences.models.transcription_model,
            widget_size=preferences.transcription.widget_size,
            widget_position=preferences.transcription.widget_position,
            is_widget_minimized=preferences.transcription.is_widget_minimized,
            enable_push_to_talk=preferences.transcription.enable_push_to_talk,
            push_to_talk_threshold_ms=preferences.transcription.push_to_talk_threshold_ms,
            auto_retranscribe_on_stop=preferences.transcription.auto_retranscribe_on_stop,
            auto_retranscribe_during_recording=preferences.transcription.auto_retranscribe_during_recording,
            retranscribe_window_seconds=preferences.transcription.retranscribe_window_seconds,
            auto_analyze_on_complete=preferences.transcription.auto_analyze_on_complete,
            auto_analyze_modes=preferences.transcription.auto_analyze_modes,
            auto_analyze_custom_instructions=preferences.transcription.auto_analyze_custom_instructions,
            auto_analyze_timing=preferences.transcription.auto_analyze_timing,
            text_replacements=preferences.transcription.text_replacements,
        )
        return SettingsResponse(settings=settings)
    except Exception as e:
        api_logger.error(f"❌ Error getting transcription settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/transcription", response_model=UpdateResponse[TranscriptionSettings])
async def update_transcription_settings(settings: TranscriptionSettings) -> UpdateResponse[TranscriptionSettings]:
    """Update consolidated transcription settings."""
    try:
        api_logger.debug("⚙️ Received transcription settings update request")
        api_logger.debug(f"⚙️ Raw settings data: {settings.model_dump()}")
        
        preferences = load_preferences()
        previous_model = preferences.models.transcription_model
        requested_model = settings.selected_model
        
        # Update transcription settings
        preferences.transcription.model_unload_delay = settings.model_unload_delay
        preferences.transcription.auto_paste = settings.auto_paste
        preferences.transcription.auto_close_on_paste = settings.auto_close_on_paste
        preferences.transcription.language = settings.language
        preferences.transcription.widget_size = settings.widget_size
        preferences.transcription.widget_position = settings.widget_position
        preferences.transcription.is_widget_minimized = settings.is_widget_minimized
        preferences.transcription.enable_push_to_talk = settings.enable_push_to_talk
        preferences.transcription.push_to_talk_threshold_ms = settings.push_to_talk_threshold_ms
        preferences.transcription.auto_retranscribe_on_stop = settings.auto_retranscribe_on_stop
        preferences.transcription.auto_retranscribe_during_recording = settings.auto_retranscribe_during_recording
        preferences.transcription.retranscribe_window_seconds = settings.retranscribe_window_seconds
        preferences.transcription.auto_analyze_on_complete = settings.auto_analyze_on_complete
        preferences.transcription.auto_analyze_modes = settings.auto_analyze_modes
        preferences.transcription.auto_analyze_custom_instructions = settings.auto_analyze_custom_instructions
        preferences.transcription.auto_analyze_timing = settings.auto_analyze_timing
        preferences.transcription.text_replacements = settings.text_replacements

        # Update model settings
        preferences.models.transcription_model = requested_model
        
        # Log the updated widget size/position for debugging
        api_logger.debug(f"📏 Updated widget size: {settings.widget_size}")
        api_logger.debug(f"📍 Updated widget position: {settings.widget_position}")
        
        save_preferences(preferences)

        # Runtime model swap for settings-UI changes:
        # when the selected transcription model changes, we must unload
        # the currently-loaded backend and load the new one immediately.
        # Without this, the process can keep serving the old in-memory
        # model until a restart/coincidental unload, which is exactly
        # the mismatch the user reported.
        if requested_model != previous_model:
            from ...dependencies import resolve_transcription_service

            api_logger.info(
                f"🔁 Transcription model changed via settings UI: "
                f"'{previous_model}' -> '{requested_model}'"
            )

            # 1) Unload the service that was active under the old
            # preference. We do this before mutating anything else in
            # runtime state to prevent mixed backend leftovers.
            try:
                old_service = resolve_transcription_service()
                api_logger.info(
                    f"🧹 Unloading previous transcription service: "
                    f"{type(old_service).__name__}"
                )
                old_service.unload_model()
            except Exception as unload_exc:
                api_logger.warning(
                    f"⚠️ Failed to cleanly unload previous transcription "
                    f"service during settings swap: {unload_exc}"
                )

            # 2) Resolve again under the new preference and load.
            try:
                new_service = resolve_transcription_service()
                api_logger.info(
                    f"📥 Loading new transcription service: "
                    f"{type(new_service).__name__}"
                )
                new_service.load_model()
                if not new_service.is_model_loaded():
                    raise RuntimeError(
                        "Selected transcription model did not report as loaded"
                    )
            except Exception as load_exc:
                # If load fails, restore previous preference and attempt
                # best-effort recovery so the app is not left in a broken
                # "selected but unusable" state.
                api_logger.error(
                    f"❌ Failed to load newly selected transcription model "
                    f"'{requested_model}': {load_exc}",
                    exc_info=True,
                )
                try:
                    rollback = load_preferences()
                    rollback.models.transcription_model = previous_model
                    save_preferences(rollback)
                    recovered_service = resolve_transcription_service()
                    recovered_service.load_model()
                    api_logger.warning(
                        f"↩️ Reverted transcription model selection back to "
                        f"'{previous_model}' after load failure"
                    )
                except Exception as rollback_exc:
                    api_logger.error(
                        f"❌ Rollback after transcription model load failure "
                        f"also failed: {rollback_exc}",
                        exc_info=True,
                    )
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Failed to load transcription model '{requested_model}'. "
                        f"Reverted to previous model '{previous_model}'."
                    ),
                )
        
        return UpdateResponse(
            status="updated",
            updated_settings=preferences.transcription,
            message="Transcription settings updated successfully"
        )
    except Exception as e:
        api_logger.error(f"❌ Error updating transcription settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

