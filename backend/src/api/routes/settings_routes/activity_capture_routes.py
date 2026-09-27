"""Activity capture routes for managing activity capture settings."""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.services.capture.shared.activity_capture_exclusion_policy import (
    normalize_excluded_bundle_ids,
)
from ...core.models.preferences import Preferences, ActivityCaptureSettings
from ...core.models.responses import SettingsResponse, UpdateResponse
from ...core.logging.api_logger import api_logger
from ...core.services.capture_management_service import CaptureManagementService
from ...core.services.file_storage_service import StorageService

async def synchronize_capture_cleanup_enabled(enabled: bool) -> tuple[CaptureManagementService, dict]:
    """Mirror cleanup enabled state into reasoning_settings.json for the scheduler."""
    service = CaptureManagementService(StorageService())
    current = await service.get_cleanup_settings()
    updated = await service.update_cleanup_settings(
        auto_cleanup_enabled=enabled,
        retention_days=current["retention_days"],
        cleanup_hour=current["cleanup_hour"],
        cleanup_minute=current["cleanup_minute"],
    )
    return service, updated

# Create the activity capture router
router = APIRouter(prefix="/activity-capture", tags=["activity-capture"])

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
class ActivityCaptureSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    start_at_startup: Optional[bool] = None
    frequency_minutes: Optional[float] = Field(None, ge=0.5, le=1440.0)  # Allow fractional minutes, minimum 30 seconds
    processing_model: Optional[str] = None
    processing_mode: Optional[str] = None
    scheduled_processing_time: Optional[str] = Field(None, pattern=r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$')  # Time in HH:MM format
    processing_max_records: Optional[int] = Field(None, ge=0, le=1000)
    max_file_age_days: Optional[int] = Field(None, ge=1, le=365)
    max_storage_mb: Optional[int] = Field(None, ge=50, le=5000)
    auto_cleanup_enabled: Optional[bool] = None
    excluded_bundle_ids: Optional[list[str]] = None
    idle_threshold_seconds: Optional[float] = Field(None, ge=0)
    post_wake_grace_seconds: Optional[float] = Field(None, ge=0)

# Endpoints

@router.get("", response_model=SettingsResponse[ActivityCaptureSettings])
async def get_activity_capture_settings() -> SettingsResponse[ActivityCaptureSettings]:
    """Get current activity capture settings."""
    try:
        preferences = load_preferences()
        return SettingsResponse(settings=preferences.activity_capture)
    except Exception as e:
        api_logger.error(f"❌ Error getting activity capture settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.put("", response_model=UpdateResponse[ActivityCaptureSettings])
async def update_activity_capture_settings(settings: ActivityCaptureSettingsUpdate) -> UpdateResponse[ActivityCaptureSettings]:
    """Update activity capture settings."""
    try:
        api_logger.debug("⚙️ Received activity capture settings update request")
        api_logger.debug(f"⚙️ Raw settings data: {settings.model_dump()}")
        
        preferences = load_preferences()
        
        # Track if frequency changed to update scheduler
        frequency_changed = False
        old_frequency = preferences.activity_capture.frequency_minutes
        
        old_auto_cleanup_enabled = preferences.activity_capture.auto_cleanup_enabled
        cleanup_service: CaptureManagementService | None = None

        # Track if scheduled processing time changed to update scheduler
        processing_time_changed = False
        old_processing_time = preferences.activity_capture.scheduled_processing_time
        
        # Update only the provided fields
        if settings.enabled is not None:
            preferences.activity_capture.enabled = settings.enabled
        if settings.start_at_startup is not None:
            preferences.activity_capture.start_at_startup = settings.start_at_startup
        if settings.frequency_minutes is not None:
            preferences.activity_capture.frequency_minutes = settings.frequency_minutes
            frequency_changed = (old_frequency != settings.frequency_minutes)
        if settings.processing_model is not None:
            preferences.activity_capture.processing_model = settings.processing_model
        if settings.processing_mode is not None:
            preferences.activity_capture.processing_mode = settings.processing_mode
        if settings.scheduled_processing_time is not None:
            # Validate the time string format
            try:
                hour, minute = map(int, settings.scheduled_processing_time.split(':'))
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    preferences.activity_capture.scheduled_processing_time = settings.scheduled_processing_time
                    processing_time_changed = (old_processing_time != settings.scheduled_processing_time)
                else:
                    api_logger.warning(f"⚠️ Invalid time values in scheduled_processing_time: {settings.scheduled_processing_time}. Hour must be 0-23, minute must be 0-59.")
            except ValueError:
                api_logger.warning(f"⚠️ Invalid scheduled_processing_time format: {settings.scheduled_processing_time}. Expected HH:MM.")
        if settings.processing_max_records is not None:
            preferences.activity_capture.processing_max_records = settings.processing_max_records
        if settings.max_file_age_days is not None:
            preferences.activity_capture.max_file_age_days = settings.max_file_age_days
        if settings.max_storage_mb is not None:
            preferences.activity_capture.max_storage_mb = settings.max_storage_mb
        if settings.auto_cleanup_enabled is not None:
            if settings.auto_cleanup_enabled != old_auto_cleanup_enabled:
                cleanup_service, _ = await synchronize_capture_cleanup_enabled(
                    settings.auto_cleanup_enabled
                )
            preferences.activity_capture.auto_cleanup_enabled = settings.auto_cleanup_enabled
        if settings.excluded_bundle_ids is not None:
            preferences.activity_capture.excluded_bundle_ids = normalize_excluded_bundle_ids(
                settings.excluded_bundle_ids
            )
        if settings.idle_threshold_seconds is not None:
            preferences.activity_capture.idle_threshold_seconds = settings.idle_threshold_seconds
        if settings.post_wake_grace_seconds is not None:
            preferences.activity_capture.post_wake_grace_seconds = settings.post_wake_grace_seconds
        
        try:
            save_preferences(preferences)
        except Exception:
            if (
                cleanup_service is not None
                and settings.auto_cleanup_enabled is not None
                and settings.auto_cleanup_enabled != old_auto_cleanup_enabled
            ):
                try:
                    current = await cleanup_service.get_cleanup_settings()
                    await cleanup_service.update_cleanup_settings(
                        auto_cleanup_enabled=old_auto_cleanup_enabled,
                        retention_days=current["retention_days"],
                        cleanup_hour=current["cleanup_hour"],
                        cleanup_minute=current["cleanup_minute"],
                    )
                except Exception as rollback_error:
                    api_logger.error(
                        "Failed to roll back capture cleanup scheduler after preferences save failure: %s",
                        rollback_error,
                        exc_info=True,
                    )
            raise

        if settings.enabled is False:
            from api.services.capture.automatic.activity_capture_runtime import (
                get_activity_capture_scheduler,
            )

            scheduler = get_activity_capture_scheduler()
            if scheduler is not None:
                await scheduler.stop_activity_capture()
                api_logger.info("Stopped running activity capture after it was disabled in settings")
        
        # If frequency changed, update the running scheduler
        if frequency_changed:
            api_logger.info(f"🔄 Frequency changed from {old_frequency} to {settings.frequency_minutes} minutes - updating scheduler")
            try:
                # Import here to avoid circular imports and ensure it's available
                from api.services.capture.automatic.activity_capture_runtime import get_activity_capture_scheduler
                scheduler = get_activity_capture_scheduler()
                if scheduler:
                    await scheduler.configure_activity_capture_frequency(settings.frequency_minutes)
                    api_logger.info(f"✅ Successfully updated running scheduler frequency from {old_frequency} to {settings.frequency_minutes} minutes")
                else:
                    api_logger.warning("⚠️ Activity capture scheduler not available - frequency will apply on next start")
            except Exception as scheduler_error:
                api_logger.error(f"❌ Failed to update running scheduler frequency: {scheduler_error}", exc_info=True)
                # Don't fail the entire request if scheduler update fails
        else:
            api_logger.debug(f"🔄 No frequency change detected (old: {old_frequency}, new: {settings.frequency_minutes})")
        
        # If scheduled processing hour changed, restart the processing service to pick up new hour
        if processing_time_changed:
            api_logger.info(f"🔄 Scheduled processing hour changed from {old_processing_time} to {preferences.activity_capture.scheduled_processing_time} - restarting processing service")
            try:
                from api.services.capture.automatic.activity_capture_runtime import get_automatic_processing_service_instance
                processing_service = get_automatic_processing_service_instance()
                if processing_service:
                    # Restart processing service to pick up new processing hour
                    if processing_service.is_processing_active:
                        await processing_service.stop_processing_service()
                        await processing_service.start_processing_service()
                        api_logger.info(f"✅ Successfully restarted processing service with new processing hour: {preferences.activity_capture.scheduled_processing_time}")
                    else:
                        # Update the processing service's internal state even if not running
                        time_parts = preferences.activity_capture.scheduled_processing_time.split(":")
                        if len(time_parts) == 2:
                            processing_service.scheduled_processing_hour = int(time_parts[0])
                            processing_service.scheduled_processing_minute = int(time_parts[1])
                        api_logger.info(f"✅ Updated processing service processing hour to {preferences.activity_capture.scheduled_processing_time} (service not running)")
                else:
                    api_logger.warning("⚠️ Activity capture processing service not available - processing hour will apply on next start")
            except Exception as scheduler_error:
                api_logger.error(f"❌ Failed to update running processing service processing hour: {scheduler_error}", exc_info=True)
                # Don't fail the entire request if scheduler update fails
        else:
            api_logger.debug(f"🔄 No processing hour change detected (old: {old_processing_time}, new: {preferences.activity_capture.scheduled_processing_time})")
        
        return UpdateResponse(
            status="updated",
            updated_settings=preferences.activity_capture,
            message="Activity capture settings updated successfully"
        )
    except Exception as e:
        api_logger.error(f"❌ Error updating activity capture settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

