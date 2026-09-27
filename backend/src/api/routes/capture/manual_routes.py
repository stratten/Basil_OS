"""API routes for capture handler."""

from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Dict, Any, Optional
import logging
import time
from datetime import datetime
import json
from pydantic import BaseModel

from api.core.services.model_service import get_model_service
from api.services.capture.manual.capture_handler import CaptureHandler
from api.services.capture.shared.work_context import derive_work_context
from api.services.image_processing.image_models import raise_if_analysis_unusable

router = APIRouter()
logger = logging.getLogger(__name__)

class ProcessCaptureRequest(BaseModel):
    """Request model for processing a captured image."""
    image_path: str
    app_name: str
    window_title: str

@router.post("/capture")
async def capture_screen(
    temporary: bool = Query(False, description="Whether to store the capture temporarily"),
    force_text_only: bool = Query(False, description="Deprecated: Always uses text-only analysis now")
) -> Dict[str, Any]:
    """Capture the active window and process it.
    
    Args:
        temporary: If True, store the capture in a temporary location
        force_text_only: Deprecated parameter, kept for backward compatibility. All analysis is text-only now.
        
    Returns:
        Dictionary containing capture and processing results
    """
    start_time = time.time()
    request_id = f"req_{int(start_time * 1000)}"
    logger.info(f"\n==== CAPTURE ENDPOINT CALLED [{request_id}] ====")
    logger.info(f"[{request_id}] Timestamp: {datetime.now().isoformat()}")
    logger.info(f"[{request_id}] Parameters: temporary={temporary}, force_text_only={force_text_only}")
    
    try:
        logger.info(f"[{request_id}] Getting model service...")
        model_service = get_model_service()
        
        logger.info(f"[{request_id}] Creating CaptureHandler instance...")
        handler = CaptureHandler(model_service)
        
        logger.info(f"[{request_id}] Initiating screen capture process...")
        capture_start = time.time()
        result = await handler.capture_and_process(
            temporary=temporary,
            force_text_only=force_text_only  # Kept for backward compatibility
        )
        capture_end = time.time()
        capture_duration = capture_end - capture_start
        
        if "error" in result:
            logger.error(f"[{request_id}] Capture failed: {result['error']}")
            logger.info(f"[{request_id}] ==== CAPTURE ENDPOINT FAILED (after {time.time() - start_time:.2f}s) ====\n")
            return {
                "operation": "capture",
                "status": "error",
                "details": result["error"]
            }
        
        logger.info(f"[{request_id}] Capture successful: {result.get('app_name', 'Unknown app')}")
        logger.info(f"[{request_id}] Analysis type: {result.get('analysis_type', 'unknown')}")
        logger.info(f"[{request_id}] Processing time: {result.get('processing_time_ms', 0)}ms")
        logger.info(f"[{request_id}] Capture process duration: {capture_duration:.2f}s")
        logger.info(f"[{request_id}] ==== CAPTURE ENDPOINT COMPLETED (total time: {time.time() - start_time:.2f}s) ====\n")
        
        # Format response to match OperationResponse structure expected by Swift client
        # The client expects: { "operation": String, "status": String, "details": String? }
        response_data = {
            "operation": "capture",
            "status": "success",
            "details": json.dumps({
                "app_name": result.get("app_name", "Unknown"),
                "window_title": result.get("window_title", ""),
                "analysis_type": result.get("analysis_type", "unknown"),
                "processing_time_ms": result.get("processing_time_ms", 0),
                "activity_id": result.get("activity_id", ""),
                "request_id": request_id  # Include request ID for debugging
            })
        }
        logger.info(f"[{request_id}] Returning response: {response_data}")
        return response_data
    except Exception as e:
        logger.error(f"[{request_id}] Unexpected error in capture endpoint: {e}", exc_info=True)
        logger.info(f"[{request_id}] ==== CAPTURE ENDPOINT FAILED (after {time.time() - start_time:.2f}s) ====\n")
        return {
            "operation": "capture",
            "status": "error",
            "details": str(e)
        }

@router.get("/recent-activities")
async def get_recent_activities(
    limit: int = Query(10, ge=1, le=100, description="Maximum number of activities to return"),
    app_name: Optional[str] = Query(None, description="Filter by application name")
) -> Dict[str, Any]:
    """Get recent activities from the knowledge base.
    
    Args:
        limit: Maximum number of activities to return
        app_name: Optional application name to filter by
        
    Returns:
        Dictionary containing recent activities
    """
    try:
        model_service = get_model_service()
        handler = CaptureHandler(model_service)
        
        logger.info(f"Retrieving recent activities (limit={limit}, app_name={app_name})")
        result = await handler.get_recent_activities(limit=limit, app_name=app_name)
        
        return result
    except Exception as e:
        logger.error(f"Error retrieving recent activities: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }

@router.post("/similar-activities")
async def find_similar_activities(
    content: str,
    app_name: Optional[str] = Query(None, description="Filter by application name"),
    limit: int = Query(5, ge=1, le=20, description="Maximum number of results to return")
) -> Dict[str, Any]:
    """Find activities similar to the provided content.
    
    Args:
        content: Text content to match against
        app_name: Optional application name to filter by
        limit: Maximum number of results to return
        
    Returns:
        Dictionary containing similar activities
    """
    try:
        model_service = get_model_service()
        handler = CaptureHandler(model_service)
        
        logger.info(f"Finding similar activities (content length={len(content)}, app_name={app_name})")
        result = await handler.find_similar_activities(
            content=content,
            app_name=app_name,
            limit=limit
        )
        
        return result
    except Exception as e:
        logger.error(f"Error finding similar activities: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }

@router.post("/cleanup")
async def cleanup_temporary_files() -> Dict[str, Any]:
    """Clean up temporary files created during capture.
    
    Returns:
        Success status
    """
    try:
        model_service = get_model_service()
        handler = CaptureHandler(model_service)
        
        logger.info("Cleaning up temporary files")
        await handler.cleanup()
        
        return {
            "success": True,
            "message": "Temporary files cleaned up successfully"
        }
    except Exception as e:
        logger.error(f"Error cleaning up temporary files: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }

@router.post("/capture/process")
async def process_captured_image(
    request: ProcessCaptureRequest
) -> Dict[str, Any]:
    """Process an already captured image.
    
    This endpoint is used when the frontend has already captured the image
    and just needs the backend to process it.
    
    Args:
        request: Contains image_path, app_name, and window_title
        
    Returns:
        Dictionary containing processing results
    """
    start_time = time.time()
    request_id = f"proc_{int(start_time * 1000)}"
    logger.info(f"\n==== PROCESS CAPTURED IMAGE ENDPOINT [{request_id}] ====")
    logger.info(f"[{request_id}] Timestamp: {datetime.now().isoformat()}")
    logger.info(f"[{request_id}] Image path: {request.image_path}")
    logger.info(f"[{request_id}] App: {request.app_name}")
    logger.info(f"[{request_id}] Window: {request.window_title}")
    
    try:
        logger.info(f"[{request_id}] Getting model service...")
        model_service = get_model_service()
        
        logger.info(f"[{request_id}] Creating CaptureHandler instance...")
        handler = CaptureHandler(model_service)
        
        # Process the image directly
        logger.info(f"[{request_id}] Processing image...")
        processing_start = time.time()
        processing_result = await handler.image_processor.process_image(request.image_path)
        processing_end = time.time()

        # Checked before anything is written so a failed analysis is
        # reported rather than persisted as a real capture.
        raise_if_analysis_unusable(processing_result)

        # Store the processed results
        timestamp = datetime.utcnow()
        processed_filename = f"processed_{timestamp.strftime('%Y%m%d_%H%M%S')}_{request.app_name}.json"
        processed_path = handler.storage.get_processed_path(processed_filename)
        
        results = {
            "timestamp": timestamp.isoformat(),
            "app_name": request.app_name,
            "window_title": request.window_title,
            "image_path": request.image_path,
            "extracted_text": processing_result.extracted_text,
            "analysis": processing_result.analysis.dict() if processing_result.analysis else None,
            "analysis_type": processing_result.analysis_type,
            "processing_time_ms": processing_result.processing_time_ms,
            "process_id": request_id
        }
        
        with open(processed_path, "w") as f:
            json.dump(results, f, indent=2)
        
        # Store in knowledge base
        try:
            logger.info(f"[{request_id}] Storing activity in knowledge base")
            activity_id = await handler.knowledge_base.store_activity(
                timestamp=timestamp,
                app_name=request.app_name,
                window_title=request.window_title,
                extracted_text=processing_result.extracted_text,
                ai_analysis=processing_result.analysis.dict() if processing_result.analysis else None,
                metadata={
                    **derive_work_context(
                        request.app_name,
                        request.window_title,
                        capture_id=request_id,
                    ).as_metadata(),
                    "capture_type": "frontend_capture",
                    "file_path": request.image_path,
                    "processed_path": str(processed_path),
                    "analysis_type": processing_result.analysis_type,
                    "processing_time_ms": processing_result.processing_time_ms,
                    "process_id": request_id,
                    "automatic_capture": False  # Frontend captures are not automatic
                }
            )
            results["activity_id"] = activity_id
            logger.info(f"[{request_id}] Activity stored with ID: {activity_id}")
        except Exception as e:
            logger.error(f"[{request_id}] Failed to store in knowledge base: {e}", exc_info=True)
            results["knowledge_base_error"] = str(e)
        
        processing_duration = processing_end - processing_start
        total_duration = time.time() - start_time
        
        logger.info(f"[{request_id}] Processing successful")
        logger.info(f"[{request_id}] Analysis type: {processing_result.analysis_type}")
        logger.info(f"[{request_id}] Processing time: {processing_result.processing_time_ms}ms")
        logger.info(f"[{request_id}] Processing duration: {processing_duration:.2f}s")
        logger.info(f"[{request_id}] ==== PROCESS ENDPOINT COMPLETED (total: {total_duration:.2f}s) ====\n")
        
        return {
            "operation": "process_capture",
            "status": "success",
            "details": results
        }
        
    except Exception as e:
        logger.error(f"[{request_id}] Error processing image: {e}", exc_info=True)
        logger.info(f"[{request_id}] ==== PROCESS ENDPOINT FAILED (after {time.time() - start_time:.2f}s) ====\n")
        return {
            "operation": "process_capture",
            "status": "error",
            "details": str(e)
        } 