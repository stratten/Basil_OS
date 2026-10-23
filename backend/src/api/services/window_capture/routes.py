from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
import logging
from typing import Optional

from .models import CaptureResponse, TextInsertRequest
from .window_capture_service import WindowCaptureService
from ...core.services.model_service import ModelService
from ...core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from ...dependencies import get_model_service, get_knowledge_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/window", tags=["window"])

async def get_capture_service(
    model_service: ModelService = Depends(get_model_service),
    knowledge_service: SQLiteKnowledgeService = Depends(get_knowledge_service)
) -> WindowCaptureService:
    """Dependency injection for WindowCaptureService."""
    return WindowCaptureService(model_service)

@router.post("/capture/temp", response_model=CaptureResponse)
async def capture_temp_window(
    service: WindowCaptureService = Depends(get_capture_service),
    knowledge_service: SQLiteKnowledgeService = Depends(get_knowledge_service)
) -> CaptureResponse:
    """Capture current window to temporary location."""
    start_time = datetime.now()
    try:
        file_path, app_name, window_title, processing_result = await service.capture_temp_window()
        
        # Calculate duration
        duration = int((datetime.now() - start_time).total_seconds())
        
        # Store in knowledge service
        await knowledge_service.store_activity(
            timestamp=start_time,
            app_name=app_name,
            window_title=window_title,
            extracted_text=processing_result.get("extracted_text"),
            ai_analysis=processing_result.get("analysis"),
            duration=duration,
            metadata={
                "capture_type": "temporary",
                "file_path": file_path,
                "automatic_capture": False  # Manual window captures are not automatic
            }
        )
        
        return CaptureResponse(
            file_path=file_path,
            app_name=app_name,
            window_title=window_title,
            timestamp=start_time,
            is_temporary=True,
            extracted_text=processing_result.get("extracted_text"),
            analysis=processing_result.get("analysis")
        )
    except Exception as e:
        logger.error(f"Failed to capture temporary window: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/capture/permanent", response_model=CaptureResponse)
async def capture_permanent_window(
    service: WindowCaptureService = Depends(get_capture_service),
    knowledge_service: SQLiteKnowledgeService = Depends(get_knowledge_service)
) -> CaptureResponse:
    """Capture current window and store permanently."""
    start_time = datetime.now()
    try:
        file_path, app_name, window_title, processing_result = await service.capture_active_window()
        
        # Calculate duration
        duration = int((datetime.now() - start_time).total_seconds())
        
        # Store in knowledge service
        await knowledge_service.store_activity(
            timestamp=start_time,
            app_name=app_name,
            window_title=window_title,
            extracted_text=processing_result.get("extracted_text"),
            ai_analysis=processing_result.get("analysis"),
            duration=duration,
            metadata={
                "capture_type": "permanent",
                "file_path": file_path,
                "automatic_capture": False  # Manual window captures are not automatic
            }
        )
        
        return CaptureResponse(
            file_path=file_path,
            app_name=app_name,
            window_title=window_title,
            timestamp=start_time,
            is_temporary=False,
            extracted_text=processing_result.get("extracted_text"),
            analysis=processing_result.get("analysis")
        )
    except Exception as e:
        logger.error(f"Failed to capture permanent window: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/insert")
async def insert_text(
    request: TextInsertRequest,
    service: WindowCaptureService = Depends(get_capture_service)
) -> dict:
    """Insert text into current window."""
    try:
        await service.insert_text(request.text)
        return {"status": "success", "message": "Text inserted successfully"}
    except Exception as e:
        logger.error(f"Failed to insert text: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
