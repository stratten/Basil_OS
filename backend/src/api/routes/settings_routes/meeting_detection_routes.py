"""Meeting detection settings routes."""

from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core.logging.api_logger import api_logger
from ...core.models.preferences import MeetingDetectionSettings, Preferences
from ...core.models.responses import SettingsResponse, UpdateResponse

router = APIRouter(prefix="/meeting-detection", tags=["meeting-detection"])


def load_preferences() -> Preferences:
    """Load preferences from file or return defaults."""
    from api.core.preferences.preferences_io import load_preferences as _load_preferences
    return _load_preferences()


def save_preferences(preferences: Preferences) -> None:
    """Save preferences to file."""
    from api.core.preferences.preferences_io import save_preferences as _save_preferences
    return _save_preferences(preferences)


class MeetingDetectionSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    start_at_startup: Optional[bool] = None
    mode: Optional[Literal["prompt", "auto_start"]] = None
    poll_seconds: Optional[float] = Field(None, ge=1.0, le=600.0)
    excluded_bundle_ids: Optional[List[str]] = None
    excluded_app_names: Optional[List[str]] = None
    cooldown_minutes: Optional[float] = Field(None, ge=0.0, le=10080.0)
    use_calendar_enrichment: Optional[bool] = None
    require_calendar_match: Optional[bool] = None
    auto_end: Optional[bool] = None
    inactivity_timeout_minutes: Optional[float] = Field(None, ge=0.0, le=600.0)
    calendar_join_lead_minutes: Optional[float] = Field(None, ge=0.0, le=1440.0)
    calendar_join_grace_minutes: Optional[float] = Field(None, ge=0.0, le=1440.0)


@router.get("", response_model=SettingsResponse[MeetingDetectionSettings])
async def get_meeting_detection_settings() -> SettingsResponse[MeetingDetectionSettings]:
    """Get current meeting detection settings."""
    try:
        preferences = load_preferences()
        return SettingsResponse(settings=preferences.meeting_detection)
    except Exception as e:
        api_logger.error(f"Error getting meeting detection settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("", response_model=UpdateResponse[MeetingDetectionSettings])
async def update_meeting_detection_settings(
    settings: MeetingDetectionSettingsUpdate,
) -> UpdateResponse[MeetingDetectionSettings]:
    """Update meeting detection settings and push them to the runtime."""
    try:
        preferences = load_preferences()
        current = preferences.meeting_detection

        updates = settings.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(current, field, value)

        save_preferences(preferences)

        # Any settings change affects the loop; push to the runtime if present.
        try:
            from api.services.meeting_detection.runtime import get_meeting_detection_runtime
            runtime = get_meeting_detection_runtime()
            if runtime and updates:
                await runtime.apply_settings(current)
        except Exception as runtime_error:
            api_logger.error(
                f"Failed to apply meeting detection settings to runtime: {runtime_error}",
                exc_info=True,
            )

        return UpdateResponse(
            status="updated",
            updated_settings=current,
            message="Meeting detection settings updated successfully",
        )
    except Exception as e:
        api_logger.error(f"Error updating meeting detection settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
