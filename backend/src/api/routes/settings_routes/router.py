"""Settings router for managing application preferences."""

import logging
import sys

from fastapi import APIRouter, HTTPException, Request

from api.core.logging.api_logger import api_logger
from api.core.models.preferences import (
    BehaviorSettings,
    GeneralSettings,
    ModelSettings,
    Preferences,
)
from api.core.models.responses import SettingsResponse, StatusResponse, UpdateResponse
from api.core.preferences.preferences_io import load_preferences, save_preferences

from .activity_capture_routes import router as activity_capture_router
from .ambient_suggestions_routes import router as ambient_suggestions_router
from .meeting_detection_routes import router as meeting_detection_settings_router
from .api_models_routes import router as api_models_router
from .appearance_routes import router as appearance_router
from .auth_routes import router as auth_router
from .browser_automation_routes import router as browser_automation_router
from .hotkeys_routes import router as hotkeys_router
from .models import (
    AggregatedSettingsResponse,
    BehaviorSettingsUpdate,
    GeneralSettingsUpdate,
    ModelSettingsUpdate,
)
from .memory_intelligence_routes import router as memory_intelligence_router
from .transcription_model_swap_route import router as transcription_model_swap_router
from .voice_listener_settings_routes import router as voice_listener_settings_router
from .voice_routes import router as voice_router
from .widget_routes import router as widget_router
from .zettel_routes import router as zettel_router


# Create the main router with prefix
router = APIRouter(prefix="/settings", tags=["settings"])

# Include all subrouters
router.include_router(api_models_router)
router.include_router(hotkeys_router)
router.include_router(voice_router)
router.include_router(widget_router)
router.include_router(appearance_router)
router.include_router(activity_capture_router)
router.include_router(ambient_suggestions_router)
router.include_router(meeting_detection_settings_router)
router.include_router(browser_automation_router)
router.include_router(auth_router)
router.include_router(memory_intelligence_router)
router.include_router(voice_listener_settings_router)
router.include_router(transcription_model_swap_router)
router.include_router(zettel_router)


# Core settings endpoints

@router.get("/", response_model=AggregatedSettingsResponse)
async def get_settings() -> AggregatedSettingsResponse:
    """Get all application settings."""
    try:
        preferences = load_preferences()
        return AggregatedSettingsResponse(
            hotkeys={key: binding.model_dump() for key, binding in preferences.hotkeys.items()},
            behavior=preferences.behavior.model_dump(),
            models=preferences.models.model_dump()
        )
    except Exception as e:
        api_logger.error(f"Error getting settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/behavior", response_model=SettingsResponse[BehaviorSettings])
async def get_behavior_settings() -> SettingsResponse[BehaviorSettings]:
    """Get current behavior settings."""
    try:
        preferences = load_preferences()
        return SettingsResponse(settings=preferences.behavior)
    except Exception as e:
        api_logger.error(f"❌ Error getting behavior settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/behavior", response_model=UpdateResponse[BehaviorSettings])
async def update_behavior_settings(settings: BehaviorSettingsUpdate) -> UpdateResponse[BehaviorSettings]:
    """Update behavior settings."""
    try:
        api_logger.debug("⚙️ Received behavior settings update request")
        updates = settings.model_dump(exclude_unset=True)
        api_logger.debug(f"⚙️ Raw settings data: {updates}")
        preferences = load_preferences()
        if updates:
            preferences.behavior = preferences.behavior.model_copy(update=updates)
            save_preferences(preferences)
        return UpdateResponse(
            status="updated",
            updated_settings=preferences.behavior,
            message="Behavior settings updated successfully" if updates else "No behavior settings changes supplied."
        )
    except Exception as e:
        api_logger.error(f"❌ Error updating behavior settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models", response_model=SettingsResponse[ModelSettings])
async def get_model_settings() -> SettingsResponse[ModelSettings]:
    """Get current model settings."""
    try:
        preferences = load_preferences()
        return SettingsResponse(settings=preferences.models)
    except Exception as e:
        api_logger.error(f"❌ Error getting model settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/models", response_model=UpdateResponse[ModelSettings])
async def update_model_settings(settings: ModelSettingsUpdate) -> UpdateResponse[ModelSettings]:
    """Update model settings."""
    try:
        api_logger.debug("🔧 Received model settings update request")
        api_logger.debug(f"🔧 Raw settings data: {settings.model_dump()}")
        
        preferences = load_preferences()
        
        # Update the basic settings
        preferences.models.transcription_model = settings.transcription_model
        preferences.models.persistence_duration = settings.persistence_duration
        preferences.models.vision_model = settings.vision_model
        preferences.models.language_model = settings.language_model
        preferences.models.reasoning_model = settings.reasoning_model
        
        if settings.local_vision_fallback_enabled is not None:
            preferences.models.local_vision_fallback_enabled = settings.local_vision_fallback_enabled
        if settings.local_vision_model_id is not None:
            preferences.models.local_vision_model_id = settings.local_vision_model_id.strip()
        if settings.reasoning_fallback_enabled is not None:
            preferences.models.reasoning_fallback_enabled = settings.reasoning_fallback_enabled
        if settings.reasoning_fallback_model_id is not None:
            preferences.models.reasoning_fallback_model_id = settings.reasoning_fallback_model_id.strip()
        
        # Update API settings if provided
        if settings.use_api_models is not None:
            preferences.models.use_api_models = settings.use_api_models
        if settings.anthropic_enabled is not None:
            preferences.models.anthropic_enabled = settings.anthropic_enabled
        if settings.openai_enabled is not None:
            preferences.models.openai_enabled = settings.openai_enabled
        
        # Update Anthropic model selections
        for model_id, enabled in settings.anthropic_models.items():
            # Only update if the model exists in our defaults
            if model_id in preferences.models.anthropic_models:
                preferences.models.anthropic_models[model_id] = enabled
        
        # Update OpenAI model selections
        for model_id, enabled in settings.openai_models.items():
            # Only update if the model exists in our defaults
            if model_id in preferences.models.openai_models:
                preferences.models.openai_models[model_id] = enabled
        
        # Update special features
        preferences.models.api_extended_thinking = settings.api_extended_thinking
        preferences.models.close_assistant_session_on_insert = settings.close_assistant_session_on_insert
        if settings.assistant_output_paste_mode is not None:
            preferences.models.assistant_output_paste_mode = settings.assistant_output_paste_mode
        preferences.models.use_region_selection = settings.use_region_selection
        
        save_preferences(preferences)
        
        return UpdateResponse(
            status="updated",
            updated_settings=preferences.models,
            message="Model settings updated successfully"
        )
    except Exception as e:
        api_logger.error(f"❌ Error updating model settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/general", response_model=SettingsResponse[GeneralSettings])
async def get_general_settings() -> SettingsResponse[GeneralSettings]:
    """Get current general settings."""
    try:
        preferences = load_preferences()
        return SettingsResponse(settings=preferences.general)
    except Exception as e:
        api_logger.error(f"❌ Error getting general settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/general", response_model=UpdateResponse[GeneralSettings])
async def update_general_settings(settings_update: GeneralSettingsUpdate) -> UpdateResponse[GeneralSettings]:
    """Update general settings."""
    try:
        preferences = load_preferences()
        updated = False
        if settings_update.has_completed_onboarding is not None and preferences.general.has_completed_onboarding != settings_update.has_completed_onboarding:
            preferences.general.has_completed_onboarding = settings_update.has_completed_onboarding
            api_logger.info(f"⚙️ General setting 'has_completed_onboarding' updated to: {preferences.general.has_completed_onboarding}")
            updated = True

        if settings_update.date_display_style is not None and preferences.general.date_display_style != settings_update.date_display_style:
            preferences.general.date_display_style = settings_update.date_display_style
            api_logger.info(f"⚙️ General setting 'date_display_style' updated to: {preferences.general.date_display_style}")
            updated = True

        if updated:
            save_preferences(preferences)
        
        return UpdateResponse(
            status="updated",
            updated_settings=preferences.general,
            message="General settings updated successfully." if updated else "No changes applied to general settings."
        )
    except Exception as e:
        api_logger.error(f"❌ Error updating general settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset", response_model=StatusResponse)
async def reset_settings() -> StatusResponse:
    """Reset all settings to defaults."""
    try:
        preferences = Preferences()  # Create new with defaults
        save_preferences(preferences)
        return StatusResponse(status="success", message="All settings reset to defaults")
    except Exception as e:
        api_logger.error(f"Error resetting settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dev/log", response_model=StatusResponse)
async def receive_client_log(request: Request) -> StatusResponse:
    """Development endpoint to receive and display client logs."""
    try:
        message = await request.body()
    except Exception:
        # Client disconnected before we could read the body - ignore it
        return StatusResponse(status="success", message="ok")
    
    # Create a direct console logger that won't propagate to avoid duplicates
    # This bypasses the normal logging chain to prevent duplicated logs
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("%(asctime)s - api.main - INFO - [API] [CLIENT] %(message)s"))
    
    # Create a non-propagating logger to avoid duplicates
    direct_logger = logging.getLogger("direct.client.log")
    direct_logger.propagate = False  # Don't propagate to root logger
    
    # Remove any existing handlers to prevent accumulation
    for handler in direct_logger.handlers[:]:
        direct_logger.removeHandler(handler)
    
    # Add our single console handler
    direct_logger.addHandler(console_handler)
    direct_logger.setLevel(logging.INFO)
    
    # Log directly without going through api_logger
    direct_logger.info(message.decode('utf-8'))
    
    return StatusResponse(status="success", message="logged")
