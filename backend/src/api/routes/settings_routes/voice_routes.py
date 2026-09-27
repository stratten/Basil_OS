"""Voice routes for managing agent-task, assistant-session, and conversation widget settings."""

from typing import Dict, Any, Optional, Tuple, Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...core.models.preferences import (
    Preferences,
    AgentTaskPreferences,
    AssistantSessionPreferences,
    ConversationWidgetPreferences
)
from ...core.models.responses import SettingsResponse, UpdateResponse
from ...core.logging.api_logger import api_logger

# Create the voice router (no prefix - endpoints will be directly under /settings)
router = APIRouter(tags=["voice"])

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
class AgentTaskSettingsUpdate(BaseModel):
    """Model for updating agent-task settings."""
    widget_position: Optional[Tuple[float, float, int]] = None
    result_widget_size: Optional[Tuple[int, int]] = None
    enable_push_to_talk: Optional[bool] = None
    push_to_talk_threshold_ms: Optional[int] = None
    default_input_modality: Optional[Literal["voice", "text"]] = None
    auto_reopen_on_completion: Optional[bool] = None

class AssistantSessionSettingsUpdate(BaseModel):
    """Model for updating assistant-session settings."""
    enable_push_to_talk: Optional[bool] = None
    push_to_talk_threshold_ms: Optional[int] = None
    # Default entry mode for the unified assistant-session widget. `speak` opens the
    # mic immediately (legacy behaviour); `type` opens the typed-input field
    # without starting recording. The widget header toggle can flip the
    # active mode at runtime regardless of this default.
    default_input_modality: Optional[Literal["speak", "type"]] = None

# Agent-task Endpoints

@router.get("/agent-task", response_model=SettingsResponse[AgentTaskPreferences])
async def get_agent_task_settings() -> SettingsResponse[AgentTaskPreferences]:
    """Get agent-task widget settings."""
    try:
        preferences = load_preferences()
        return SettingsResponse(settings=preferences.agent_task)
    except Exception as e:
        api_logger.error(f"❌ Error getting agent-task settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/agent-task", response_model=UpdateResponse[AgentTaskPreferences])
async def update_agent_task_settings(settings: AgentTaskSettingsUpdate) -> UpdateResponse[AgentTaskPreferences]:
    """Update agent-task widget settings."""
    try:
        api_logger.debug("⚙️ Received agent-task settings update request")
        api_logger.debug(f"⚙️ Raw settings data: {settings.model_dump()}")
        
        preferences = load_preferences()
        
        # Update only provided settings
        if settings.widget_position is not None:
            preferences.agent_task.widget_position = settings.widget_position
            api_logger.debug(f"📍 Updated agent-task widget position: {settings.widget_position}")
        
        if settings.result_widget_size is not None:
            preferences.agent_task.result_widget_size = settings.result_widget_size
            api_logger.debug(f"📏 Updated agent-task result widget size: {settings.result_widget_size}")
        
        if settings.enable_push_to_talk is not None:
            preferences.agent_task.enable_push_to_talk = settings.enable_push_to_talk
            api_logger.debug(f"🎙️ Updated agent-task push-to-talk enabled: {settings.enable_push_to_talk}")
        
        if settings.push_to_talk_threshold_ms is not None:
            preferences.agent_task.push_to_talk_threshold_ms = settings.push_to_talk_threshold_ms
            api_logger.debug(f"⏱️ Updated agent-task push-to-talk threshold: {settings.push_to_talk_threshold_ms}ms")

        if settings.default_input_modality is not None:
            preferences.agent_task.default_input_modality = settings.default_input_modality
            api_logger.debug(f"⌨️ Updated agent-task default input modality: {settings.default_input_modality}")

        if settings.auto_reopen_on_completion is not None:
            preferences.agent_task.auto_reopen_on_completion = settings.auto_reopen_on_completion
            api_logger.debug(f"🪟 Updated agent-task auto reopen on completion: {settings.auto_reopen_on_completion}")

        save_preferences(preferences)
        
        return UpdateResponse(
            status="updated",
            updated_settings=preferences.agent_task,
            message="Agent-task settings updated successfully"
        )
    except Exception as e:
        api_logger.error(f"❌ Error updating agent-task settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# Assistant-session Endpoints

@router.get("/assistant-session", response_model=SettingsResponse[AssistantSessionPreferences])
async def get_assistant_session_settings() -> SettingsResponse[AssistantSessionPreferences]:
    """Get assistant-session settings."""
    try:
        preferences = load_preferences()
        return SettingsResponse(settings=preferences.assistant_session)
    except Exception as e:
        api_logger.error(f"❌ Error getting assistant-session settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/assistant-session", response_model=UpdateResponse[AssistantSessionPreferences])
async def update_assistant_session_settings(settings: AssistantSessionSettingsUpdate) -> UpdateResponse[AssistantSessionPreferences]:
    """Update assistant-session settings."""
    try:
        api_logger.debug("⚙️ Received assistant-session settings update request")
        
        preferences = load_preferences()
        
        # Update only provided settings
        if settings.enable_push_to_talk is not None:
            preferences.assistant_session.enable_push_to_talk = settings.enable_push_to_talk
            api_logger.debug(f"🎙️ Updated assistant-session push-to-talk enabled: {settings.enable_push_to_talk}")
        
        if settings.push_to_talk_threshold_ms is not None:
            preferences.assistant_session.push_to_talk_threshold_ms = settings.push_to_talk_threshold_ms
            api_logger.debug(f"⏱️ Updated assistant-session push-to-talk threshold: {settings.push_to_talk_threshold_ms}ms")

        if settings.default_input_modality is not None:
            preferences.assistant_session.default_input_modality = settings.default_input_modality
            api_logger.debug(f"⌨️ Updated assistant-session default input modality: {settings.default_input_modality}")

        save_preferences(preferences)
        
        return UpdateResponse(
            status="updated",
            updated_settings=preferences.assistant_session,
            message="Assistant-session settings updated successfully"
        )
    except Exception as e:
        api_logger.error(f"❌ Error updating assistant-session settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# Conversation Widget Endpoints

@router.get("/conversation-widget", response_model=SettingsResponse[ConversationWidgetPreferences])
async def get_conversation_widget_settings() -> SettingsResponse[ConversationWidgetPreferences]:
    """Get conversation widget settings."""
    try:
        preferences = load_preferences()
        return SettingsResponse(settings=preferences.conversation_widget)
    except Exception as e:
        api_logger.error(f"❌ Error getting conversation widget settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/conversation-widget", response_model=UpdateResponse[ConversationWidgetPreferences])
async def update_conversation_widget_settings(settings: Dict[str, Any]) -> UpdateResponse[ConversationWidgetPreferences]:
    """Update conversation widget settings."""
    try:
        api_logger.debug("⚙️ Received conversation widget settings update request")
        api_logger.debug(f"⚙️ Raw settings data: {settings}")
        
        preferences = load_preferences()
        
        # Update only provided settings
        if "widget_size" in settings and settings["widget_size"] is not None:
            preferences.conversation_widget.widget_size = tuple(settings["widget_size"])
            api_logger.debug(f"📏 Updated conversation widget size: {settings['widget_size']}")
        
        if "widget_position" in settings and settings["widget_position"] is not None:
            preferences.conversation_widget.widget_position = tuple(settings["widget_position"])
            api_logger.debug(f"📍 Updated conversation widget position: {settings['widget_position']}")
        
        if "is_sidebar_collapsed" in settings:
            preferences.conversation_widget.is_sidebar_collapsed = settings["is_sidebar_collapsed"]
            api_logger.debug(f"📂 Updated sidebar collapsed state: {settings['is_sidebar_collapsed']}")
        
        save_preferences(preferences)
        
        return UpdateResponse(
            status="updated",
            updated_settings=preferences.conversation_widget,
            message="Conversation widget settings updated successfully"
        )
    except Exception as e:
        api_logger.error(f"❌ Error updating conversation widget settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

