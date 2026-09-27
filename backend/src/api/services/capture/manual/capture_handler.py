"""Handler for coordinating window capture and image processing."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
import time

from api.dependencies import get_sqlite_knowledge_service
from api.core.services.file_storage_service import StorageService
from api.core.services.model_service import ModelService
from api.services.image_processing.image_models import (
    ProcessingResponse,
    raise_if_analysis_unusable,
)
from api.services.image_processing.image_processing_service import ImageProcessor
from api.services.capture.shared.work_context import derive_work_context
from api.services.window_capture.window_capture_service import WindowCaptureService
from api.settings import Settings, get_settings

logger = logging.getLogger(__name__)

class CaptureHandler:
    """Coordinates window capture, image processing, and knowledge storage."""
    
    def __init__(
        self,
        model_service: ModelService,
        storage: Optional[StorageService] = None,
        settings: Optional[Settings] = None
    ) -> None:
        """Initialize the capture handler.
        
        Args:
            model_service: Service for managing AI models
            storage: Optional storage service for managing files
            settings: Optional settings for configuration
        """
        self.settings = settings or get_settings()
        self.storage = storage or StorageService()
        
        # Initialize services
        self.image_processor = ImageProcessor(model_service, self.storage, settings=self.settings)
        self.capture_service = WindowCaptureService(model_service, self.image_processor)
        self.knowledge_base = get_sqlite_knowledge_service()
        
        # Configure logging
        self.logger = logger.getChild("capture_handler")

    async def capture_and_process(self, temporary: bool = False, force_text_only: bool = False) -> Dict[str, Any]:
        """Handle the capture and processing flow.
        
        Args:
            temporary: If True, store capture in temporary location
            force_text_only: If True, forces text-only analysis even if vision is available (deprecated, always text-only now)
            
        Returns:
            Dictionary containing all capture and processing results
        """
        process_id = f"proc_{int(time.time() * 1000)}"
        try:
            # Capture window
            if temporary:
                self.logger.info(f"[{process_id}] Capturing temporary window")
                file_path, app_name, window_title, _ = await self.capture_service.capture_temp_window()
            else:
                self.logger.info(f"[{process_id}] Capturing permanent window")
                file_path, app_name, window_title, _ = await self.capture_service.capture_active_window()

            self.logger.info(f"[{process_id}] Captured {app_name} window to {file_path}")

            # Process image - always text-only now, but keeping parameter for backward compatibility
            self.logger.info(f"[{process_id}] Starting image processing...")
            img_proc_start = time.time()
            processing_result: ProcessingResponse = await self.image_processor.process_image(
                file_path
            )
            img_proc_end = time.time()
            self.logger.info(f"[{process_id}] Image processing completed in {img_proc_end - img_proc_start:.2f}s")

            # Checked before anything is written so a failed analysis is
            # reported rather than persisted as a real capture.
            raise_if_analysis_unusable(processing_result)

            # Save processed results
            timestamp = datetime.utcnow()
            processed_filename = f"processed_{timestamp.strftime('%Y%m%d_%H%M%S')}_{app_name}.json"
            processed_path = self.storage.get_processed_path(processed_filename)
            self.logger.info(f"[{process_id}] Saving results to {processed_path}")

            results = {
                "timestamp": timestamp.isoformat(),
                "app_name": app_name,
                "window_title": window_title,
                "image_path": str(file_path),
                "extracted_text": processing_result.extracted_text,
                "analysis": processing_result.analysis.dict() if processing_result.analysis else None,
                "analysis_type": processing_result.analysis_type,
                "processing_time_ms": processing_result.processing_time_ms,
                "is_temporary": temporary,
                "process_id": process_id  # Include process ID for tracking
            }

            with open(processed_path, "w") as f:
                json.dump(results, f, indent=2)
            self.logger.info(f"[{process_id}] Results saved to JSON file")

            # Store in knowledge base
            try:
                self.logger.info(f"[{process_id}] Storing activity in knowledge base")
                kb_start = time.time()
                activity_id = await self.knowledge_base.store_activity(
                    timestamp=timestamp,
                    app_name=app_name,
                    window_title=window_title,
                    extracted_text=processing_result.extracted_text,
                    ai_analysis=processing_result.analysis.dict() if processing_result.analysis else None,
                    metadata={
                        **derive_work_context(
                            app_name, window_title, capture_id=process_id
                        ).as_metadata(),
                        "capture_type": "temporary" if temporary else "permanent",
                        "file_path": str(file_path),
                        "processed_path": str(processed_path),
                        "analysis_type": processing_result.analysis_type,
                        "processing_time_ms": processing_result.processing_time_ms,
                        "process_id": process_id,
                        "automatic_capture": False  # Manual captures are not automatic
                    }
                )
                kb_end = time.time()
                
                results["activity_id"] = activity_id
                self.logger.info(f"[{process_id}] Activity stored in knowledge base with ID: {activity_id} in {kb_end - kb_start:.2f}s")
            except Exception as e:
                self.logger.error(f"[{process_id}] Failed to store activity in knowledge base: {e}", exc_info=True)
                results["knowledge_base_error"] = str(e)
                # Continue despite knowledge base error
            
            results["processed_path"] = str(processed_path)
            
            self.logger.info(f"[{process_id}] Processing complete. Total time: {time.time() - img_proc_start:.2f}s")
            return results

        except Exception as e:
            self.logger.error(f"[{process_id}] Error in capture and process: {e}", exc_info=True)
            return {
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "success": False,
                "process_id": process_id
            }

    async def find_similar_activities(self, content: str, app_name: Optional[str] = None, limit: int = 5) -> Dict[str, Any]:
        """Find activities similar to the provided content.
        
        Args:
            content: Text content to match against
            app_name: Optional app name to filter by
            limit: Maximum number of results to return
            
        Returns:
            Dictionary with similar activities
        """
        try:
            similar = await self.knowledge_base.search_activities(
                text_search=content,
                metadata_filters={"app_name": app_name} if app_name else None,
                limit=limit
            )
            
            return {
                "success": True,
                "count": len(similar),
                "activities": [activity.to_dict() for activity in similar]
            }
        except Exception as e:
            self.logger.error(f"Error finding similar activities: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    async def get_recent_activities(self, limit: int = 10, app_name: Optional[str] = None) -> Dict[str, Any]:
        """Get recent activities from the knowledge base.
        
        Args:
            limit: Maximum number of activities to return
            app_name: Optional app name to filter by
            
        Returns:
            Dictionary with recent activities
        """
        try:
            now = datetime.utcnow()
            activities = await self.knowledge_base.search_activities(
                time_range={
                    "start": now.replace(hour=0, minute=0, second=0, microsecond=0),
                    "end": now
                },
                metadata_filters={"app_name": app_name} if app_name else None,
                limit=limit
            )
            
            return {
                "success": True,
                "count": len(activities),
                "activities": [activity.to_dict() for activity in activities]
            }
        except Exception as e:
            self.logger.error(f"Error getting recent activities: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    async def cleanup(self) -> None:
        """Clean up temporary files and resources."""
        try:
            self.storage.cleanup_temp()
            self.logger.info("Temporary files cleaned up")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}", exc_info=True) 