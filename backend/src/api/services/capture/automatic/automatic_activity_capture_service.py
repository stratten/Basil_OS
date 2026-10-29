"""Automatic Activity Capture Service - Automated periodic screenshot capture."""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import uuid
from dataclasses import dataclass

from api.services.capture.shared.activity_capture_status import ActivityCaptureStatus
from api.services.capture.shared.work_context import derive_work_context

logger = logging.getLogger(__name__)

@dataclass
class ActivityCaptureRecord:
    """Represents a captured activity."""
    capture_id: str
    timestamp: datetime
    app_name: str
    window_title: str
    screenshot_path: Optional[str]
    extracted_text: Optional[str]  # OCR result
    processing_status: ActivityCaptureStatus
    automatic_capture: bool
    error_message: Optional[str] = None
    perceptual_hash: Optional[str] = None
    work_context_key: Optional[str] = None

class AutomaticActivityCaptureService:
    """Service for automated periodic activity capture."""
    
    def __init__(self, knowledge_service):
        self.knowledge_service = knowledge_service
        
        # Capture state
        self.is_capture_active = False
        self.activity_capture_frequency_minutes = 0.5  # Default 30 seconds
        self.activity_capture_timeout_seconds = 30.0
        self.last_activity_capture_time: Optional[datetime] = None
        
        # Background task
        self.activity_capture_task: Optional[asyncio.Task] = None
        
        # OCR service for immediate text extraction
        self.ocr_service = None
        self._initialize_ocr_service()

        # In-memory policy telemetry (resets on process restart)
        self.skipped_capture_count = 0
        self.compacted_capture_count = 0
        self.last_policy_decision: Optional[str] = None
        self.last_policy_decision_time: Optional[datetime] = None
        
        logger.info("AutomaticActivityCaptureService initialized")
    
    def _initialize_ocr_service(self):
        """Initialize OCR service for immediate text extraction."""
        try:
            from api.services.ocr.ocr_service import OCRService
            self.ocr_service = OCRService(development_mode=True)
            logger.info("✅ OCR service initialized for automatic capture")
        except Exception as e:
            logger.error(f"❌ Failed to initialize OCR service: {e}")
            self.ocr_service = None
    
    async def start_activity_capture(self) -> None:
        """Start automatic activity capture."""
        if self.is_capture_active:
            logger.warning("Activity capture is already active")
            return
            
        # Load settings from preferences
        try:
            from api.core.preferences.preferences_io import load_preferences
            preferences = load_preferences()
            self.activity_capture_frequency_minutes = preferences.activity_capture.frequency_minutes
            logger.info(f"Loaded capture frequency: {self.activity_capture_frequency_minutes} minutes")
        except Exception as e:
            logger.warning(f"Failed to load capture frequency, using default: {e}")
        
        self.is_capture_active = True
        self.last_activity_capture_time = datetime.now()
        
        # Start the capture loop
        self.activity_capture_task = asyncio.create_task(self._activity_capture_loop())
        
        logger.info(f"🔄 Activity capture started - capturing every {self.activity_capture_frequency_minutes} minutes")
    
    async def stop_activity_capture(self) -> None:
        """Stop automatic activity capture."""
        if not self.is_capture_active:
            logger.warning("Activity capture is not active")
            return
            
        self.is_capture_active = False
        
        # Cancel the capture task
        if self.activity_capture_task:
            self.activity_capture_task.cancel()
            try:
                await self.activity_capture_task
            except asyncio.CancelledError:
                pass
            self.activity_capture_task = None
        
        logger.info("🛑 Activity capture stopped")
    
    async def configure_activity_capture_frequency(self, frequency_minutes: float) -> None:
        """Update capture frequency on the running service.

        The capture loop re-reads self.activity_capture_frequency_minutes each
        tick, so the new cadence applies on the next iteration without a restart.
        Safe to call whether or not capture is currently active.
        """
        old_frequency = self.activity_capture_frequency_minutes
        self.activity_capture_frequency_minutes = frequency_minutes
        logger.info(
            f"🔄 Activity capture frequency updated from {old_frequency} "
            f"to {frequency_minutes} minutes (applies on next loop tick)"
        )
    
    async def get_status(self) -> Dict[str, Any]:
        """Get current capture status."""
        next_capture_time = None
        if self.is_capture_active and self.last_activity_capture_time:
            next_capture_time = self.last_activity_capture_time + timedelta(minutes=self.activity_capture_frequency_minutes)
        
        return {
            "enabled": self.is_capture_active,
            "frequency_minutes": self.activity_capture_frequency_minutes,
            "last_capture_time": self.last_activity_capture_time.isoformat() if self.last_activity_capture_time else None,
            "next_capture_time": next_capture_time.isoformat() if next_capture_time else None,
            "skipped_capture_count": self.skipped_capture_count,
            "compacted_capture_count": self.compacted_capture_count,
            "last_policy_decision": self.last_policy_decision,
            "last_policy_decision_time": (
                self.last_policy_decision_time.isoformat()
                if self.last_policy_decision_time
                else None
            ),
        }
    
    async def _activity_capture_loop(self) -> None:
        """Main activity capture loop."""
        logger.info("🔄 Activity capture loop started")
        
        try:
            while self.is_capture_active:
                try:
                    # Check if it's time for next capture
                    current_time = datetime.now()
                    
                    if self.last_activity_capture_time is None:
                        # First capture
                        await self._perform_capture()
                    else:
                        # Check if enough time has passed
                        time_since_last = current_time - self.last_activity_capture_time
                        if time_since_last >= timedelta(minutes=self.activity_capture_frequency_minutes):
                            await self._perform_capture()
                    
                    # Sleep for 30 seconds before checking again
                    await asyncio.sleep(30)
                    
                except Exception as e:
                    logger.error(f"Error in activity capture loop: {e}", exc_info=True)
                    # Continue running even if individual captures fail
                    await asyncio.sleep(60)  # Wait longer after errors
                    
        except asyncio.CancelledError:
            logger.info("Activity capture loop canceled")
            raise
        except Exception as e:
            logger.error(f"Fatal error in activity capture loop: {e}", exc_info=True)
            self.is_capture_active = False
    
    async def _perform_capture(self) -> Optional[ActivityCaptureRecord]:
        """Perform a single activity capture."""
        capture_id = str(uuid.uuid4())
        timestamp = datetime.now()
        automatic = True
        
        logger.info(f"📸 Starting automatic activity capture {capture_id}")
        
        try:
            from api.core.preferences.preferences_io import load_preferences
            from api.services.capture.shared.activity_capture_exclusion_policy import (
                normalize_excluded_bundle_ids,
            )
            from api.services.capture.shared.window_capture_bridge import (
                trigger_automatic_activity_capture,
            )

            preferences = load_preferences()
            excluded_bundle_ids = normalize_excluded_bundle_ids(
                preferences.activity_capture.excluded_bundle_ids
            )
            
            # Request capture with timeout
            capture_result = await asyncio.wait_for(
                trigger_automatic_activity_capture(excluded_bundle_ids=excluded_bundle_ids),
                timeout=self.activity_capture_timeout_seconds
            )
            
            # Update last capture time (including policy skips)
            self.last_activity_capture_time = timestamp

            if capture_result and capture_result.get("policy_skipped"):
                app_name = capture_result.get("app_name", "Unknown")
                policy_reason = capture_result.get("policy_reason", "excluded_app")
                self.skipped_capture_count += 1
                self.last_policy_decision = f"{app_name}: {policy_reason}"
                self.last_policy_decision_time = timestamp
                logger.info(
                    "Activity capture %s skipped by policy for app %s: %s",
                    capture_id,
                    app_name,
                    policy_reason,
                )
                return None
            
            # Check if capture was successful
            if not capture_result or not capture_result.get("success", False):
                error_msg = capture_result.get("message", "Unknown capture error") if capture_result else "No capture result"
                logger.warning(f"Activity capture {capture_id} failed: {error_msg}")
                
                capture_record = ActivityCaptureRecord(
                    capture_id=capture_id,
                    timestamp=timestamp,
                    app_name="Unknown",
                    window_title="Capture Failed",
                    screenshot_path=None,
                    extracted_text=None,
                    processing_status=ActivityCaptureStatus.FAILED,
                    automatic_capture=automatic,
                    error_message=error_msg
                )
                return capture_record
            
            # Extract capture information
            app_name = capture_result.get("app_name", "Unknown")
            window_title = capture_result.get("window_title", "")
            screenshot_path = capture_result.get("image_path")
            perceptual_hash = capture_result.get("perceptual_hash")
            work_context = derive_work_context(app_name, window_title, capture_id=capture_id)
            
            # Create capture record with PENDING status initially
            capture_record = ActivityCaptureRecord(
                capture_id=capture_id,
                timestamp=timestamp,
                app_name=app_name,
                window_title=window_title,
                screenshot_path=screenshot_path,
                extracted_text=None,  # Will be populated by OCR
                processing_status=ActivityCaptureStatus.PENDING,
                automatic_capture=automatic,
                perceptual_hash=perceptual_hash,
                work_context_key=work_context.key,
            )

            if perceptual_hash and await self._try_compact_into_open_sequence(
                capture_record,
                work_context.key,
            ):
                return None
            
            # Perform OCR immediately after screenshot capture
            if self.ocr_service and screenshot_path:
                logger.info(f"🔍 Performing immediate OCR for capture {capture_id}")
                try:
                    ocr_result = await asyncio.to_thread(
                        self.ocr_service.extract_text,
                        screenshot_path,
                    )
                    if ocr_result.status == "success" and ocr_result.processed_text:
                        capture_record.extracted_text = ocr_result.processed_text
                        capture_record.processing_status = ActivityCaptureStatus.OCR_COMPLETE
                        logger.info(f"✅ OCR completed for capture {capture_id}: {len(ocr_result.processed_text)} characters")
                    else:
                        logger.warning(f"⚠️ OCR failed for capture {capture_id}: {ocr_result.status}")
                        capture_record.processing_status = ActivityCaptureStatus.PENDING
                except Exception as e:
                    logger.error(f"❌ OCR failed for capture {capture_id}: {e}")
                    capture_record.processing_status = ActivityCaptureStatus.PENDING
            else:
                logger.warning(f"⚠️ OCR service not available for capture {capture_id}")
                capture_record.processing_status = ActivityCaptureStatus.PENDING
            
            # Store in knowledge base with the appropriate status
            await self._store_capture_record(capture_record)

            processing_mode = str(
                getattr(preferences.activity_capture, "processing_mode", "scheduled")
            ).lower()
            if processing_mode in {"real_time", "realtime"}:
                from api.services.capture.automatic.activity_capture_runtime import (
                    get_automatic_processing_service_instance,
                )

                processing_service = get_automatic_processing_service_instance()
                if processing_service is None:
                    logger.warning(
                        "Activity capture %s is queued because real-time processing is unavailable",
                        capture_record.capture_id,
                    )
                else:
                    processing_result = await processing_service.process_pending_activities_now()
                    logger.info(
                        "Real-time processing request for activity %s: %s",
                        capture_record.capture_id,
                        processing_result.get("message", "no status returned"),
                    )
            
            logger.info(f"✅ Activity capture {capture_id} completed successfully (app: {app_name})")
            return capture_record
            
        except asyncio.TimeoutError:
            error_msg = f"Activity capture {capture_id} timed out after {self.activity_capture_timeout_seconds} seconds"
            logger.error(error_msg)
            
            capture_record = ActivityCaptureRecord(
                capture_id=capture_id,
                timestamp=timestamp,
                app_name="Unknown",
                window_title="Capture Timeout",
                screenshot_path=None,
                extracted_text=None,
                processing_status=ActivityCaptureStatus.FAILED,
                automatic_capture=automatic,
                error_message=error_msg
            )
            return capture_record
            
        except Exception as e:
            error_msg = f"Activity capture {capture_id} failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            capture_record = ActivityCaptureRecord(
                capture_id=capture_id,
                timestamp=timestamp,
                app_name="Unknown",
                window_title="Capture Error",
                screenshot_path=None,
                extracted_text=None,
                processing_status=ActivityCaptureStatus.FAILED,
                automatic_capture=automatic,
                error_message=error_msg
            )
            return capture_record
    
    async def _store_capture_record(self, capture_record: ActivityCaptureRecord) -> None:
        """Store an activity capture record in the database."""
        try:
            # Store in activities table with PENDING status
            activity_id = await self.knowledge_service.store_activity(
                timestamp=capture_record.timestamp,
                app_name=capture_record.app_name,
                window_title=capture_record.window_title,
                extracted_text=capture_record.extracted_text,  # Use the extracted text
                ai_analysis=None,     # Will be filled during processing
                duration=0,
                metadata={
                    **derive_work_context(
                        capture_record.app_name,
                        capture_record.window_title,
                        capture_id=capture_record.capture_id,
                    ).as_metadata(),
                    "processing_status": capture_record.processing_status.value,
                    "automatic_capture": capture_record.automatic_capture,
                    "screenshot_path": capture_record.screenshot_path,
                    "capture_id": capture_record.capture_id,
                },
                capture_frequency_minutes=self.activity_capture_frequency_minutes,
                content_fingerprint=capture_record.perceptual_hash,
                observation_count=1,
                last_observed_at=capture_record.timestamp,
            )
            
            # Update the capture record with the database ID
            capture_record.capture_id = activity_id
            
            logger.debug(f"Stored capture record {activity_id} in database with frequency {self.activity_capture_frequency_minutes} minutes")
            
        except Exception as e:
            logger.error(f"Failed to store capture record: {e}", exc_info=True)
            raise

    async def _try_compact_into_open_sequence(
        self,
        capture_record: ActivityCaptureRecord,
        work_context_key: Optional[str],
    ) -> bool:
        """Extend a matching recent activity and remove the redundant screenshot."""
        from api.services.capture.shared.perceptual_similarity import is_functionally_unchanged

        max_age_seconds = max(2 * self.activity_capture_frequency_minutes * 60, 90)
        try:
            candidate = await self.knowledge_service.find_open_sequence_activity(
                app_name=capture_record.app_name,
                work_context_key=work_context_key,
                max_age_seconds=max_age_seconds,
            )
        except Exception as error:
            logger.error(
                "Failed to find an open activity sequence for capture %s: %s",
                capture_record.capture_id,
                error,
            )
            return False

        if not candidate or not is_functionally_unchanged(
            candidate.get("content_fingerprint"),
            capture_record.perceptual_hash,
        ):
            return False

        try:
            reference_timestamp = datetime.fromisoformat(
                candidate.get("last_observed_at") or candidate["timestamp"]
            )
            elapsed_seconds = max(
                int((capture_record.timestamp - reference_timestamp).total_seconds()),
                0,
            )
            observation_count = int(candidate.get("observation_count") or 1) + 1
            duration = int(candidate.get("duration") or 0) + elapsed_seconds

            await self.knowledge_service.update_activity(
                candidate["id"],
                {
                    "observation_count": observation_count,
                    "last_observed_at": capture_record.timestamp.isoformat(),
                    "duration": duration,
                },
            )
        except Exception as error:
            logger.error(
                "Failed to compact capture %s into activity %s: %s",
                capture_record.capture_id,
                candidate["id"],
                error,
                exc_info=True,
            )
            return False

        if capture_record.screenshot_path:
            try:
                os.remove(capture_record.screenshot_path)
            except OSError as error:
                logger.warning(
                    "Could not remove compacted temporary screenshot %s: %s",
                    capture_record.screenshot_path,
                    error,
                )

        self.compacted_capture_count += 1
        self.last_policy_decision = (
            f"{capture_record.app_name}: compacted_into_open_sequence"
        )
        self.last_policy_decision_time = capture_record.timestamp
        logger.info(
            "Compacted capture %s into activity %s (observations=%s, duration=%ss)",
            capture_record.capture_id,
            candidate["id"],
            observation_count,
            duration,
        )
        return True