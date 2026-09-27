import logging
import asyncio
import threading
import time
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class VoiceListenerWakeWordManager:
    def __init__(self, wake_word_detector=None, transcription_service=None, orchestration_service=None):
        """
        Initialize the wake word management service.
        
        Args:
            wake_word_detector: The wake word detector instance
            transcription_service: The transcription service instance
            orchestration_service: The agent-task orchestration service instance
        """
        self.wake_word_detector = wake_word_detector
        self.transcription_service = transcription_service
        self.orchestration_service = orchestration_service
        
        # Wake word detection state
        self._is_capturing_agent_task = False
        self._agent_task_cancelled = False
        self._last_wake_word_time = 0.0
        self._wake_word_debounce_seconds = 3.0  # Different utterances - prevent rapid successive agent tasks
        self._same_utterance_debounce_seconds = 0.01  # Same utterance, different models - 10ms window
        
        # Thread-safe lock for wake word detection to prevent race conditions
        self._wake_word_lock = threading.Lock()

    def set_agent_task_state(self, is_capturing: bool, is_cancelled: bool = False):
        """Set the agent-task capture state."""
        self._is_capturing_agent_task = is_capturing
        self._agent_task_cancelled = is_cancelled

    @staticmethod
    def _is_api_transcription_selected() -> bool:
        """Return whether the selected transcription model is API-backed."""
        try:
            from api.core.models.preferences import Preferences
            from api.core.models.models_registry import get_cloud_transcription_models

            preferences = Preferences.load()
            selected_model = preferences.models.transcription_model
            return bool(
                preferences.models.use_api_transcription_models
                and selected_model in get_cloud_transcription_models()
            )
        except Exception as exc:
            logger.debug("Could not determine transcription backend selection: %s", exc)
            return False

    @staticmethod
    def _is_parakeet_selected() -> bool:
        """Return whether the selected transcription model is a Parakeet ONNX model.

        Parakeet (NeMo Conformer-TDT) models cannot be loaded through the
        HuggingFace Whisper Seq2Seq pre-load path; they are built lazily by the
        Parakeet dispatch helpers. Mirrors the guard in WakeWordService so the
        wake-word-triggered warm-up does not crash on 'nemo-conformer-tdt'.
        """
        try:
            from api.core.models.preferences import Preferences
            from api.core.models.models_registry import get_parakeet_transcription_models

            selected = Preferences.load().models.transcription_model
            for model_id, cfg in get_parakeet_transcription_models().items():
                if cfg.get("display_name") == selected or model_id == selected:
                    return True
            return False
        except Exception as exc:
            logger.debug("Could not determine Parakeet transcription selection: %s", exc)
            return False

    def _check_frontend_can_accept_agent_task(self):
        """
        Check if frontend can accept a agent_task by querying frontend operation state.
        Returns True if agent_task can proceed, False if blocked by frontend operation.
        Uses synchronous implementation with timeout to avoid blocking wake word detection.
        """
        try:
            # Quick synchronous check with short timeout to avoid blocking wake word detection
            if self.orchestration_service and hasattr(self.orchestration_service, 'query_frontend_operation_state_sync'):
                return self.orchestration_service.query_frontend_operation_state_sync(timeout_seconds=0.2)
            else:
                logger.warning("⚠️ Orchestration service not available for frontend state check - allowing agent_task")
                return True  # Fail-safe: allow agent_task if we can't check
        except Exception as e:
            logger.warning(f"⚠️ Error checking frontend operation state: {e} - allowing agent_task")
            return True  # Fail-safe: allow agent_task on error

    def _check_widget_state_for_wake_word(self) -> Dict[str, Any]:
        """
        Check widget state to determine if wake word should trigger a new agent task or follow-up.
        Returns dict with: can_accept_agent_task, is_processing, has_completed_result, root_task_id
        """
        try:
            if self.orchestration_service and hasattr(self.orchestration_service, 'query_widget_state_sync'):
                return self.orchestration_service.query_widget_state_sync(timeout_seconds=0.2)
            else:
                logger.debug("Orchestration service not available for widget state check - treating as new agent task")
                return {'can_accept_agent_task': True, 'is_processing': False, 'has_completed_result': False, 'root_task_id': None}
        except Exception as e:
            logger.error(f"Error checking widget state: {e}")
            return {'can_accept_agent_task': True, 'is_processing': False, 'has_completed_result': False, 'root_task_id': None}

    def _handle_wake_word_detected(self, detected_phrase: str):
        """
        Callback executed by WakeWordDetector when a wake word is detected.
        Initiates agent-task capture and processing pipeline.
        """
        logger.info(f"🎯 [WAKE_WORD_CALLBACK] Wake word callback triggered for: '{detected_phrase}'")
        
        # ATOMIC SECTION - Use lock to prevent race conditions between multiple wake word detections
        with self._wake_word_lock:
            # OPERATIONAL STATE CHECK - Prevent duplicate operations
            if self._is_capturing_agent_task:
                logger.info(f"🔄 [WAKE_WORD_CALLBACK] Ignoring wake word '{detected_phrase}' - agent_task operation already in progress (is_capturing_agent_task=True)")
                return
                
            if self._agent_task_cancelled:
                logger.info(f"🔄 [WAKE_WORD_CALLBACK] AgentTask processing was cancelled, ignoring wake word '{detected_phrase}' (agent_task_cancelled=True)")
                return

            # FRONTEND OPERATION STATE CHECK - Prevent agent_tasks during transcription, etc.
            # This is an advisory check for microphone-owner / UI collisions
            # (e.g., assistant-session recording is active). It does NOT
            # represent backend task execution state, which is the gate below.
            frontend_can_accept = self._check_frontend_can_accept_agent_task()
            logger.info(f"🔍 [WAKE_WORD_CALLBACK] Frontend operation state check result: {frontend_can_accept}")
            if not frontend_can_accept:
                logger.info(f"🔄 [WAKE_WORD_CALLBACK] Ignoring wake word '{detected_phrase}' - frontend operation in progress (transcription, AssistantSession, etc.)")
                return

            # BACKEND LIFECYCLE GATE - Prevent overlapping capture/transcription
            # handoffs only. Once an AgentTask is persisted and running under a
            # task:* key, new captures must remain allowed.
            blocking_lifecycle_keys: list = []
            if (
                self.orchestration_service is not None
                and hasattr(self.orchestration_service, "lifecycle_snapshot")
            ):
                try:
                    snapshot = self.orchestration_service.lifecycle_snapshot()
                    blocking_lifecycle_keys = [
                        key for key in snapshot
                        if key.startswith("wake_capture:") or key.startswith("transcription:")
                    ]
                except Exception:
                    blocking_lifecycle_keys = []
            if blocking_lifecycle_keys:
                logger.info(
                    f"🔄 [WAKE_WORD_CALLBACK] Ignoring wake word '{detected_phrase}' - "
                    f"backend capture/transcription lifecycle busy (active keys={blocking_lifecycle_keys})"
                )
                return

            # NOTE: Frontend will decide if this is a follow-up agent task (same as hotkey flow)
            # Backend just sends notification, frontend checks widget state locally

            current_time = time.time()
            time_since_last = current_time - self._last_wake_word_time
            
            # Enhanced multi-model debounce system:
            # 1. Extended same-utterance debounce (1000ms): Multiple OpenWakeWord models detecting same utterance
            #    This allows different models to process the same audio but only triggers one agent task
            #    Handles system delays, buffer processing variations, and ensures robust aggregation
            #    NOTE: Normalize phrase variations (hey_jarvis_v0.1 vs hey_jarvis) for proper aggregation
            extended_same_utterance_debounce = 1.0  # 1 second window - no user says wake word twice in 1s
            if time_since_last < extended_same_utterance_debounce:
                # Normalize phrase for comparison (strip version suffixes)
                normalized_phrase = detected_phrase.replace('_v0.1', '').replace('_v1.0', '').replace('_v2.0', '')
                logger.info(f"🔄 Multiple model detection: '{detected_phrase}' (normalized: '{normalized_phrase}') detected {time_since_last*1000:.0f}ms after previous - aggregating for reliability")
                # Update the time but don't trigger new processing - this detection adds to confidence
                self._last_wake_word_time = current_time
                return
            
            # 2. Regular debounce (3s): Prevent rapid successive different agent tasks
            if time_since_last < self._wake_word_debounce_seconds:
                logger.debug(f"🔄 Ignoring '{detected_phrase}' - debounce active ({time_since_last:.1f}s < {self._wake_word_debounce_seconds}s)")
                return
            
            # ACCEPT THE WAKE WORD - Set operational flag IMMEDIATELY to block other detections
            # CRITICAL: This must happen inside the lock before any async operations
            self._is_capturing_agent_task = True
            self._last_wake_word_time = current_time
            logger.info(f"✅ [WAKE_WORD_CALLBACK] Wake word '{detected_phrase}' ACCEPTED - starting agent_task operation (multiple model detections aggregated)")
            
            # Pre-load transcription model while user is speaking (non-blocking)
            # Skip pre-load when an API transcription model is selected
            if self._is_api_transcription_selected():
                logger.info("✅ API transcription model selected, skipping local model pre-load")
            elif self._is_parakeet_selected():
                logger.info(
                    "✅ Parakeet transcription model selected; skipping HuggingFace "
                    "pre-load (Parakeet service is built lazily by the dispatch helpers)"
                )
            elif self.transcription_service and not self.transcription_service.is_model_loaded():
                logger.info("🚀 Pre-loading transcription model during wake word detection...")
                def load_model_sync():
                    try:
                        self.transcription_service.load_model()
                        logger.info("✅ Transcription model pre-loaded successfully")
                    except Exception as e:
                        logger.error(f"❌ Error pre-loading transcription model: {e}")
                
                # Run model loading in a separate thread to avoid blocking
                model_load_thread = threading.Thread(target=load_model_sync, daemon=True)
                model_load_thread.start()
            else:
                logger.info("✅ Transcription model already loaded")

            # Immediately pause wake word detection to prevent additional triggers
            logger.info("Immediately pausing wake word detection to prevent duplicate triggers...")
            self._pause_wake_word_detection()
            
            # Capture immediate screenshot for context (non-blocking)
            logger.info("📸 Scheduling immediate screenshot capture (non-blocking) at wake word detection...")
            if self.orchestration_service and hasattr(self.orchestration_service, '_capture_immediate_screenshot'):
                def _capture_and_enrich_screenshot():
                    try:
                        data = self.orchestration_service._capture_immediate_screenshot()
                        # Attempt file context detection using the captured app/window snapshot
                        try:
                            if data and data.get('success'):
                                from api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval.file_context_detection_service import FileContextDetectionService
                                detector = FileContextDetectionService()
                                app_hint = data.get('app_name')
                                title_hint = data.get('window_title')
                                # Run detection in this worker thread using its own event loop
                                import asyncio as _asyncio
                                def _run_detection() -> Optional[object]:
                                    loop = _asyncio.new_event_loop()
                                    try:
                                        _asyncio.set_event_loop(loop)
                                        return loop.run_until_complete(
                                            detector.detect_current_file_context(
                                                app_name_hint=app_hint,
                                                window_title_hint=title_hint,
                                            )
                                        )
                                    finally:
                                        loop.close()
                                detection_result = _run_detection()
                                if detection_result and getattr(detection_result, 'detected_filename', None):
                                    data['detected_filename'] = detection_result.detected_filename
                                    data['detected_path'] = detection_result.detected_path
                                    data['detection_confidence'] = detection_result.confidence
                                    data['detection_method'] = detection_result.detection_method
                                    logger.info(f"📎 Snapshot file detection: {detection_result.detected_filename} ({detection_result.detected_path}) via {detection_result.detection_method}")
                                else:
                                    logger.info("📎 Snapshot file detection did not resolve a filename/path")
                        except Exception as e:
                            logger.warning(f"⚠️ Snapshot file detection failed: {e}")

                        # Set (possibly enriched) screenshot data in orchestration service
                        try:
                            self.orchestration_service.set_current_screenshot_data(data)
                            # Sync to main service so Swift audio route can access it
                            if (self.orchestration_service.main_service and 
                                hasattr(self.orchestration_service.main_service, 'set_current_screenshot_data')):
                                logger.info("📸 Syncing screenshot data to main service for Swift audio route")
                                self.orchestration_service.main_service.set_current_screenshot_data(data)
                            else:
                                logger.warning("⚠️ Main service not available for screenshot sync")
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to sync screenshot data: {e}")
                    except Exception as e:
                        logger.warning(f"⚠️ Screenshot capture worker error: {e}")

                threading.Thread(target=_capture_and_enrich_screenshot, daemon=True).start()
            else:
                logger.warning("⚠️ Orchestration service not available for screenshot capture")
            
            # Schedule agent_task processing - STILL INSIDE LOCK to prevent gaps.
            # Wake-word detection runs on the audio capture thread. Backend
            # orchestration (WebSockets, AgentTaskStreamingManager's asyncio.Lock,
            # the agent-task state machine, and the processing_started_event
            # resume gate) all live on the FastAPI startup loop. Scheduling onto
            # any other loop produces cross-loop primitive errors such as
            # "<asyncio.locks.Event ...> is bound to a different event loop".
            processing_started = self._schedule_agent_task_processing(detected_phrase)

            # If we somehow fail to start processing, reset the flag
            if not processing_started:
                logger.error("Failed to start agent_task processing - resetting capture flag")
                self._is_capturing_agent_task = False

    def _schedule_agent_task_processing(self, detected_phrase: str) -> bool:
        """
        Schedule the agent-task processing coroutine on the FastAPI main event loop.

        Returns True if scheduling succeeded (the coroutine has been handed off to
        an event loop), False otherwise.
        """
        coro = self._initiate_agent_task_processing(detected_phrase)

        # Fast path: a loop is already running on the calling thread (rare for
        # the wake-word callback, but possible for direct/test invocations).
        try:
            loop = asyncio.get_running_loop()
            logger.debug("Event loop already running on caller thread - scheduling directly")
            task = loop.create_task(coro)
            task.add_done_callback(self._log_agent_task_processing_outcome)
            return True
        except RuntimeError:
            pass

        main_loop = self._resolve_main_event_loop()
        if main_loop is None:
            logger.error(
                "Cannot schedule agent_task processing - FastAPI main event loop not available"
            )
            coro.close()
            return False

        if main_loop.is_closed():
            logger.error(
                "Cannot schedule agent_task processing - FastAPI main event loop is closed"
            )
            coro.close()
            return False

        try:
            future = asyncio.run_coroutine_threadsafe(coro, main_loop)
            future.add_done_callback(self._log_agent_task_processing_outcome)
            logger.info(
                "✅ AgentTask processing scheduled on FastAPI main event loop via run_coroutine_threadsafe"
            )
            return True
        except Exception as schedule_error:
            logger.error(
                f"Failed to schedule agent_task processing on FastAPI main loop: {schedule_error}",
                exc_info=True,
            )
            try:
                coro.close()
            except Exception:
                pass
            return False

    def _resolve_main_event_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """Return the FastAPI startup event loop captured by WakeWordService, if any."""
        try:
            main_service = (
                getattr(self.orchestration_service, "main_service", None)
                if self.orchestration_service
                else None
            )
            loop = getattr(main_service, "main_event_loop", None) if main_service else None
            if loop is not None:
                return loop
        except Exception as resolve_error:
            logger.warning(f"Error resolving main event loop: {resolve_error}")
        return None

    def _log_agent_task_processing_outcome(self, fut) -> None:
        """
        Done-callback for the scheduled agent-task processing coroutine.

        _initiate_agent_task_processing() has its own try/finally that resets
        capture flags, so this callback exists purely to surface any unhandled
        exception that escapes the coroutine (defensive logging).
        """
        try:
            exc = fut.exception()
        except asyncio.CancelledError:
            logger.info("Agent_task processing was cancelled")
            return
        except Exception as cb_err:
            logger.warning(
                f"Could not retrieve agent_task processing outcome: {cb_err}"
            )
            return
        if exc is not None:
            logger.error(
                f"Unhandled exception in agent_task processing: {exc}",
                exc_info=exc,
            )

    async def _initiate_agent_task_processing(self, wake_phrase: str):
        """
        Initiate agent-task processing through the orchestration service.
        
        Args:
            wake_phrase: The detected wake phrase
        """
        try:
            if self.orchestration_service:
                # Sync state with orchestration service
                self.orchestration_service.set_agent_task_cancelled(self._agent_task_cancelled)
                # Delegate to orchestration service
                # Frontend will decide if this is a follow-up (same as hotkey flow)
                await self.orchestration_service._capture_and_process_agent_task(wake_phrase)
            else:
                logger.error("Cannot initiate agent-task processing - orchestration service not available")
        finally:
            self._is_capturing_agent_task = False
            self._agent_task_cancelled = False  # Clear cancellation flag
            
            # CRITICAL: Also clear the flag in the main service for hotkey-initiated agent tasks
            # This ensures the status endpoint shows the correct state for subsequent agent tasks
            if (self.orchestration_service and 
                hasattr(self.orchestration_service, 'main_service') and 
                self.orchestration_service.main_service):
                self.orchestration_service.main_service._is_capturing_agent_task = False
                self.orchestration_service.main_service._agent_task_cancelled = False

    def _pause_wake_word_detection(self):
        """
        Temporarily pause wake word detection during transcription processing.
        This prevents false wake word triggers from audio feedback or processing artifacts.
        """
        logger.info("🔇 [PAUSE_DEBUG] _pause_wake_word_detection() called in wake word manager")
        logger.info(f"Wake word detector object: {self.wake_word_detector}")
        logger.info(f"Has set_paused method: {hasattr(self.wake_word_detector, 'set_paused') if self.wake_word_detector else 'No detector'}")
        
        if self.wake_word_detector and hasattr(self.wake_word_detector, 'set_paused'):
            try:
                current_state = self.wake_word_detector.is_paused()
                logger.info(f"🔇 [PAUSE_DEBUG] Current wake word detector state: paused={current_state}")
                self.wake_word_detector.set_paused(True)
                final_state = self.wake_word_detector.is_paused()
                logger.info(f"✅ Wake word detection successfully paused - final state: paused={final_state}")
            except Exception as e:
                logger.error(f"❌ Could not pause wake word detector: {e}")
        else:
            logger.warning("⚠️ Wake word detector does not support pausing - skipping")

    def _resume_wake_word_detection(self):
        """
        Resume wake word detection after transcription processing completes.
        """
        logger.info("🔄 [RESUME_DEBUG] _resume_wake_word_detection() called in wake word manager")
        if self.wake_word_detector and hasattr(self.wake_word_detector, 'set_paused'):
            try:
                current_state = self.wake_word_detector.is_paused()
                logger.info(f"🔄 [RESUME_DEBUG] Current wake word detector state: paused={current_state}")
                self.wake_word_detector.set_paused(False)
                final_state = self.wake_word_detector.is_paused()
                logger.info(f"✅ Wake word detection successfully resumed - final state: paused={final_state}")
            except Exception as e:
                logger.error(f"❌ Could not resume wake word detector: {e}")
        else:
            logger.warning("⚠️ Wake word detector does not support pausing - skipping")

    def get_wake_word_callback(self):
        """
        Get the wake word detection callback for the detector.
        
        Returns:
            The callback function to be used by the wake word detector
        """
        return self._handle_wake_word_detected 