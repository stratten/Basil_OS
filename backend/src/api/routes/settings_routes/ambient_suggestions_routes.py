"""Ambient suggestion settings routes."""

from typing import List, Literal, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core.logging.api_logger import api_logger
from ...core.models.preferences import AmbientSuggestionSettings, Preferences
from ...core.models.responses import SettingsResponse, UpdateResponse

router = APIRouter(prefix="/ambient-suggestions", tags=["ambient-suggestions"])


def load_preferences() -> Preferences:
    """Load preferences from file or return defaults."""
    from api.core.preferences.preferences_io import load_preferences as _load_preferences
    return _load_preferences()


def save_preferences(preferences: Preferences) -> None:
    """Save preferences to file."""
    from api.core.preferences.preferences_io import save_preferences as _save_preferences
    return _save_preferences(preferences)


class AmbientSuggestionSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    frequency_minutes: Optional[float] = Field(None, ge=0.25, le=1440.0)
    frequency_seconds: Optional[float] = Field(None, ge=1.0, le=86400.0)
    evaluation_model: Optional[str] = None
    mode: Optional[Literal["suggestion_only", "auto_execute"]] = None
    enabled_capabilities: Optional[List[Literal["assistant_session", "agent_task"]]] = None
    auto_execute_capabilities: Optional[List[Literal["assistant_session", "agent_task"]]] = None
    minimum_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    cooldown_minutes: Optional[float] = Field(None, ge=0.0, le=10080.0)
    excluded_app_names: Optional[List[str]] = None
    allow_cloud_evaluation: Optional[bool] = None
    panel_position: Optional[Tuple[float, float, int]] = None
    panel_size: Optional[Tuple[int, int]] = None
    panel_visible_on_launch: Optional[bool] = None


@router.get("", response_model=SettingsResponse[AmbientSuggestionSettings])
async def get_ambient_suggestion_settings() -> SettingsResponse[AmbientSuggestionSettings]:
    """Get current ambient suggestion settings."""
    try:
        preferences = load_preferences()
        return SettingsResponse(settings=preferences.ambient_suggestions)
    except Exception as e:
        api_logger.error(f"Error getting ambient suggestion settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("", response_model=UpdateResponse[AmbientSuggestionSettings])
async def update_ambient_suggestion_settings(
    settings: AmbientSuggestionSettingsUpdate,
) -> UpdateResponse[AmbientSuggestionSettings]:
    """Update ambient suggestion settings."""
    try:
        preferences = load_preferences()
        current = preferences.ambient_suggestions

        updates = settings.model_dump(exclude_unset=True)
        if "frequency_seconds" in updates:
            updates["frequency_minutes"] = updates["frequency_seconds"] / 60.0
        elif "frequency_minutes" in updates:
            updates["frequency_seconds"] = updates["frequency_minutes"] * 60.0

        for field, value in updates.items():
            setattr(current, field, value)

        save_preferences(preferences)

        runtime_fields = {
            "enabled",
            "frequency_minutes",
            "frequency_seconds",
            "evaluation_model",
            "mode",
            "enabled_capabilities",
            "auto_execute_capabilities",
            "minimum_confidence",
            "cooldown_minutes",
            "excluded_app_names",
        }

        try:
            from api.services.ambient_suggestions.runtime import get_ambient_suggestion_runtime
            runtime = get_ambient_suggestion_runtime()
            if runtime and runtime_fields.intersection(updates):
                await runtime.apply_settings(current)
        except Exception as runtime_error:
            api_logger.error(
                f"Failed to apply ambient suggestion settings to runtime: {runtime_error}",
                exc_info=True,
            )

        return UpdateResponse(
            status="updated",
            updated_settings=current,
            message="Ambient suggestion settings updated successfully",
        )
    except Exception as e:
        api_logger.error(f"Error updating ambient suggestion settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
