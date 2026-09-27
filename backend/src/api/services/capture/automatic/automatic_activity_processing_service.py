"""Automatic Activity Processing Service - Background processing of captured activities with OCR and AI analysis."""

import asyncio
import logging
import math
import time
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from api.core.models.model_types import ModelCapability
from api.services.capture.automatic.activity_processing_stage_coordinator import (
    ActivityProcessingStageCoordinator,
)
from api.services.capture.automatic.activity_processing_run_policy import (
    ActivityProcessingRunPolicy,
    resolve_activity_processing_model_id,
    resolve_activity_processing_run_policy,
)
from api.services.capture.shared.activity_capture_status import ActivityCaptureStatus

logger = logging.getLogger(__name__)

# How many failed activities a single run will look at when choosing what to
# retry. The query orders newest-first, so reading one row at a time meant a
# deterministic failure re-selected the same activity forever while every older
# failure starved behind it. Anything beyond this window waits for the next run.
FAILED_RETRY_WINDOW = 200

INTERRUPTED_PROCESSING_ERROR = "Activity processing interrupted by Basil restart."


def _nearest_rank_percentile(values: List[int], percentile: float) -> Optional[int]:
    """Return nearest-rank percentile from a copied integer list."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil((percentile / 100.0) * len(ordered)))
    return ordered[min(rank - 1, len(ordered) - 1)]


def _median_int(values: List[int]) -> Optional[int]:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[midpoint]
    return int(round((ordered[midpoint - 1] + ordered[midpoint]) / 2))


@dataclass(frozen=True)
class ActivityProcessingProgress:
    active: bool = False
    total: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    remaining: int = 0
    cancel_requested: bool = False
    started_at: Optional[datetime] = None
    last_error: Optional[str] = None
    max_records: int = 0
    analysis_concurrency: int = 1
    processing_strategy: str = "sequential"


class AutomaticActivityProcessingService:
    """Background service for processing captured activities."""
    
    def __init__(self, knowledge_service, model_service, image_processor):
        self.knowledge_service = knowledge_service
        self.model_service = model_service
        self.image_processor = image_processor

        # Best-effort contact identity observation extraction (gated behind an
        # off-by-default preference). Discovers candidate contacts from screen
        # text without ever asserting a relationship or failing the pipeline.
        from api.services.capture.automatic.activity_contact_observation_processor import (
            ActivityContactObservationProcessor,
        )
        self.contact_observation_processor = ActivityContactObservationProcessor(
            knowledge_service, image_processor
        )
        
        # Processing state
        self.is_processing_active = False
        self.scheduled_processing_hour = 14  # Default 2 PM
        self.scheduled_processing_minute = 0
        self.last_scheduled_processing_date: Optional[datetime] = None
        
        # Background tasks
        self.scheduled_processing_task: Optional[asyncio.Task] = None
        self._current_processing_task: Optional[asyncio.Task] = None
        self._processing_start_lock = asyncio.Lock()
        self._model_stage_semaphore = asyncio.Semaphore(1)
        self._processing_progress = ActivityProcessingProgress()
        self._processing_run_id: Optional[str] = None
        self._active_run_policy: Optional[ActivityProcessingRunPolicy] = None
        self._selected_at_by_activity_id: Dict[str, float] = {}
        self._generation_telemetry_for_run: List[Dict[str, Any]] = []
        
        logger.info("AutomaticActivityProcessingService initialized")

    async def recover_interrupted_processing_activities(self) -> int:
        """Mark stranded PROCESSING rows as FAILED after an unclean shutdown."""
        interrupted = await self.knowledge_service.search_activities(
            metadata_filters={"processing_status": "PROCESSING"},
            limit=1000,
        )
        for activity in interrupted:
            await self._update_activity_processing_status(
                activity.id,
                ActivityCaptureStatus.FAILED,
                processing_completed_at=datetime.now(),
                error_message=INTERRUPTED_PROCESSING_ERROR,
            )
        if interrupted:
            logger.info(
                "Recovered %s interrupted activity-capture processing row(s)",
                len(interrupted),
            )
        return len(interrupted)
    
    async def start_processing_service(self) -> None:
        """Start the background processing service."""
        if self.is_processing_active:
            logger.warning("Activity processing service is already active")
            return
            
        self.is_processing_active = True
        
        # Load settings from preferences
        try:
            from api.core.preferences.preferences_io import load_preferences
            preferences = load_preferences()
            
            # Parse scheduled processing time from string format (HH:MM)
            scheduled_time_str = preferences.activity_capture.scheduled_processing_time
            time_parts = scheduled_time_str.split(":")
            if len(time_parts) == 2:
                self.scheduled_processing_hour = int(time_parts[0])
                self.scheduled_processing_minute = int(time_parts[1])
            else:
                # Fallback if parsing fails
                self.scheduled_processing_hour = 14
                self.scheduled_processing_minute = 0
                
            logger.info(f"Loaded processing schedule: {self.scheduled_processing_hour:02d}:{self.scheduled_processing_minute:02d}")
        except Exception as e:
            logger.warning(f"Failed to load processing schedule, using defaults: {e}")

        await self.recover_interrupted_processing_activities()
        
        # Start the scheduled processing loop
        self.scheduled_processing_task = asyncio.create_task(self._scheduled_processing_loop())
        
        logger.info(f"🔄 Activity processing service started - scheduled daily at {self.scheduled_processing_hour:02d}:{self.scheduled_processing_minute:02d}")
    
    async def stop_processing_service(self) -> None:
        """Stop the background processing service."""
        if not self.is_processing_active:
            logger.warning("Activity processing service is not active")
            return
            
        self.is_processing_active = False
        
        # Cancel processing tasks
        if self.scheduled_processing_task:
            self.scheduled_processing_task.cancel()
            try:
                await self.scheduled_processing_task
            except asyncio.CancelledError:
                pass
            self.scheduled_processing_task = None
        
        if self._current_processing_task:
            self._current_processing_task.cancel()
            try:
                await self._current_processing_task
            except asyncio.CancelledError:
                pass
            self._current_processing_task = None
        
        logger.info("🛑 Activity processing service stopped")
    
    async def get_status(self) -> Dict[str, Any]:
        """Get current processing status."""
        # Calculate next scheduled processing time
        next_scheduled_processing_time = None
        if self.is_processing_active:
            now = datetime.now()
            next_scheduled = now.replace(hour=self.scheduled_processing_hour, minute=self.scheduled_processing_minute, second=0, microsecond=0)
            if next_scheduled <= now:
                next_scheduled += timedelta(days=1)
            next_scheduled_processing_time = next_scheduled
        
        # Get counts from database
        try:
            pending_count = (
                await self.knowledge_service.count_activities_by_metadata(
                    "processing_status", ActivityCaptureStatus.PENDING.value
                )
                + await self.knowledge_service.count_activities_by_metadata(
                    "processing_status", ActivityCaptureStatus.OCR_COMPLETE.value
                )
            )
            failed_count = await self.knowledge_service.count_activities_by_metadata(
                "processing_status", ActivityCaptureStatus.FAILED.value
            )
            
        except Exception as e:
            logger.error(f"Failed to get processing counts: {e}")
            pending_count = 0
            failed_count = 0
        
        return {
            "enabled": self.is_processing_active,
            "next_scheduled_processing_time": next_scheduled_processing_time.isoformat() if next_scheduled_processing_time else None,
            "pending_activities_count": pending_count,
            "failed_activities_count": failed_count,
            "scheduled_processing_hour": self.scheduled_processing_hour,
            "is_currently_processing": self._current_processing_task is not None and not self._current_processing_task.done()
        }
    
    async def process_pending_activities_now(self) -> Dict[str, Any]:
        """Trigger immediate processing of pending activities in the background."""
        started = await self._start_processing_run(is_manual_backlog_run=True)
        if started is None:
            return {
                "success": False,
                "message": "Processing is already in progress",
            }

        progress = self._processing_progress
        return {
            "success": True,
            "message": f"Background processing started for {progress.total} activities",
            "processed_count": 0,
            "failed_count": 0,
            "total_count": progress.total,
            "processing_started": True,
            "progress": self._progress_as_dict(),
        }

    def get_processing_progress(self) -> ActivityProcessingProgress:
        return self._processing_progress

    def request_processing_cancellation(self) -> bool:
        if not self._processing_progress.active:
            return False
        self._processing_progress = replace(
            self._processing_progress,
            cancel_requested=True,
        )
        return True

    def _progress_as_dict(self) -> Dict[str, Any]:
        payload = asdict(self._processing_progress)
        started_at = self._processing_progress.started_at
        payload["started_at"] = started_at.isoformat() if started_at else None
        return payload

    async def _calculate_eligible_count(self) -> int:
        pending_count = await self.knowledge_service.count_activities_by_metadata(
            "processing_status", ActivityCaptureStatus.PENDING.value
        )
        ocr_complete_count = await self.knowledge_service.count_activities_by_metadata(
            "processing_status", ActivityCaptureStatus.OCR_COMPLETE.value
        )
        failed_count = await self.knowledge_service.count_activities_by_metadata(
            "processing_status", ActivityCaptureStatus.FAILED.value
        )
        failed_eligible = min(failed_count, FAILED_RETRY_WINDOW)
        return (
            pending_count
            + ocr_complete_count
            + failed_eligible
        )

    async def _start_processing_run(
        self,
        *,
        is_manual_backlog_run: bool = False,
    ) -> Optional[asyncio.Task]:
        async with self._processing_start_lock:
            if self._current_processing_task and not self._current_processing_task.done():
                return None

            from api.core.preferences.preferences_io import load_preferences

            preferences = load_preferences()
            max_records = preferences.activity_capture.processing_max_records
            run_policy = resolve_activity_processing_run_policy(
                preferences.activity_capture.processing_model,
                is_manual_backlog_run=is_manual_backlog_run,
            )
            eligible = await self._calculate_eligible_count()
            total = eligible if max_records == 0 else min(eligible, max_records)

            self._processing_progress = ActivityProcessingProgress(
                active=True,
                total=total,
                remaining=total,
                started_at=datetime.now(),
                max_records=max_records,
                analysis_concurrency=run_policy.analysis_concurrency,
                processing_strategy=run_policy.processing_strategy,
            )

            logger.info(
                "Starting activity-capture processing run for %s eligible record(s) "
                "(cap=%s)",
                total,
                "unlimited" if max_records == 0 else max_records,
            )
            self._processing_run_id = f"activity-processing-{uuid.uuid4().hex}"
            self._active_run_policy = run_policy
            self._generation_telemetry_for_run = []
            logger.info(
                "activity_processing_run_started run_id=%s eligible=%s total=%s "
                "max_records=%s processing_model=%s processing_strategy=%s "
                "analysis_concurrency=%s",
                self._processing_run_id,
                eligible,
                total,
                max_records,
                run_policy.model_id or "default",
                run_policy.processing_strategy,
                run_policy.analysis_concurrency,
            )

            self._current_processing_task = asyncio.create_task(
                self._process_pending_activities(
                    max_records=max_records,
                    run_policy=run_policy,
                )
            )
            return self._current_processing_task

    async def _scheduled_processing_loop(self) -> None:
        """Background loop for scheduled processing of pending activities."""
        logger.info(f"📅 Scheduled processing loop started - will process pending activities daily at {self.scheduled_processing_hour:02d}:{self.scheduled_processing_minute:02d}")
        
        try:
            while self.is_processing_active:
                try:
                    current_time = datetime.now()
                    current_date = current_time.date()
                    
                    # Check if we should process pending activities
                    should_process = False
                    
                    # Check if it's the exact scheduled time and we haven't processed today yet
                    if (current_time.hour == self.scheduled_processing_hour and 
                        current_time.minute == self.scheduled_processing_minute and
                        (self.last_scheduled_processing_date is None or 
                         self.last_scheduled_processing_date.date() < current_date)):
                        should_process = True
                    
                    if should_process:
                        logger.info(f"⏰ Scheduled processing time reached: {current_time.strftime('%H:%M')}")
                        
                        task = await self._start_processing_run(is_manual_backlog_run=False)
                        if task is not None:
                            await task
                            self.last_scheduled_processing_date = current_time
                        else:
                            logger.info(
                                "Scheduled processing skipped because a run is already active"
                            )
                    
                    # Sleep for 1 minute before checking again
                    await asyncio.sleep(60)
                    
                except Exception as e:
                    logger.error(f"Error in scheduled processing loop: {e}", exc_info=True)
                    await asyncio.sleep(300)  # Wait 5 minutes after errors
                    
        except asyncio.CancelledError:
            logger.info("Scheduled processing loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Fatal error in scheduled processing loop: {e}", exc_info=True)
            self.is_processing_active = False
    
    def _resolve_batch_model_id(self) -> Optional[str]:
        """Canonical registry id of the model this batch processes with.

        The activity_capture.processing_model preference can hold either a
        canonical id or a display_name, so fall back to display_name lookup.
        """
        from api.core.models.preferences import Preferences

        configured = Preferences.load().activity_capture.processing_model
        return resolve_activity_processing_model_id(configured)

    async def _stage_failed_retry_candidates(self) -> None:
        """Re-stage failed work once so it cannot spin in the same run."""
        failed = await self.knowledge_service.search_activities(
            metadata_filters={"processing_status": ActivityCaptureStatus.FAILED.value},
            limit=FAILED_RETRY_WINDOW,
        )
        for activity in failed:
            status = (
                ActivityCaptureStatus.OCR_COMPLETE
                if (getattr(activity, "extracted_text", None) or "").strip()
                else ActivityCaptureStatus.PENDING
            )
            await self._update_activity_processing_status(activity.id, status)
            if hasattr(activity, "metadata") and isinstance(activity.metadata, dict):
                activity.metadata["processing_status"] = status.value

    async def _process_pending_activities(
        self,
        *,
        max_records: int = 0,
        run_policy: Optional[ActivityProcessingRunPolicy] = None,
    ) -> Dict[str, Any]:
        """Run independent OCR preparation and bounded analysis workers."""
        run_id = self._processing_run_id or f"activity-processing-{uuid.uuid4().hex}"
        run_started_at = time.perf_counter()
        run_outcome = "completed"
        run_policy = run_policy or self._active_run_policy or ActivityProcessingRunPolicy(
            model_id="",
            analysis_concurrency=1,
            processing_strategy="sequential",
        )
        progress = self._processing_progress
        logger.info(
            "activity_processing_run_processing_started run_id=%s analysis_concurrency=%s "
            "processing_strategy=%s",
            run_id,
            run_policy.analysis_concurrency,
            run_policy.processing_strategy,
        )

        def publish_analysis_result(activity: Any, error: Optional[BaseException]) -> None:
            nonlocal progress
            processed = progress.processed + 1
            if error is None:
                logger.info(
                    "activity_processing_item_completed run_id=%s activity_id=%s",
                    run_id,
                    activity.id,
                )
                progress = replace(
                    progress,
                    processed=processed,
                    succeeded=progress.succeeded + 1,
                    remaining=max(progress.total - processed, 0),
                    cancel_requested=self._processing_progress.cancel_requested,
                )
            else:
                logger.error(
                    "activity_processing_item_failed run_id=%s activity_id=%s exception_type=%s",
                    run_id,
                    activity.id,
                    type(error).__name__,
                )
                progress = replace(
                    progress,
                    processed=processed,
                    failed=progress.failed + 1,
                    remaining=max(progress.total - processed, 0),
                    last_error=str(error),
                    cancel_requested=self._processing_progress.cancel_requested,
                )
            self._processing_progress = progress

        try:
            await self._stage_failed_retry_candidates()

            async def process_pending_ocr(activity: Any) -> None:
                await self._process_pending_ocr_activity(activity)

            async def process_ocr_complete(activity: Any) -> None:
                self._selected_at_by_activity_id[activity.id] = time.perf_counter()
                await self._process_ocr_complete_activity(activity)

            result = await ActivityProcessingStageCoordinator(
                search_activities=self.knowledge_service.search_activities,
                process_pending_ocr=process_pending_ocr,
                process_ocr_complete=process_ocr_complete,
                publish_analysis_result=publish_analysis_result,
                cancellation_requested=lambda: self._processing_progress.cancel_requested,
                max_analysis_records=max_records,
                analysis_concurrency=run_policy.analysis_concurrency,
            ).run()
            if result.analysis_exhausted and not result.reached_analysis_cap:
                progress = replace(progress, total=progress.processed, remaining=0)
                self._processing_progress = progress

            if progress.processed == 0:
                logger.info("✅ No activities found to analyze")
            else:
                logger.info(
                    "✅ Activity processing completed: %s successful, %s failed out of %s total",
                    progress.succeeded,
                    progress.failed,
                    progress.processed,
                )
            return {
                "success": True,
                "processed_count": progress.succeeded,
                "failed_count": progress.failed,
                "total_count": progress.processed,
            }
        except Exception as e:
            run_outcome = "failed"
            logger.error("Activity processing run failed: %s", e, exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "processed_count": progress.succeeded,
                "failed_count": progress.failed,
                "total_count": progress.processed,
            }
        finally:
            try:
                model_manager = getattr(self.model_service, "model_manager", None)
                batch_model_id = run_policy.model_id or self._resolve_batch_model_id()
                if batch_model_id and model_manager is not None:
                    await model_manager.unload_model(batch_model_id)
                    logger.info("🧹 Model %s unloaded after activity processing", batch_model_id)
            except Exception as e:
                logger.warning("Failed to unload model after processing: %s", e)
            self._emit_generation_summary(run_id)
            total_ms = int((time.perf_counter() - run_started_at) * 1000)
            logger.info(
                "activity_processing_run_completed run_id=%s outcome=%s processed=%s "
                "succeeded=%s failed=%s cancelled=%s total_ms=%s average_item_ms=%s",
                run_id,
                "cancelled" if self._processing_progress.cancel_requested else run_outcome,
                progress.processed,
                progress.succeeded,
                progress.failed,
                self._processing_progress.cancel_requested,
                total_ms,
                total_ms // progress.processed if progress.processed else 0,
            )
            self._selected_at_by_activity_id.clear()
            self._generation_telemetry_for_run = []
            self._processing_progress = replace(
                progress,
                active=False,
                cancel_requested=self._processing_progress.cancel_requested,
            )
            self._processing_run_id = None
            self._active_run_policy = None

    def _record_generation_telemetry(self, telemetry: Optional[Dict[str, Any]]) -> None:
        if telemetry:
            self._generation_telemetry_for_run.append(dict(telemetry))

    def _emit_generation_summary(self, run_id: str) -> None:
        telemetry_rows = list(self._generation_telemetry_for_run)
        if not telemetry_rows:
            return

        completion_tokens = [
            int(row["raw_completion_tokens"])
            for row in telemetry_rows
            if isinstance(row.get("raw_completion_tokens"), int)
        ]
        native_durations = [
            int(row["native_duration_ms"])
            for row in telemetry_rows
            if isinstance(row.get("native_duration_ms"), int)
        ]
        raw_minus_visible = []
        for row in telemetry_rows:
            raw = row.get("raw_completion_tokens")
            visible = row.get("visible_completion_tokens")
            if isinstance(raw, int) and isinstance(visible, int) and raw >= visible:
                raw_minus_visible.append(raw - visible)

        requested_caps = {
            int(row["requested_output_tokens"])
            for row in telemetry_rows
            if isinstance(row.get("requested_output_tokens"), int)
        }
        finish_reasons = {
            str(row.get("finish_reason"))
            for row in telemetry_rows
            if row.get("finish_reason") is not None
        }
        cap_hit_count = sum(
            1
            for row in telemetry_rows
            if bool(row.get("cap_hit"))
        )
        length_finish_count = sum(
            1
            for row in telemetry_rows
            if str(row.get("finish_reason", "")).lower() == "length"
        )
        parse_error_count = sum(
            1 for row in telemetry_rows if str(row.get("parse_outcome", "")) == "error"
        )

        logger.info(
            "activity_processing_generation_summary run_id=%s attempt_count=%s "
            "known_completion_count=%s completion_tokens_min=%s completion_tokens_median=%s "
            "completion_tokens_p95=%s completion_tokens_max=%s requested_caps=%s "
            "finish_reasons=%s cap_hit_count=%s length_finish_count=%s parse_error_count=%s "
            "native_duration_median_ms=%s raw_minus_visible_median=%s",
            run_id,
            len(telemetry_rows),
            len(completion_tokens),
            min(completion_tokens) if completion_tokens else None,
            _median_int(completion_tokens),
            _nearest_rank_percentile(completion_tokens, 95.0),
            max(completion_tokens) if completion_tokens else None,
            ",".join(str(value) for value in sorted(requested_caps)),
            ",".join(sorted(finish_reasons)),
            cap_hit_count,
            length_finish_count,
            parse_error_count,
            _median_int(native_durations),
            _median_int(raw_minus_visible),
        )
    
    def _log_activity_stage(
        self,
        run_id: str,
        activity_id: str,
        stage: str,
        duration_ms: int = 0,
        *,
        outcome: str = "started",
        **metadata: Any,
    ) -> None:
        """Log privacy-safe processing-stage diagnostics for one activity."""
        duration_field = {
            "queue_wait": "queue_wait_ms",
            "status_update": "status_update_ms",
            "ocr": "ocr_ms",
            "model_acquisition": "model_acquisition_ms",
            "analysis": "analysis_ms",
            "contact_enrichment": "contact_enrichment_ms",
            "persistence": "persistence_ms",
            "screenshot_move": "screenshot_move_ms",
            "total": "total_ms",
        }.get(stage, "duration_ms")
        scalar_metadata = {
            key: value
            for key, value in metadata.items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }
        metadata_text = " ".join(
            f"{key}={value}" for key, value in scalar_metadata.items()
        )
        logger.info(
            "activity_processing_stage run_id=%s activity_id=%s stage=%s outcome=%s "
            "duration_ms=%s %s=%s%s",
            run_id,
            activity_id,
            stage,
            outcome,
            duration_ms,
            duration_field,
            duration_ms,
            f" {metadata_text}" if metadata_text else "",
        )
        if stage in {
            "persistence_core_update",
            "persistence_metadata_update",
            "screenshot_move",
        } and outcome in {"completed", "failed", "skipped"}:
            logger.info(
                "activity_persistence_stage_completed run_id=%s activity_id=%s "
                "operation=%s outcome=%s duration_ms=%s",
                run_id,
                activity_id,
                stage,
                outcome,
                duration_ms,
            )

    @staticmethod
    def _screenshot_path_for_activity(activity) -> Optional[str]:
        metadata = getattr(activity, "metadata", None)
        if isinstance(metadata, dict):
            return metadata.get("screenshot_path")
        if metadata:
            for item in metadata:
                if getattr(item, "key", None) == "screenshot_path":
                    return getattr(item, "value", None)
        return None

    async def _process_pending_ocr_activity(self, activity) -> None:
        """Prepare one PENDING activity for the sequential analysis worker."""
        run_id = self._processing_run_id or "activity-processing-direct"
        started_at = time.perf_counter()
        try:
            extracted_text = (getattr(activity, "extracted_text", None) or "").strip()
            if not extracted_text:
                screenshot_path = self._screenshot_path_for_activity(activity)
                if not screenshot_path:
                    raise RuntimeError("No screenshot path found in activity metadata")
                self._log_activity_stage(run_id, activity.id, "ocr")
                extracted_text = (
                    await asyncio.to_thread(self.image_processor.extract_text, screenshot_path)
                ).strip()
                if not extracted_text:
                    raise RuntimeError("OCR returned no text")
                await self.knowledge_service.update_activity(
                    activity.id,
                    {"extracted_text": extracted_text},
                )
                activity.extracted_text = extracted_text
                self._log_activity_stage(
                    run_id,
                    activity.id,
                    "ocr",
                    int((time.perf_counter() - started_at) * 1000),
                    outcome="completed",
                    text_chars=len(extracted_text),
                )
            else:
                self._log_activity_stage(
                    run_id,
                    activity.id,
                    "ocr",
                    outcome="skipped",
                    reason="already_extracted",
                    text_chars=len(extracted_text),
                )
            await self._update_activity_processing_status(
                activity.id,
                ActivityCaptureStatus.OCR_COMPLETE,
            )
            if isinstance(getattr(activity, "metadata", None), dict):
                activity.metadata["processing_status"] = ActivityCaptureStatus.OCR_COMPLETE.value
        except Exception as exc:
            message = f"Failed to OCR activity {activity.id}: {exc}"
            self._log_activity_stage(
                run_id,
                activity.id,
                "ocr",
                int((time.perf_counter() - started_at) * 1000),
                outcome="failed",
                exception_type=type(exc).__name__,
            )
            await self._update_activity_processing_status(
                activity.id,
                ActivityCaptureStatus.FAILED,
                processing_completed_at=datetime.now(),
                error_message=message,
            )
            raise

    async def _process_ocr_complete_activity(self, activity) -> None:
        """Analyze one OCR_COMPLETE activity without repeating OCR."""
        run_id = self._processing_run_id or "activity-processing-direct"
        activity_started_at = time.perf_counter()
        selected_at = self._selected_at_by_activity_id.pop(activity.id, activity_started_at)
        try:
            self._log_activity_stage(
                run_id,
                activity.id,
                "queue_wait",
                int((activity_started_at - selected_at) * 1000),
                outcome="completed",
            )
            # Update status to PROCESSING
            processing_started_at = datetime.now()
            status_started_at = time.perf_counter()
            self._log_activity_stage(run_id, activity.id, "status_update")
            await self._update_activity_processing_status(
                activity.id, 
                ActivityCaptureStatus.PROCESSING,
                processing_started_at=processing_started_at
            )
            self._log_activity_stage(
                run_id,
                activity.id,
                "status_update",
                int((time.perf_counter() - status_started_at) * 1000),
                outcome="completed",
            )
            
            logger.info(f"🔄 Processing activity {activity.id}")
            
            # Yield control to allow other operations
            await asyncio.sleep(0)
            
            extracted_text = (getattr(activity, "extracted_text", None) or "").strip()
            if not extracted_text:
                raise RuntimeError("OCR_COMPLETE activity has no extracted text")
            ai_analysis_result = await self._perform_ai_analysis_only(activity, extracted_text)
            
            self._record_generation_telemetry(
                self._generation_telemetry_from_analysis_result(ai_analysis_result)
            )
            self._raise_if_activity_analysis_unusable(ai_analysis_result)

            # Update activity in database with processing results
            persistence_started_at = time.perf_counter()
            self._log_activity_stage(run_id, activity.id, "persistence")
            await self._store_processing_results(
                activity,
                ai_analysis_result,
                processing_started_at,
                run_id=run_id,
            )
            self._log_activity_stage(
                run_id,
                activity.id,
                "persistence",
                int((time.perf_counter() - persistence_started_at) * 1000),
                outcome="completed",
            )

            # Best-effort: derive contact identity observations from the stored
            # OCR/AI results. Gated by preference and never fails the activity.
            contact_started_at = time.perf_counter()
            self._log_activity_stage(run_id, activity.id, "contact_enrichment")
            await self.contact_observation_processor.process(
                activity,
                ai_analysis_result,
                model_stage_semaphore=self._model_stage_semaphore,
                run_id=run_id,
            )
            self._log_activity_stage(
                run_id,
                activity.id,
                "contact_enrichment",
                int((time.perf_counter() - contact_started_at) * 1000),
                outcome="completed",
            )
            
            logger.info(f"✅ Successfully processed activity {activity.id}")
            self._log_activity_stage(
                run_id,
                activity.id,
                "total",
                int((time.perf_counter() - activity_started_at) * 1000),
                outcome="completed",
                analysis_model_id=ai_analysis_result.get("model_used"),
                analysis_requested_tokens=4096,
                analysis_output_chars=len(str(ai_analysis_result.get("analysis") or "")),
            )
            
        except Exception as e:
            error_msg = f"Failed to process activity {activity.id}: {str(e)}"
            logger.error(
                "Activity processing failed for %s (%s)",
                activity.id,
                type(e).__name__,
            )
            self._log_activity_stage(
                run_id,
                activity.id,
                "failed",
                int((time.perf_counter() - activity_started_at) * 1000),
                outcome="failed",
                exception_type=type(e).__name__,
            )
            
            # Update status to FAILED
            await self._update_activity_processing_status(
                activity.id,
                ActivityCaptureStatus.FAILED,
                error_message=error_msg,
                processing_completed_at=datetime.now()
            )
            raise
    
    def _generation_telemetry_from_analysis_result(
        self,
        ai_analysis_result: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        telemetry = ai_analysis_result.get("generation_telemetry")
        if not isinstance(telemetry, dict):
            return None
        merged = dict(telemetry)
        parse_outcome = ai_analysis_result.get("parse_outcome")
        if isinstance(parse_outcome, str):
            merged["parse_outcome"] = parse_outcome
        return merged

    @staticmethod
    def _raise_if_activity_analysis_unusable(
        ai_analysis_result: Dict[str, Any],
    ) -> None:
        analysis_type = ai_analysis_result.get("analysis_type")
        if analysis_type == "none":
            raise RuntimeError("AI analysis failed - no reasoning model was successfully loaded")
        if analysis_type == "error":
            raise RuntimeError("AI analysis failed - error during processing")
        if not ai_analysis_result.get("analysis"):
            raise RuntimeError("AI analysis failed - no analysis object returned")

    async def _perform_ai_analysis_only(self, activity, extracted_text: str) -> Dict[str, Any]:
        """Perform AI analysis only (OCR already done during capture)."""
        run_id = self._processing_run_id or "activity-processing-direct"
        stage = "model_acquisition"
        stage_started_at = time.perf_counter()
        try:
            # Get the configured processing model from preferences
            from api.core.preferences.preferences_io import load_preferences
            from api.services.image_processing.image_processing_service import resolve_activity_analysis_output_tokens

            active_run_policy = self._active_run_policy
            preferences = load_preferences()
            processing_model = (
                active_run_policy.model_id
                if active_run_policy is not None and active_run_policy.model_id
                else preferences.activity_capture.processing_model
            )
            is_parallel_api_run = (
                active_run_policy is not None
                and active_run_policy.processing_strategy == "api_parallel"
            )

            # Extract app name for context
            app_name = activity.app_name

            async def invoke_analysis(model, requested_tokens: int) -> Dict[str, Any]:
                nonlocal stage, stage_started_at
                stage = "analysis"
                stage_started_at = time.perf_counter()
                self._log_activity_stage(run_id, activity.id, "analysis")
                result = await self.image_processor.analyze_text_only(
                    extracted_text,
                    app_name,
                    pre_loaded_model=model,
                    model_id=processing_model,
                    activity_generation_context={
                        "run_id": run_id,
                        "activity_id": activity.id,
                        "analysis_model_id": processing_model,
                        "analysis_requested_tokens": requested_tokens,
                    },
                )
                self._log_activity_stage(
                    run_id,
                    activity.id,
                    "analysis",
                    int((time.perf_counter() - stage_started_at) * 1000),
                    outcome="completed",
                    analysis_model_id=processing_model,
                    analysis_requested_tokens=requested_tokens,
                    analysis_output_chars=len(str(result.get("analysis") or "")),
                )
                return result

            # Load the reasoning model for analysis
            model_wait_started_at = time.perf_counter()
            self._log_activity_stage(run_id, activity.id, "model_acquisition")
            async with self._model_stage_semaphore:
                self._log_activity_stage(
                    run_id,
                    activity.id,
                    "model_stage_wait",
                    int((time.perf_counter() - model_wait_started_at) * 1000),
                    outcome="completed",
                )
                model_stage_started_at = time.perf_counter()
                stage_started_at = model_stage_started_at
                reasoning_model = await self.image_processor._get_model_for_task(
                    {ModelCapability.REASONING},
                    model_id=processing_model,
                )
                self._log_activity_stage(
                    run_id,
                    activity.id,
                    "model_acquisition",
                    int((time.perf_counter() - model_stage_started_at) * 1000),
                    outcome="completed",
                    analysis_model_id=processing_model,
                    handler=getattr(reasoning_model, "handler", None),
                )

                if not reasoning_model:
                    raise Exception("AI analysis failed - no reasoning model was successfully loaded")

                analysis_max_tokens = resolve_activity_analysis_output_tokens(reasoning_model)

                # For a sequential run, keep the analysis call inside the semaphore
                # so the next activity's model acquisition waits for it. For an
                # api_parallel run, only the (cheap) model acquisition is
                # serialized here - the network-bound call below runs outside the
                # semaphore so up to analysis_concurrency HTTP calls can overlap.
                if not is_parallel_api_run:
                    analysis_result = await invoke_analysis(reasoning_model, analysis_max_tokens)

            if is_parallel_api_run:
                analysis_result = await invoke_analysis(reasoning_model, analysis_max_tokens)

            logger.info(f"✅ AI-only analysis completed for {activity.id}")
            
            # analyze_text_only returns the analysis wrapped alongside its own
            # metadata, so unwrap it here. Passing the whole envelope through made
            # ai_analysis_result["analysis"] a dict, and _store_processing_results
            # calls .dict() on it - the AttributeError that failed every activity
            # whose OCR was already done.
            return {
                "extracted_text": extracted_text,  # Use existing OCR text
                "analysis": analysis_result["analysis"],
                "analysis_type": analysis_result.get("analysis_type", "text_only"),
                "processing_time_ms": analysis_result.get("processing_time_ms", 0),
                "model_used": processing_model,
                "generation_telemetry": analysis_result.get("generation_telemetry"),
                "parse_outcome": analysis_result.get("parse_outcome", "success"),
            }
            
        except Exception as e:
            self._log_activity_stage(
                run_id,
                activity.id,
                stage,
                int((time.perf_counter() - stage_started_at) * 1000),
                outcome="failed",
                exception_type=type(e).__name__,
            )
            logger.error(
                "AI-only analysis failed for activity %s at %s (%s)",
                activity.id,
                stage,
                type(e).__name__,
            )
            raise
    
    async def _store_processing_results(
        self,
        activity,
        ai_analysis_result: Dict[str, Any],
        processing_started_at: datetime,
        *,
        run_id: Optional[str] = None,
    ) -> None:
        """Store the results of AI analysis in the database."""
        run_id = run_id or self._processing_run_id or "activity-processing-direct"
        persistence_stage = "serialization"
        persistence_stage_started_at = time.perf_counter()
        try:
            # Convert analysis dict to JSON string for SQLite TEXT column storage
            import json
            ai_analysis_json = None
            if ai_analysis_result["analysis"]:
                ai_analysis_json = json.dumps(ai_analysis_result["analysis"].dict())
            
            # First update the core activity fields (extracted_text and ai_analysis)
            persistence_stage = "persistence_core_update"
            core_update_started_at = time.perf_counter()
            persistence_stage_started_at = core_update_started_at
            await self.knowledge_service.update_activity(
                activity_id=activity.id,
                updates={
                    "extracted_text": ai_analysis_result["extracted_text"],
                    "ai_analysis": ai_analysis_json
                }
            )
            self._log_activity_stage(
                run_id,
                activity.id,
                "persistence_core_update",
                int((time.perf_counter() - core_update_started_at) * 1000),
                outcome="completed",
            )
            
            # Then update the metadata fields
            persistence_stage = "persistence_metadata_update"
            metadata_update_started_at = time.perf_counter()
            persistence_stage_started_at = metadata_update_started_at
            await self.knowledge_service.update_activity_metadata(
                activity_id=activity.id,
                metadata={
                    "processing_status": ActivityCaptureStatus.COMPLETED.value,
                    "processing_started_at": processing_started_at.isoformat(),
                    "processing_completed_at": datetime.now().isoformat(),
                    "analysis_type": ai_analysis_result["analysis_type"],
                    "processing_time_ms": ai_analysis_result["processing_time_ms"],
                    "model_used": ai_analysis_result["model_used"]
                }
            )
            self._log_activity_stage(
                run_id,
                activity.id,
                "persistence_metadata_update",
                int((time.perf_counter() - metadata_update_started_at) * 1000),
                outcome="completed",
            )
            
            # Move screenshot from temp to permanent storage after successful processing
            screenshot_path = None
            if hasattr(activity, 'metadata') and activity.metadata and isinstance(activity.metadata, dict):
                screenshot_path = activity.metadata.get("screenshot_path")
            
            if screenshot_path:
                persistence_stage = "screenshot_move"
                screenshot_move_started_at = time.perf_counter()
                persistence_stage_started_at = screenshot_move_started_at
                try:
                    from api.core.services.file_storage_service import StorageService
                    from pathlib import Path
                    
                    storage_service = StorageService(development_mode=True)  # Use same mode as main app
                    source_path = Path(screenshot_path)
                    
                    if source_path.exists() and "temp" in str(source_path):
                        # Generate filename based on timestamp and app name
                        timestamp_str = processing_started_at.strftime("%Y%m%d_%H%M%S")
                        safe_app_name = "".join(c for c in activity.app_name if c.isalnum() or c in ('-', '_'))
                        filename = f"capture_{timestamp_str}_{safe_app_name}.png"
                        
                        # Store in permanent location
                        permanent_path = storage_service.store_capture(source_path, filename)
                        
                        # Update the database with the new permanent path
                        await self.knowledge_service.update_activity_metadata(
                            activity_id=activity.id,
                            metadata={"screenshot_path": str(permanent_path)}
                        )
                        
                    self._log_activity_stage(
                        run_id,
                        activity.id,
                        "screenshot_move",
                        int((time.perf_counter() - screenshot_move_started_at) * 1000),
                        outcome="completed",
                    )
                except Exception as e:
                    self._log_activity_stage(
                        run_id,
                        activity.id,
                        "screenshot_move",
                        int((time.perf_counter() - screenshot_move_started_at) * 1000),
                        outcome="failed",
                        exception_type=type(e).__name__,
                    )
                    # Don't fail the entire processing if file move fails
            else:
                self._log_activity_stage(
                    run_id,
                    activity.id,
                    "screenshot_move",
                    outcome="skipped",
                    reason="no_screenshot_path",
                )
            
        except Exception as e:
            self._log_activity_stage(
                run_id,
                activity.id,
                persistence_stage,
                int((time.perf_counter() - persistence_stage_started_at) * 1000),
                outcome="failed",
                exception_type=type(e).__name__,
            )
            logger.error(
                "Failed to store processing results for activity %s (%s)",
                activity.id,
                type(e).__name__,
            )
            raise
    
    async def _update_activity_processing_status(
        self, 
        activity_id: str, 
        status: ActivityCaptureStatus,
        processing_started_at: Optional[datetime] = None,
        processing_completed_at: Optional[datetime] = None,
        error_message: Optional[str] = None
    ) -> None:
        """Update the processing status of an activity."""
        try:
            metadata_updates = {
                "processing_status": status.value
            }
            
            if processing_started_at:
                metadata_updates["processing_started_at"] = processing_started_at.isoformat()
            
            if processing_completed_at:
                metadata_updates["processing_completed_at"] = processing_completed_at.isoformat()
            
            if error_message:
                metadata_updates["error_message"] = error_message
            
            await self.knowledge_service.update_activity_metadata(
                activity_id=activity_id,
                metadata=metadata_updates
            )
            
        except Exception as e:
            logger.error(f"Failed to update processing status for activity {activity_id}: {e}")
            raise