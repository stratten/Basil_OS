"""Memory intelligence settings routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.core.logging.api_logger import api_logger
from api.core.models.preferences import MemoryIntelligenceSettings
from api.core.models.responses import SettingsResponse, UpdateResponse
from api.core.preferences.preferences_io import load_preferences, save_preferences
from api.routes.settings_routes.models import MemoryIntelligenceSettingsUpdate


router = APIRouter(prefix="/memory-intelligence", tags=["memory-intelligence"])


@router.get("", response_model=SettingsResponse[MemoryIntelligenceSettings])
async def get_memory_intelligence_settings() -> SettingsResponse[MemoryIntelligenceSettings]:
    """Get current memory intelligence settings."""
    try:
        preferences = load_preferences()
        return SettingsResponse(settings=preferences.memory_intelligence)
    except Exception as exc:
        api_logger.error(f"Error getting memory intelligence settings: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("", response_model=UpdateResponse[MemoryIntelligenceSettings])
async def update_memory_intelligence_settings(
    settings: MemoryIntelligenceSettingsUpdate,
) -> UpdateResponse[MemoryIntelligenceSettings]:
    """Update memory intelligence settings."""
    try:
        preferences = load_preferences()
        updates = settings.model_dump(exclude_unset=True)

        for field_name, value in updates.items():
            if field_name.endswith("_daily_time_local") and value is not None:
                _validate_local_time(value)
            if field_name == "skill_reconciliation_min_instances" and value is not None:
                _validate_min_instances(value)
            setattr(preferences.memory_intelligence, field_name, value)

        save_preferences(preferences)
        return UpdateResponse(
            updated_settings=preferences.memory_intelligence,
            message="Memory intelligence settings updated successfully",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        api_logger.error(f"Error updating memory intelligence settings: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _validate_local_time(value: str) -> None:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except Exception as exc:
        raise ValueError("Daily time must be in HH:MM format.") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Daily time must be in HH:MM format.")


def _validate_min_instances(value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("Reconciliation minimum instances must be an integer >= 1.")
