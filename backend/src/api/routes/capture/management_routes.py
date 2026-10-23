# backend/src/api/routes/capture/management_routes.py
import logging
from fastapi import APIRouter, Depends, HTTPException, Path as FastApiPath
from pydantic import BaseModel, Field

# Corrected import path assuming services are in api.core.services
from ...core.services.capture_management_service import CaptureManagementService
from ...core.services.file_storage_service import StorageService

# Placeholder for Pydantic models - these should be defined in a shared models location
# For example: backend/src/api/models/capture_management_models.py

class CaptureStatsResponse(BaseModel):
    total_files: int
    total_size_bytes: int
    files_last_7_days: int
    size_last_7_days_bytes: int
    files_last_30_days: int
    size_last_30_days_bytes: int

class CleanupSettingsResponse(BaseModel):
    auto_cleanup_enabled: bool
    retention_days: int
    cleanup_hour: int
    cleanup_minute: int

class UpdateCleanupSettingsRequest(BaseModel):
    auto_cleanup_enabled: bool
    retention_days: int
    cleanup_hour: int = None  # Optional - will use current if not provided
    cleanup_minute: int = None  # Optional - will use current if not provided

class ClearCapturesResponse(BaseModel):
    status: str
    message: str
    files_deleted: int
    space_freed_bytes: int
    records_deleted: int = 0
    derived_entries_deleted: int = 0
    errors: list[str] = Field(default_factory=list)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/capture-management", tags=["Capture Management"])

# Dependency injection for services
def get_storage_service():
    # Assuming StorageService can be instantiated directly or fetched from a global app state
    return StorageService() 

def get_capture_management_service(storage_service: StorageService = Depends(get_storage_service)):
    return CaptureManagementService(storage_service=storage_service)

@router.get("/stats", response_model=CaptureStatsResponse)
async def get_capture_stats_endpoint(
    service: CaptureManagementService = Depends(get_capture_management_service)
):
    """Endpoint to get statistics about stored capture files."""
    try:
        stats = await service.get_capture_stats()
        return CaptureStatsResponse(**stats)
    except Exception as e:
        logger.error(f"Error getting capture stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve capture statistics.")

@router.get("/settings", response_model=CleanupSettingsResponse)
async def get_cleanup_settings_endpoint(
    service: CaptureManagementService = Depends(get_capture_management_service)
):
    """Endpoint to get current cleanup settings."""
    try:
        settings = await service.get_cleanup_settings()
        return CleanupSettingsResponse(**settings)
    except Exception as e:
        logger.error(f"Error getting cleanup settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve cleanup settings.")

@router.post("/settings", response_model=CleanupSettingsResponse)
async def update_cleanup_settings_endpoint(
    payload: UpdateCleanupSettingsRequest,
    service: CaptureManagementService = Depends(get_capture_management_service)
):
    """Endpoint to update cleanup settings."""
    try:
        updated_settings = await service.update_cleanup_settings(
            auto_cleanup_enabled=payload.auto_cleanup_enabled,
            retention_days=payload.retention_days,
            cleanup_hour=payload.cleanup_hour,
            cleanup_minute=payload.cleanup_minute
        )
        return CleanupSettingsResponse(**updated_settings)
    except ValueError as ve:
        logger.warning(f"Invalid value in update_cleanup_settings: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error updating cleanup settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update cleanup settings.")

@router.post("/clear-all", response_model=ClearCapturesResponse)
async def clear_all_captures_endpoint(
    service: CaptureManagementService = Depends(get_capture_management_service)
):
    """Endpoint to delete all capture files."""
    try:
        result = await service.clear_all_captures()
        return ClearCapturesResponse(**result)
    except Exception as e:
        logger.error(f"Error clearing all captures: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to clear all captures.")

@router.post("/clear-older-than/{days}", response_model=ClearCapturesResponse)
async def clear_captures_older_than_endpoint(
    days: int = FastApiPath(..., title="The maximum age in days for captures to keep. Files older than this will be deleted.", ge=0),
    service: CaptureManagementService = Depends(get_capture_management_service)
):
    """Endpoint to delete capture files older than a specified number of days."""
    try:
        result = await service.clear_captures_older_than(days)
        return ClearCapturesResponse(**result)
    except ValueError as ve:
        logger.warning(f"Invalid value in clear_captures_older_than: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error clearing captures older than {days} days: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to clear captures older than {days} days.")

@router.post("/test-automatic-cleanup", response_model=dict)
async def test_automatic_cleanup_endpoint(
    service: CaptureManagementService = Depends(get_capture_management_service)
):
    """Endpoint to manually trigger automatic cleanup for testing purposes."""
    try:
        logger.info("Manual trigger: Testing automatic cleanup")
        await service.run_automatic_cleanup()
        return {"status": "success", "message": "Automatic cleanup test completed. Check logs for details."}
    except Exception as e:
        logger.error(f"Error during automatic cleanup test: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to run automatic cleanup test: {str(e)}")

# It would be good to register this router with the main FastAPI app.
# Example (in main.py or similar):
# from api.routes import capture_management_routes
# app.include_router(capture_management_routes.router) 
