"""Activity Capture API Routes - Automated background monitoring endpoints."""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import logging

from api.dependencies import get_knowledge_service
from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.capture.automatic.automatic_activity_capture_service import (
    AutomaticActivityCaptureService,
    ActivityCaptureRecord,
)
from api.services.capture.automatic.automatic_activity_processing_service import (
    AutomaticActivityProcessingService
)
from api.services.capture.automatic.activity_capture_runtime import (
    get_automatic_capture_service_instance,
    get_automatic_processing_service_instance,
)
from api.services.capture.automatic.activity_capture_data_lifecycle_service import (
    ActivityCaptureDataLifecycleService,
)
from api.services.capture.shared.activity_capture_status import ActivityCaptureStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/activity-capture", tags=["activity_capture"])

def get_automatic_capture_service() -> AutomaticActivityCaptureService:
    """Dependency to get the global automatic capture service instance."""
    automatic_capture_service = get_automatic_capture_service_instance()
    if automatic_capture_service is None:
        raise HTTPException(status_code=500, detail="Automatic capture service not initialized")
    return automatic_capture_service

def get_automatic_processing_service() -> AutomaticActivityProcessingService:
    """Dependency to get the global automatic processing service instance."""
    automatic_processing_service = get_automatic_processing_service_instance()
    if automatic_processing_service is None:
        raise HTTPException(status_code=500, detail="Automatic processing service not initialized")
    return automatic_processing_service

# Request/Response Models
class ActivityCaptureSchedulerConfigRequest(BaseModel):
    """Request model for configuring activity capture scheduler settings."""
    frequency_minutes: float = Field(ge=0.5, le=1440.0, description="Capture frequency in minutes (0.5-1440, supports fractional)")

class ActivityCaptureSchedulerStatusResponse(BaseModel):
    """Response model for activity capture scheduler status."""
    enabled: bool
    frequency_minutes: float
    last_capture_time: Optional[str]
    next_capture_time: Optional[str]
    pending_captures_count: int
    failed_captures_count: int
    total_captures_today: int
    total_captures_last_7_days: int
    total_captures_last_30_days: int
    skipped_capture_count: Optional[int] = None
    compacted_capture_count: Optional[int] = None
    last_policy_decision: Optional[str] = None
    last_policy_decision_time: Optional[str] = None

class ActivityCaptureRecordResponse(BaseModel):
    """Response model for activity capture record."""
    capture_id: str
    timestamp: str
    app_name: str
    window_title: str
    screenshot_path: Optional[str]
    processing_status: str
    automatic_capture: bool
    model_used: Optional[str]
    processing_started_at: Optional[str]
    processing_completed_at: Optional[str]
    error_message: Optional[str]
    retry_count: int

class ActivityCaptureOperationResponse(BaseModel):
    """Standard response model for activity capture operations."""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None

class CaptureServiceStatusResponse(BaseModel):
    """Response model for capture service status."""
    enabled: bool
    frequency_minutes: float
    last_capture_time: Optional[str]
    next_capture_time: Optional[str]

class ProcessingServiceStatusResponse(BaseModel):
    """Response model for processing service status."""
    enabled: bool
    next_scheduled_processing_time: Optional[str]
    pending_activities_count: int
    failed_activities_count: int
    scheduled_processing_hour: int
    is_currently_processing: bool

class ActivityProcessingProgressResponse(BaseModel):
    active: bool
    total: int
    processed: int
    succeeded: int
    failed: int
    remaining: int
    eta_seconds: Optional[float]
    cancel_requested: bool
    started_at: Optional[str]
    last_error: Optional[str]
    max_records: int
    analysis_concurrency: int
    processing_strategy: str

# Activity Capture Scheduler Management Endpoints

@router.post("/capture/start", response_model=ActivityCaptureOperationResponse)
async def start_automatic_capture(
    capture_service: AutomaticActivityCaptureService = Depends(get_automatic_capture_service)
):
    """Start automatic activity capture."""
    try:
        await capture_service.start_activity_capture()
        
        return ActivityCaptureOperationResponse(
            success=True,
            message="Automatic activity capture started successfully"
        )
        
    except Exception as e:
        logger.error(f"Failed to start automatic capture: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start capture: {str(e)}")

@router.post("/capture/stop", response_model=ActivityCaptureOperationResponse)
async def stop_automatic_capture(
    capture_service: AutomaticActivityCaptureService = Depends(get_automatic_capture_service)
):
    """Stop automatic activity capture."""
    try:
        await capture_service.stop_activity_capture()
        
        return ActivityCaptureOperationResponse(
            success=True,
            message="Automatic activity capture stopped successfully"
        )
        
    except Exception as e:
        logger.error(f"Failed to stop automatic capture: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to stop capture: {str(e)}")

@router.post("/processing/start", response_model=ActivityCaptureOperationResponse)
async def start_automatic_processing(
    processing_service: AutomaticActivityProcessingService = Depends(get_automatic_processing_service)
):
    """Start automatic activity processing."""
    try:
        await processing_service.start_processing_service()
        
        return ActivityCaptureOperationResponse(
            success=True,
            message="Automatic activity processing started successfully"
        )
        
    except Exception as e:
        logger.error(f"Failed to start automatic processing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start processing: {str(e)}")

@router.post("/processing/stop", response_model=ActivityCaptureOperationResponse)
async def stop_automatic_processing(
    processing_service: AutomaticActivityProcessingService = Depends(get_automatic_processing_service)
):
    """Stop automatic activity processing."""
    try:
        await processing_service.stop_processing_service()
        
        return ActivityCaptureOperationResponse(
            success=True,
            message="Automatic activity processing stopped successfully"
        )
        
    except Exception as e:
        logger.error(f"Failed to stop automatic processing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to stop processing: {str(e)}")

@router.post("/processing/process-now", response_model=ActivityCaptureOperationResponse)
async def process_pending_activities_now(
    processing_service: AutomaticActivityProcessingService = Depends(get_automatic_processing_service)
):
    """Trigger immediate processing of pending activities."""
    try:
        result = await processing_service.process_pending_activities_now()
        
        return ActivityCaptureOperationResponse(
            success=result.get("success", False),
            message=result.get("message", "Processing completed"),
            data={**result, "progress": result.get("progress")}
        )
        
    except Exception as e:
        logger.error(f"Failed to process pending activities: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process activities: {str(e)}")

@router.get("/processing/progress", response_model=ActivityProcessingProgressResponse)
async def get_activity_processing_progress(
    processing_service: AutomaticActivityProcessingService = Depends(get_automatic_processing_service),
) -> ActivityProcessingProgressResponse:
    progress = processing_service.get_processing_progress()
    remaining = max(progress.total - progress.processed, 0)
    eta_seconds = None
    if (
        progress.active
        and progress.processed > 0
        and remaining > 0
        and progress.started_at is not None
    ):
        elapsed_seconds = (datetime.now() - progress.started_at).total_seconds()
        if elapsed_seconds > 0:
            eta_seconds = elapsed_seconds / progress.processed * remaining

    return ActivityProcessingProgressResponse(
        **{
            **progress.__dict__,
            "remaining": remaining,
            "eta_seconds": eta_seconds,
            "started_at": progress.started_at.isoformat() if progress.started_at else None,
        }
    )


@router.post("/processing/cancel", response_model=ActivityCaptureOperationResponse)
async def cancel_activity_processing(
    processing_service: AutomaticActivityProcessingService = Depends(get_automatic_processing_service),
) -> ActivityCaptureOperationResponse:
    accepted = processing_service.request_processing_cancellation()
    return ActivityCaptureOperationResponse(
        success=True,
        message=(
            "Stopping after the current OCR and analysis work finish."
            if accepted
            else "No activity-capture processing run is active."
        ),
        data={"cancel_requested": accepted},
    )

@router.post("/processing/clear-backlog", response_model=ActivityCaptureOperationResponse)
async def clear_backlog(
    knowledge_service: SQLiteKnowledgeService = Depends(get_knowledge_service)
):
    """Clear pending, OCR-complete, and failed captures through lifecycle deletion."""
    try:
        logger.info("🧹 Starting backlog clearing operation")

        pending_activities = await knowledge_service.search_activities(
            metadata_filters={"processing_status": "PENDING"},
            limit=1000
        )
        
        ocr_complete_activities = await knowledge_service.search_activities(
            metadata_filters={"processing_status": "OCR_COMPLETE"},
            limit=1000
        )
        failed_activities = await knowledge_service.search_activities(
            metadata_filters={"processing_status": "FAILED"},
            limit=1000
        )

        pending_count = len(pending_activities)
        ocr_complete_count = len(ocr_complete_activities)
        failed_count = len(failed_activities)
        total_count = pending_count + ocr_complete_count + failed_count
        
        if total_count == 0:
            return ActivityCaptureOperationResponse(
                success=True,
                message="No backlog items to clear",
                data={"cleared_count": 0}
            )

        from api.services.retrieval.index_runtime import get_retrieval_index_runtime
        from api.services.zettel.materializer import get_zettel_materializer

        deletion_service = ActivityCaptureDataLifecycleService(
            knowledge_service.db_path,
            get_retrieval_index_runtime(),
            get_zettel_materializer(),
        )
        deletion_result = await deletion_service.delete_activity_ids(
            [
                *(activity.id for activity in pending_activities),
                *(activity.id for activity in ocr_complete_activities),
                *(activity.id for activity in failed_activities),
            ]
        )
        cleared_count = deletion_result.records_deleted
        if cleared_count != total_count:
            raise RuntimeError(
                f"Backlog deletion selected {total_count} activities but deleted {cleared_count}"
            )

        success_msg = f"Backlog deleted: {pending_count} pending, {ocr_complete_count} OCR complete, {failed_count} failed ({cleared_count} total)"
        logger.info(f"✅ {success_msg}")

        return ActivityCaptureOperationResponse(
            success=True,
            message=success_msg,
            data={
                "deleted_count": cleared_count,
                "pending_deleted": pending_count,
                "ocr_complete_deleted": ocr_complete_count,
                "failed_deleted": failed_count,
                "files_deleted": deletion_result.files_deleted,
                "derived_entries_deleted": deletion_result.derived_entries_deleted,
            }
        )

    except Exception as e:
        logger.error(f"Failed to clear backlog: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to clear backlog: {str(e)}")

@router.get("/status", response_model=ActivityCaptureSchedulerStatusResponse)
async def get_activity_capture_status(
    knowledge_service: SQLiteKnowledgeService = Depends(get_knowledge_service)
) -> ActivityCaptureSchedulerStatusResponse:
    """Return durable capture counts, with optional runtime scheduler state."""
    try:
        from api.core.models.preferences import Preferences

        preferences = Preferences.load().activity_capture
        capture_service = get_automatic_capture_service_instance()
        capture_status = (
            await capture_service.get_status()
            if capture_service is not None
            else {
                # The scheduler cannot be running until its runtime service has
                # initialized. Keep its active state distinct from the persisted
                # feature-availability preference.
                "enabled": False,
                "frequency_minutes": preferences.frequency_minutes,
                "last_capture_time": None,
                "next_capture_time": None,
            }
        )
        
        # Calculate today's captures count (both automatic and manual)
        from datetime import datetime
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Get all captures (both automatic and manual) from today
        all_today_captures = await knowledge_service.search_activities(
            time_range={"start": today_start, "end": today_end},
            limit=1000
        )
        
        # Filter to only include captures that have the automatic_capture metadata field
        # (this excludes older captures that don't have this field)
        today_captures = [
            capture for capture in all_today_captures
            if capture.metadata and "automatic_capture" in capture.metadata
        ]

        pending_activities = await knowledge_service.search_activities(
            metadata_filters={"processing_status": "PENDING"},
            limit=1000,
        )
        ocr_complete_activities = await knowledge_service.search_activities(
            metadata_filters={"processing_status": "OCR_COMPLETE"},
            limit=1000,
        )
        failed_activities = await knowledge_service.search_activities(
            metadata_filters={"processing_status": "FAILED"},
            limit=1000,
        )

        # Durable automatic-capture activity counts, not to be confused with the
        # raw screenshot *file* counts shown in Capture Management: an activity
        # can survive after its screenshot file is deleted (e.g. dedup
        # compaction), so these numbers are the actual source of truth for
        # "how many captures happened" over a given window.
        seven_days_ago = datetime.now() - timedelta(days=6)
        thirty_days_ago = datetime.now() - timedelta(days=29)
        total_captures_last_7_days = await knowledge_service.count_automatic_captures_since(
            seven_days_ago.replace(hour=0, minute=0, second=0, microsecond=0)
        )
        total_captures_last_30_days = await knowledge_service.count_automatic_captures_since(
            thirty_days_ago.replace(hour=0, minute=0, second=0, microsecond=0)
        )

        return ActivityCaptureSchedulerStatusResponse(
            enabled=capture_status["enabled"],
            frequency_minutes=capture_status["frequency_minutes"],
            last_capture_time=capture_status["last_capture_time"],
            next_capture_time=capture_status["next_capture_time"],
            pending_captures_count=len(pending_activities) + len(ocr_complete_activities),
            failed_captures_count=len(failed_activities),
            total_captures_today=len(today_captures),
            total_captures_last_7_days=total_captures_last_7_days,
            total_captures_last_30_days=total_captures_last_30_days,
            skipped_capture_count=capture_status.get("skipped_capture_count"),
            compacted_capture_count=capture_status.get("compacted_capture_count"),
            last_policy_decision=capture_status.get("last_policy_decision"),
            last_policy_decision_time=capture_status.get("last_policy_decision_time"),
        )
        
    except Exception as e:
        logger.error(f"Failed to get activity capture status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")

@router.get("/capture/status", response_model=CaptureServiceStatusResponse)
async def get_capture_status(
    capture_service: AutomaticActivityCaptureService = Depends(get_automatic_capture_service)
) -> CaptureServiceStatusResponse:
    """Get the current status of the capture service."""
    try:
        status = await capture_service.get_status()
        return CaptureServiceStatusResponse(**status)
        
    except Exception as e:
        logger.error(f"Failed to get capture status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get capture status: {str(e)}")

@router.get("/processing/status", response_model=ProcessingServiceStatusResponse)
async def get_processing_status(
    processing_service: AutomaticActivityProcessingService = Depends(get_automatic_processing_service)
) -> ProcessingServiceStatusResponse:
    """Get the current status of the processing service."""
    try:
        status = await processing_service.get_status()
        return ProcessingServiceStatusResponse(**status)
        
    except Exception as e:
        logger.error(f"Failed to get processing status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get processing status: {str(e)}")

# Note: Manual captures are handled by the existing /capture/capture endpoint (F1 hotkey)
# This service focuses on automated scheduler functionality only

# Legacy endpoints removed - use the new separated endpoints above instead

# Activity Capture History and Statistics Endpoints

@router.get("/history/today", response_model=List[ActivityCaptureRecordResponse])
async def get_today_activity_captures(
    knowledge_service: SQLiteKnowledgeService = Depends(get_knowledge_service)
):
    """Get all activity captures performed today (both automatic and manual)."""
    try:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Get all activities from today
        all_activities = await knowledge_service.search_activities(
            time_range={"start": today_start, "end": today_end},
            limit=1000
        )
        
        # Filter to only include captures that have the automatic_capture metadata field
        activities = [
            activity for activity in all_activities
            if activity.metadata and "automatic_capture" in activity.metadata
        ]
        
        return [
            ActivityCaptureRecordResponse(
                capture_id=activity.metadata.get("capture_id", activity.id) if activity.metadata else activity.id,
                timestamp=activity.timestamp.isoformat(),
                app_name=activity.app_name,
                window_title=activity.window_title,
                screenshot_path=activity.metadata.get("screenshot_path") if activity.metadata else None,
                processing_status=activity.metadata.get("processing_status", "UNKNOWN") if activity.metadata else "UNKNOWN",
                automatic_capture=activity.metadata.get("automatic_capture", "False") == "True" if activity.metadata else False,
                model_used=activity.metadata.get("model_used") if activity.metadata else None,
                processing_started_at=None,  # Would need to be stored in metadata
                processing_completed_at=None,  # Would need to be stored in metadata
                error_message=activity.metadata.get("error_message") if activity.metadata else None,
                retry_count=int(activity.metadata.get("retry_count", "0")) if activity.metadata else 0
            )
            for activity in activities
        ]
        
    except Exception as e:
        logger.error(f"Failed to get today's activity captures: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get today's captures: {str(e)}")

@router.get("/statistics/summary", response_model=Dict[str, Any])
async def get_activity_capture_statistics(
    knowledge_service: SQLiteKnowledgeService = Depends(get_knowledge_service)
):
    """Get summary statistics for activity capture system."""
    try:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Get today's captures (both automatic and manual)
        all_today_captures = await knowledge_service.search_activities(
            time_range={"start": today_start, "end": today_end},
            limit=1000
        )
        today_captures = [
            capture for capture in all_today_captures
            if capture.metadata and "automatic_capture" in capture.metadata
        ]
        
        # Get all-time captures (last 30 days, both automatic and manual)
        thirty_days_ago = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=30)
        all_recent_captures = await knowledge_service.search_activities(
            time_range={"start": thirty_days_ago, "end": today_end},
            limit=10000
        )
        all_captures = [
            capture for capture in all_recent_captures
            if capture.metadata and "automatic_capture" in capture.metadata
        ]
        
        # Calculate statistics
        today_count = len(today_captures)
        total_count = len(all_captures)
        
        # Group by processing status
        status_counts: dict[str, int] = {}
        for capture in all_captures:
            # Activity objects have metadata attribute
            metadata = capture.metadata or {}
            status = metadata.get("processing_status", "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Calculate daily average
        daily_average = total_count / 30 if total_count > 0 else 0
        
        return {
            "today_captures": today_count,
            "total_captures_30_days": total_count,
            "daily_average": round(daily_average, 2),
            "status_distribution": status_counts,
            "most_active_day": None,  # Could be calculated from daily breakdown
            "processing_success_rate": round(
                (status_counts.get("COMPLETED", 0) / total_count * 100) if total_count > 0 else 0, 2
            )
        }
        
    except Exception as e:
        logger.error(f"Failed to get activity capture statistics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get statistics: {str(e)}")

# Legacy compatibility endpoint for client toggle
@router.post("/toggle", response_model=ActivityCaptureOperationResponse)
async def toggle_activity_capture(
    capture_service: AutomaticActivityCaptureService = Depends(get_automatic_capture_service)
):
    """Toggle automatic activity capture on/off (for compatibility with existing client)."""
    try:
        status = await capture_service.get_status()
        
        if status["enabled"]:
            # Currently enabled, so stop it
            await capture_service.stop_activity_capture()
            return ActivityCaptureOperationResponse(
                success=True,
                message="Automatic activity capture disabled"
            )
        else:
            # Currently disabled, so start it
            await capture_service.start_activity_capture()
            return ActivityCaptureOperationResponse(
                success=True,
                message="Automatic activity capture enabled"
            )
        
    except Exception as e:
        logger.error(f"Failed to toggle activity capture: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to toggle capture: {str(e)}")
