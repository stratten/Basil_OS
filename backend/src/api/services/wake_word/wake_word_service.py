import logging
import json
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List
import numpy as np # Added for audio processing
import threading
import concurrent.futures
import uuid
import time

# Use the exact same logger setup as basil_api.py
from ...core.logging.api_logger import setup_api_logger
from ...core.config.api_settings import settings

from .audio_capturer import WakeWordAudioCapturer
from .wake_word_detector import WakeWordDetector
from .wake_word_manager import VoiceListenerWakeWordManager
from .models import VoiceListenerSettings
from ..agent_processing.lifecycle.submission.agent_task_processing import AgentTaskOrchestrator  # AgentTaskProcessor removed 2025-11-17
from ..agent_processing.lifecycle.submission import AgentTaskSubmissionService
from ..transcription.backends.huggingface_service import HuggingFaceTranscriptionService # Added

from ...core.services.file_storage_service import StorageService # For path logic consistency
from ...dependencies import get_sqlite_knowledge_service  # Import shared database service

# Import component services
from .agent_task_capture import VoiceListenerAgentTaskCapture
from .agent_task_orchestration_service import VoiceListenerAgentTaskOrchestrationService

# Use the EXACT same logger as basil_api.py (creates api.api.main)
logger = setup_api_logger(
    "api.main",
    level=logging.DEBUG if settings.DEBUG else logging.INFO
)

# Define the settings filename
VOICE_LISTENER_SETTINGS_FILENAME = "voice_listener_settings.json"

class WakeWordService:
    def __init__(self, 
                 llm_service=None, 
                 basil_services: Optional[Dict[str, Any]] = None, 
                 transcription_service: Optional[HuggingFaceTranscriptionService] = None,
                 db_service=None):
        """
        Initialize the VoiceListenerService with audio capturing and wake word detection.
        """
        try:
            # EXPLICIT TEST: Verify logging works in packaged builds
            logger.info("🚀 VOICE_LISTENER_DEBUG: VoiceListenerService constructor started")
            logger.info("🚀 VOICE_LISTENER_DEBUG: This message should appear in packaged build logs")
            
            logger.info("Initializing VoiceListenerService...")
            
            # Store database service reference for chain context building
            if db_service is not None:
                self.db_service = db_service
            else:
                # Fallback: create new instance if not provided (for backward compatibility)
                from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
                self.db_service = SQLiteKnowledgeService()
                logger.info("Created fallback SQLiteKnowledgeService instance")
            
            # Store reference to the main event loop for thread-safe async operations
            try:
                self.main_event_loop = asyncio.get_running_loop()
                logger.info("🚀 VOICE_LISTENER_DEBUG: Captured reference to main event loop")
            except RuntimeError:
                self.main_event_loop = None
                logger.warning("🚀 VOICE_LISTENER_DEBUG: No event loop running during init")

            # Load settings
            logger.info("🚀 VOICE_LISTENER_DEBUG: Setting up settings file path...")
            self.settings_file_path = Path.home() / ".config" / "basil" / "voice_listener_settings.json"
            self.settings_file_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info("🚀 VOICE_LISTENER_DEBUG: Loading settings...")
            self.current_settings = self._load_settings()
            logger.info("🚀 VOICE_LISTENER_DEBUG: Settings loaded successfully")

            # Initialize state variables
            logger.info("🚀 VOICE_LISTENER_DEBUG: Initializing state variables...")
            # Use startup preference for initial state, not last session's state
            self._is_globally_enabled_by_user = self._get_startup_listener_preference()
            
            # Sync the session settings with the startup preference
            # This ensures the settings reflect the startup state, not a stale previous session
            if self.current_settings.voice_listener_enabled != self._is_globally_enabled_by_user:
                self.current_settings.voice_listener_enabled = self._is_globally_enabled_by_user
                self._save_settings(self.current_settings)
                logger.info(f"Synced session voice listener state to startup preference: {self._is_globally_enabled_by_user}")
            
            self._is_actively_listening = False
            self._is_capturing_agent_task = False
            self._agent_task_cancelled = False
            self._agent_task_capture_task: Optional[asyncio.Task] = None
            self._active_transcription_task: Optional[asyncio.Task] = None
            self._last_wake_word_time = 0.0
            self._wake_word_debounce_seconds = 3.0
            self._same_utterance_debounce_seconds = 0.01
            self._current_screenshot_data = None
            self._wake_word_lock = threading.Lock()
            logger.info("🚀 VOICE_LISTENER_DEBUG: State variables initialized")

            # Health monitoring setup
            logger.info("🚀 VOICE_LISTENER_DEBUG: Setting up health monitoring...")
            self._last_audio_frame_time = 0.0
            self._last_heartbeat_time = time.time()
            self._health_check_interval = 15.0
            self._max_failed_health_checks = 3
            self._consecutive_health_failures = 0
            self._health_monitor_task: Optional[asyncio.Task] = None
            self._restart_in_progress = False
            logger.info("🚀 VOICE_LISTENER_DEBUG: Health monitoring setup complete")

            # Initialize component placeholders
            logger.info("🚀 VOICE_LISTENER_DEBUG: Initializing component placeholders...")
            self.wake_word_detector = None
            self.audio_capturer = None
            self.llm_service = llm_service
            logger.info("🚀 VOICE_LISTENER_DEBUG: Component placeholders initialized")

            # Initialize agent-task processing pipeline
            logger.info("🚀 VOICE_LISTENER_DEBUG: Setting up agent-task processing...")
            shared_db_service = get_sqlite_knowledge_service()
            self.agent_task_orchestrator = AgentTaskOrchestrator(
                llm_service=llm_service,
                websocket_manager=self,
                basil_services=basil_services,
                db_service=shared_db_service
            )
            logger.info("🚀 VOICE_LISTENER_DEBUG: Agent-task processing setup complete")

            # Initialize transcription service
            logger.info("🚀 VOICE_LISTENER_DEBUG: Setting up transcription service...")
            self.transcription_service = transcription_service or HuggingFaceTranscriptionService()
            logger.info("🚀 VOICE_LISTENER_DEBUG: Transcription service setup complete")

            # Initialize component services (will be set up in _initialize_components)
            logger.info("🚀 VOICE_LISTENER_DEBUG: Initializing component service placeholders...")
            self.agent_task_capture_service = None
            self.agent_task_orchestration_service = None
            self.agent_task_submission_service = None
            self.wake_word_manager = None
            logger.info("🚀 VOICE_LISTENER_DEBUG: Component service placeholders initialized")

            # Pre-load transcription model if needed (skip for API models)
            logger.info("🚀 VOICE_LISTENER_DEBUG: Checking transcription model...")
            if self.transcription_service and not self.transcription_service.is_model_loaded():
                if self._is_api_transcription_selected():
                    logger.info("🚀 VOICE_LISTENER_DEBUG: API transcription model selected, skipping local model pre-load")
                elif self._is_parakeet_selected():
                    logger.info(
                        "🚀 VOICE_LISTENER_DEBUG: Parakeet transcription model selected; "
                        "skipping HuggingFace pre-load (Parakeet service is built lazily)"
                    )
                else:
                    logger.info("🚀 VOICE_LISTENER_DEBUG: Pre-loading transcription model...")
                    try:
                        self.transcription_service.load_model()
                        logger.info("🚀 VOICE_LISTENER_DEBUG: Transcription model loaded successfully")
                    except Exception as e:
                        logger.error(f"🚨 VOICE_LISTENER_DEBUG: Transcription model load failed: {e}")

            # Initialize components with detailed logging
            logger.info("🚀 VOICE_LISTENER_DEBUG: About to call _initialize_components()...")
            self._initialize_components()
            logger.info("🚀 VOICE_LISTENER_DEBUG: _initialize_components() completed successfully")

            # Start listening if enabled
            logger.info("🚀 VOICE_LISTENER_DEBUG: Checking if should start listening...")
            if self._is_globally_enabled_by_user:
                logger.info("🚀 VOICE_LISTENER_DEBUG: Voice listener enabled - starting audio capture...")
                self.start_listening()
            else:
                logger.info("🚀 VOICE_LISTENER_DEBUG: Voice listener disabled - not starting audio capture")
            
            logger.info("🚀 VOICE_LISTENER_DEBUG: Constructor completed successfully!")
            
        except Exception as constructor_error:
            logger.error(f"🚨 VOICE_LISTENER_DEBUG: CONSTRUCTOR FAILED: {constructor_error}")
            logger.error(f"🚨 VOICE_LISTENER_DEBUG: Constructor error type: {type(constructor_error)}")
            import traceback
            logger.error(f"🚨 VOICE_LISTENER_DEBUG: Full traceback: {traceback.format_exc()}")
            raise

    def _load_settings(self) -> VoiceListenerSettings:
        """Loads voice listener settings from the JSON file."""
        if self.settings_file_path.exists():
            try:
                with open(self.settings_file_path, 'r') as f:
                    data = json.load(f)
                return VoiceListenerSettings(**data)
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Error loading or parsing {self.settings_file_path}: {e}. Using default settings.")
        else:
            logger.info(f"{self.settings_file_path} not found. Creating with default settings.")
        
        default_settings = VoiceListenerSettings()
        self._save_settings(default_settings) # Save defaults if file missing or corrupt
        return default_settings

    def _save_settings(self, settings: VoiceListenerSettings):
        """Saves voice listener settings to the JSON file."""
        try:
            with open(self.settings_file_path, 'w') as f:
                json.dump(settings.model_dump(), f, indent=4)
            logger.info(f"Voice listener settings saved to {self.settings_file_path}")
        except IOError as e:
            logger.error(f"Error saving settings to {self.settings_file_path}: {e}")

    def _initialize_components(self):
        """Initializes the detector and capturer components."""
        # First initialize wake word detector without callback
        self.wake_word_detector = WakeWordDetector(
            sensitivity=0.75,  # Increased from default 0.5 to reduce false positives from background noise
            on_wake_word_detected_callback=None,  # Will be set after wake word manager is created
            heartbeat_callback=self.update_wake_word_heartbeat
        )
        self.audio_capturer = WakeWordAudioCapturer(wake_word_detector=self.wake_word_detector)
        
        # Initialize agent-task capture service now that audio_capturer is ready
        self.agent_task_capture_service = VoiceListenerAgentTaskCapture(
            audio_capturer=self.audio_capturer,
            transcription_service=self.transcription_service
        )
        
        # Initialize agent-task orchestration service now that capture service is ready
        self.agent_task_orchestration_service = VoiceListenerAgentTaskOrchestrationService(
            agent_task_capture_service=self.agent_task_capture_service,
            agent_task_orchestrator=self.agent_task_orchestrator,
            main_service=self  # Pass reference to self for delegation
        )
        
        # Direct agent-task submission is owned by agent_processing; wake-word
        # service keeps audio lifecycle only and supplies pre-captured context.
        self.agent_task_submission_service = AgentTaskSubmissionService(
            agent_task_orchestrator=self.agent_task_orchestrator,
            db_service=self.db_service,
            wake_word_service=self,
        )
        
        # Initialize wake word manager now that all other services are ready.
        # The manager reaches the FastAPI main event loop via
        # orchestration_service.main_service.main_event_loop and schedules
        # agent-task processing with asyncio.run_coroutine_threadsafe(...),
        # so no separate event-loop callback registration is required here.
        self.wake_word_manager = VoiceListenerWakeWordManager(
            wake_word_detector=self.wake_word_detector,
            transcription_service=self.transcription_service,
            orchestration_service=self.agent_task_orchestration_service
        )

        # Set the wake word callback on the detector
        if self.wake_word_detector:
            self.wake_word_detector.on_wake_word_detected_callback = self.wake_word_manager.get_wake_word_callback()
        

        
        logger.info("VoiceListenerService components initialized.")

    def _get_startup_listener_preference(self) -> bool:
        """
        Gets the user's startup preference for the voice listener.
        This determines whether the listener should be enabled when the app starts.
        """
        try:
            from ...core.models.preferences import Preferences
            preferences = Preferences.load()
            startup_enabled = preferences.behavior.enable_voice_listener_at_startup
            logger.info(f"Voice listener startup preference: {startup_enabled}")
            return startup_enabled
        except Exception as e:
            logger.error(f"Error loading startup preference, defaulting to False: {e}")
            return False

    def _get_voice_listener_enabled_setting(self) -> bool:
        """ Fetches the user's preference for enabling the voice listener from current settings object."""
        return self.current_settings.voice_listener_enabled

    def set_voice_listener_enabled(self, enabled: bool):
        """
        Sets the voice listener enabled state and saves it to settings.
        This will also attempt to start or stop the listener accordingly.
        """
        if self.current_settings.voice_listener_enabled != enabled:
            self.current_settings.voice_listener_enabled = enabled
            self._save_settings(self.current_settings)
            logger.info(f"Voice listener enabled state set to: {enabled}")
            self.update_listener_state_from_settings() # Trigger start/stop logic
        else:
            logger.info(f"Voice listener enabled state is already {enabled}. No change.")

    async def _capture_and_process_agent_task(self, wake_phrase: str):
        """
        Capture agent_task after wake word and process it through the agent-task pipeline.
        
        Args:
            wake_phrase: The detected wake phrase
        """
        try:
            self._is_capturing_agent_task = True
            self._agent_task_cancelled = False  # Reset cancellation flag at start
            
            # Sync state with wake word manager
            if self.wake_word_manager:
                self.wake_word_manager.set_agent_task_state(self._is_capturing_agent_task, self._agent_task_cancelled)
            
            # Sync cancellation state and get screenshot data from orchestration service
            self.agent_task_orchestration_service.set_agent_task_cancelled(self._agent_task_cancelled)
            # Get the screenshot data that was captured during wake word detection
            self._current_screenshot_data = self.agent_task_orchestration_service._current_screenshot_data
            
            # Delegate to the orchestration service
            await self.agent_task_orchestration_service._capture_and_process_agent_task(wake_phrase)
            
        finally:
            # In hotkey client-owned capture mode, keep status as capturing until the client stops it.
            if getattr(self, "_hotkey_client_owned_capture", False):
                logger.info("🎤 [VOICE_CAPTURE_DEBUG] Hotkey client-owned capture active - keeping is_capturing_agent_task=True until client stop")
                # Ensure the status endpoint reflects active capture for the second hotkey press
                self._is_capturing_agent_task = True
                self._agent_task_cancelled = False
            else:
                self._is_capturing_agent_task = False
                self._agent_task_cancelled = False  # Clear cancellation flag
                
                # Sync final state with wake word manager
                if self.wake_word_manager:
                    self.wake_word_manager.set_agent_task_state(self._is_capturing_agent_task, self._agent_task_cancelled)

    async def _capture_agent_task(self) -> Optional[str]:
        """
        Capture the agent_task that follows the wake word using intelligent word-based termination.
        
        IMPORTANT: Uses streaming processor for capture termination detection only.
        Final agent-task processing still uses complete recorded audio via batch transcription.
        
        Returns:
            Transcribed agent_task or None if capture failed
        """
        # Sync cancellation state with the agent-task capture service
        self.agent_task_capture_service.set_agent_task_cancelled(self._agent_task_cancelled)
        
        # Delegate to the agent-task capture service
        return await self.agent_task_capture_service._capture_agent_task()

    async def _capture_agent_task_fallback(self) -> Optional[str]:
        """
        Fallback agent_task capture using the original timer-based method.
        Used when streaming processor is not available or fails.
        
        Returns:
            Transcribed agent_task or None if capture failed
        """
        # Sync cancellation state with the agent-task capture service
        self.agent_task_capture_service.set_agent_task_cancelled(self._agent_task_cancelled)
        
        # Delegate to the agent-task capture service
        return await self.agent_task_capture_service._capture_agent_task_fallback()

    async def broadcast(self, message_data: Dict[str, Any]):
        """
        Broadcast a message to all connected WebSocket clients.
        Delegates to the orchestration service for actual broadcasting.
        
        Args:
            message_data: Dictionary containing the message to broadcast
        """
        if self.agent_task_orchestration_service:
            await self.agent_task_orchestration_service.broadcast(message_data)
        else:
            logger.error("Cannot broadcast message - orchestration service not available")

    def _pause_wake_word_detection(self):
        """
        Temporarily pause wake word detection during transcription processing.
        Delegates to the wake word manager.
        """
        if self.wake_word_manager:
            self.wake_word_manager._pause_wake_word_detection()
        else:
            logger.error("Cannot pause wake word detection - wake word manager not available")

    def _resume_wake_word_detection(self):
        """
        Resume wake word detection after transcription processing completes.
        Delegates to the wake word manager.
        """
        logger.info("🔄 [RESUME_DEBUG] _resume_wake_word_detection() called in main service")
        if self.wake_word_manager:
            logger.info("🔄 [RESUME_DEBUG] Delegating to wake word manager _resume_wake_word_detection()")
            self.wake_word_manager._resume_wake_word_detection()
        else:
            logger.error("Cannot resume wake word detection - wake word manager not available")

    def _check_can_resume_wake_word_detection(self) -> bool:
        """
        Check if it's safe to resume wake word detection by querying widget state.
        Returns True if wake word detection can be safely resumed, False if an agent task is still processing.
        """
        try:
            if self.agent_task_orchestration_service and hasattr(self.agent_task_orchestration_service, 'query_widget_state_sync'):
                widget_state = self.agent_task_orchestration_service.query_widget_state_sync(timeout_seconds=0.2)
                is_processing = widget_state.get('is_processing', False)
                
                if is_processing:
                    logger.info("🔄 [LISTENER_START] Widget is processing an agent task - cannot resume wake word detection yet")
                    return False
                else:
                    logger.info("🔄 [LISTENER_START] Widget not processing - safe to resume wake word detection")
                    return True
            else:
                # No orchestration service - assume safe to resume
                logger.debug("No orchestration service for widget state check - assuming safe to resume")
                return True
        except Exception as e:
            logger.error(f"Error checking widget state for wake word resume: {e}")
            # On error, assume safe to resume
            return True

    def update_listener_state_from_settings(self):
        """
        Checks the user preference from the loaded settings and starts or stops the listener accordingly.
        """
        new_setting_value = self.current_settings.voice_listener_enabled
        if new_setting_value != self._is_globally_enabled_by_user:
            logger.info(f"Internal global enabled state updating from {self._is_globally_enabled_by_user} to {new_setting_value}")
            self._is_globally_enabled_by_user = new_setting_value
        
        # Now reconcile active listening state with the (potentially new) global enabled state
        if self._is_globally_enabled_by_user:
            if not self._is_actively_listening:
                self.start_listening()
            # else: already listening and enabled, no change needed
        else: # Not globally enabled
            if self._is_actively_listening:
                self.stop_listening()
            # else: already not listening and not enabled, no change needed

    def start_listening(self):
        """Starts the audio capturer if globally enabled by user preference."""
        if not self._is_globally_enabled_by_user:
            logger.debug("Voice listener is not globally enabled by user. Cannot start listening.")
            return

        if self._is_actively_listening:
            logger.debug("Voice listener is already actively listening.")
            return
        
        if self._is_capturing_agent_task:
            logger.debug("Currently capturing agent task. Will not start wake word listening.")
            return
        
        if not self.audio_capturer:
            logger.error("AudioCapturer not initialized. Cannot start listening.")
            return
        if not self.wake_word_detector or not self.wake_word_detector.oww_model:
             logger.error("WakeWordDetector not initialized or model not loaded. Cannot start listening.")
             return

        # Start transcription model loading in parallel (non-blocking)
        # This allows audio capture to start immediately while model loads in background
        # Skip pre-load entirely when an API or Parakeet transcription model is selected
        if self._is_api_transcription_selected():
            logger.info("VoiceListenerService: API transcription model selected, skipping local model preload")
        elif self._is_parakeet_selected():
            logger.info(
                "VoiceListenerService: Parakeet transcription model selected; "
                "skipping HuggingFace preload (Parakeet service is built lazily by the dispatch helpers)"
            )
        elif self.transcription_service and not self.transcription_service.is_model_loaded():
            logger.info("VoiceListenerService: Starting parallel transcription model preload...")
            
            def preload_transcription_model():
                try:
                    logger.info("Background thread: Loading transcription model...")
                    self.transcription_service.load_model()
                    logger.info("✅ Background thread: Transcription model loaded successfully")
                except Exception as e:
                    logger.error(f"❌ Background thread: Error loading transcription model: {e}")
            
            preload_thread = threading.Thread(target=preload_transcription_model, daemon=True)
            preload_thread.start()
            logger.info("VoiceListenerService: Transcription model loading in background - audio capture will start immediately")
        else:
            logger.info("VoiceListenerService: Transcription model already loaded")

        try:
            logger.info("VoiceListenerService: Starting audio capture for wake word detection...")
            self.audio_capturer.start()
            self._is_actively_listening = True
            
            # Check if it's safe to resume wake word detection
            # Don't resume if an agent task is still processing (widget visible and processing)
            can_resume_wake_word = self._check_can_resume_wake_word_detection()
            if can_resume_wake_word:
                logger.info("VoiceListenerService: Widget state allows wake word detection - resuming...")
                self._resume_wake_word_detection()
            else:
                logger.info("VoiceListenerService: Agent task still processing - deferring wake word resume until completion")
            
            # Initialize health tracking
            current_time = time.time()
            self._last_audio_frame_time = current_time
            self._last_heartbeat_time = current_time
            
            # Start health monitor if we have an event loop (use current running loop, not stored reference)
            if not self._health_monitor_task or self._health_monitor_task.done():
                try:
                    current_loop = asyncio.get_running_loop()
                    self._health_monitor_task = current_loop.create_task(self._health_monitor())
                    logger.info("VoiceListenerService: Started health monitor task on current event loop")
                except RuntimeError:
                    # No event loop running - this is expected in some contexts
                    logger.warning("VoiceListenerService: Cannot start health monitor - no running event loop")
                    self._health_monitor_task = None
                
            logger.info("VoiceListenerService: Audio capture started successfully for wake word.")
        except Exception as e:
            logger.error(f"VoiceListenerService: Failed to start audio capture: {e}", exc_info=True)
            self._is_actively_listening = False

    def stop_listening(self):
        """Stops the audio capturer."""
        if not self._is_actively_listening:
            # logger.debug("Voice listener is not actively listening.")
            return

        if not self.audio_capturer:
            logger.error("AudioCapturer not initialized. Cannot stop listening.")
            return

        try:
            logger.info("VoiceListenerService: Stopping audio capture...")
            
            # Clear all buffers before stopping to prevent phantom detections on restart
            if hasattr(self.audio_capturer, 'clear_all_buffers'):
                self.audio_capturer.clear_all_buffers()
            
            # Stop health monitor
            if self._health_monitor_task and not self._health_monitor_task.done():
                self._health_monitor_task.cancel()
                self._health_monitor_task = None
            
            # IMMEDIATE state change - don't wait for thread cleanup
            self._is_actively_listening = False
            logger.info("VoiceListenerService: Voice listener disabled (thread cleanup in background)")
            
            # Signal the audio capturer to stop (non-blocking)
            if hasattr(self.audio_capturer, '_is_capturing'):
                self.audio_capturer._is_capturing = False
                
            # Clean up in background thread - DON'T block the API call
            def cleanup_audio_capturer():
                try:
                    self.audio_capturer.stop()
                    logger.info("VoiceListenerService: Audio capturer cleanup completed")
                except Exception as e:
                    logger.error(f"VoiceListenerService: Error during background cleanup: {e}")
            
            import threading
            cleanup_thread = threading.Thread(target=cleanup_audio_capturer, daemon=True)
            cleanup_thread.start()
            
        except Exception as e:
            logger.error(f"VoiceListenerService: Error stopping audio capture: {e}", exc_info=True)
            self._is_actively_listening = False

    @staticmethod
    def _is_api_transcription_selected() -> bool:
        """Check if the user has an API transcription model selected and enabled."""
        try:
            from api.core.models.preferences import Preferences
            from api.core.models.models_registry import get_cloud_transcription_models
            prefs = Preferences.load()
            return (
                prefs.models.use_api_transcription_models
                and prefs.models.transcription_model in get_cloud_transcription_models()
            )
        except Exception:
            return False

    @staticmethod
    def _is_parakeet_selected() -> bool:
        """Check if the user's selected transcription model is a Parakeet ONNX model.

        Used to short-circuit the HuggingFace pre-load path on the voice
        listener so we do not pull a Whisper bundle into memory when the
        user has switched to Parakeet. The actual Parakeet service is
        constructed lazily by ``resolve_transcription_service`` /
        ``get_transcription_service`` on the first transcription request.
        """
        try:
            from api.core.models.preferences import Preferences
            from api.core.models.models_registry import get_parakeet_transcription_models
            prefs = Preferences.load()
            selected = prefs.models.transcription_model
            for model_id, cfg in get_parakeet_transcription_models().items():
                if cfg.get("display_name") == selected or model_id == selected:
                    return True
            return False
        except Exception:
            return False

    def get_status(self) -> dict:
        """
        Returns the current status of the voice listener service.
        """
        
        # In hotkey client-owned capture, report capturing as active until explicit stop
        capturing_flag = self._is_capturing_agent_task or getattr(self, "_hotkey_client_owned_capture", False)

        return {
            "voice_listener_enabled": self.current_settings.voice_listener_enabled,
            "is_actively_listening": self._is_actively_listening,
            "is_capturing_agent_task": capturing_flag,
            "detector_model_loaded": self.wake_word_detector.oww_model is not None if self.wake_word_detector else False,
            "detector_models": list(self.wake_word_detector.active_models.keys()) if self.wake_word_detector and self.wake_word_detector.oww_model else [],
            "agent_task_processor_ready": self.agent_task_orchestrator is not None,
            "transcription_service_ready": self.transcription_service is not None and self.transcription_service.is_model_loaded(),
            "health_monitor_active": self._health_monitor_task is not None and not self._health_monitor_task.done(),
            "consecutive_health_failures": self._consecutive_health_failures,
            "max_failed_health_checks": self._max_failed_health_checks,
            "restart_in_progress": self._restart_in_progress,
            "health_check_interval": self._health_check_interval
        }

    async def _process_agent_task_direct_impl(self, agent_task: str, clarification_agent_task: str = None, agent_task_id: str = None, root_task_id: str = None, previous_task_id: str = None, reference_paths: Optional[List[str]] = None, model_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Process agent_task directly without wake word detection.
        Used for API endpoints and direct agent-task processing.
        
        Uses synchronous processing like AssistantSession suggestions (not event-driven orchestrator).
        
        Args:
            agent_task: The transcribed agent_task text
            clarification_agent_task: Optional clarification agent task
            agent_task_id: Optional AgentTask ID (will be generated if not provided)
            root_task_id: Explicit root task ID for follow-up chains
            previous_task_id: Immediate predecessor task ID for follow-up chains
            reference_paths: Optional list of file/folder paths for context (from drag-and-drop)
        """
        logger.info(f"Processing agent_task directly: '{agent_task}'")
        
        try:
            # Short-term cancellation gate: drop any new processing immediately after cancel
            try:
                import time as _time
                last_cancel = getattr(self, "_last_cancel_timestamp", 0.0)
                if last_cancel and (_time.time() - last_cancel) < 5.0:
                    logger.info("🚫 Direct processing suppressed due to recent cancellation window (<5s)")
                    return {
                        "success": False,
                        "operation": "cancelled",
                        "confidence": 0.0,
                        "reasoning": "User cancelled the agent_task; ignoring late-arriving audio.",
                        "message": "Task was cancelled",
                    }
            except Exception:
                pass
            
            # Build chain context if this is a follow-up agent task
            chain_context = None
            chain_root_id = root_task_id
            if chain_root_id:
                logger.info(f"🔗 Building chain context for follow-up (root: {chain_root_id}, previous: {previous_task_id})")
                chain_context = await self._build_chain_context(chain_root_id, previous_task_id=previous_task_id)
                if chain_context:
                    logger.info(f"🔗 Chain context built: sequence={chain_context['chain_sequence_number']}, "
                               f"artifacts_count={len(chain_context.get('accumulated_artifacts', {}))}")
                else:
                    logger.warning(f"⚠️ Root task {chain_root_id} not found, treating as standalone task")
            
            # Handle clarifications vs new agent tasks correctly
            if clarification_agent_task and agent_task_id:
                # This is a clarification for an existing agent task
                logger.info(f"Processing clarification for agent task {agent_task_id}")
                result = await self.agent_task_orchestrator.add_clarification(
                    agent_task_id=agent_task_id,
                    clarification_text=agent_task
                )
            else:
                # Both tracks (wake word and hotkey) should use identical processing
                # Use the orchestrator like wake word flow does, but return complete results
                logger.info("Processing agent task via orchestrator (same as wake word flow)")
                
                # Generate agent task ID if not provided
                if not agent_task_id:
                    agent_task_id = str(uuid.uuid4())
                
                # Use purely event-driven processing for all agent tasks
                # Database INSERT will trigger event system to handle routing and execution
                result = await self.agent_task_orchestrator.process_agent_task(
                    agent_task=agent_task,
                    pre_captured_screenshot=self._current_screenshot_data,
                    agent_task_id=agent_task_id,
                    synchronous=False,  # All agent tasks now use event-driven processing
                    chain_context=chain_context,  # Pass chain context if this is a follow-up
                    reference_paths=reference_paths,  # Pass file/folder paths for agent context
                    model_id=model_id
                )
                logger.info(f"Orchestrator processing completed: status={result.get('status', 'unknown')}")
                
                # Event-driven processing returns after database storage - event system takes over
            
            return result
        except Exception as e:
            logger.error(f"Error in process_agent_task_direct: {e}", exc_info=True)
            return {
                "success": False,
                "operation": "error", 
                "confidence": 0.0,
                "reasoning": f"Error during agent-task processing: {str(e)}",
                "message": "AgentTask processing failed",
                "error": str(e)
            }
    
    async def _build_chain_context(self, root_task_id: str, previous_task_id: str = None) -> Optional[Dict[str, Any]]:
        """
        Build chain context for a follow-up turn by retrieving root task and chain history.
        
        Args:
            root_task_id: ID of the root task in the chain
            previous_task_id: Optional immediate predecessor task ID
            
        Returns:
            Dict with chain_sequence_number, session_type, accumulated_artifacts, or None if parent not found
        """
        try:
            root_task = await self.db_service.get_agent_task(root_task_id)
            if root_task:
                root_task_id = root_task.root_task_id or root_task.id

            # Retrieve the entire agent task chain (root + all existing follow-ups)
            chain_agentTasks = await self.db_service.get_agent_task_chain(root_task_id)
            
            if not chain_agentTasks:
                logger.warning(f"Root task {root_task_id} not found")
                return None
            
            # Calculate sequence number: count of agent tasks in chain (parent is 0, so next is len(chain))
            chain_sequence_number = len(chain_agentTasks)
            logger.info(f"🔗 Chain has {len(chain_agentTasks)} existing agent tasks, new sequence number: {chain_sequence_number}")
            
            # Build accumulated artifacts from entire chain
            accumulated_artifacts = {
                'chain_agentTasks': []
            }
            
            # Add each agent task turn in the chain to the accumulated artifacts
            for agent_task_record in chain_agentTasks:
                agent_task_artifact = {
                    'id': agent_task_record.id,
                    'root_task_id': agent_task_record.root_task_id or agent_task_record.id,
                    'previous_task_id': agent_task_record.previous_task_id,
                    'sequence': agent_task_record.chain_sequence_number,
                    'text': agent_task_record.transcribed_prompt,
                    'timestamp': agent_task_record.timestamp.isoformat(),
                    'status': agent_task_record.status
                }
                
                # Include results if available
                if agent_task_record.result_data:
                    agent_task_artifact['result'] = agent_task_record.result_data
                
                # Include operation info if available
                if agent_task_record.operation_parameters:
                    agent_task_artifact['operation'] = agent_task_record.operation_parameters
                
                accumulated_artifacts['chain_agentTasks'].append(agent_task_artifact)
            
            # Get the most recent agent task's accumulated artifacts (might have been built up)
            latest_agent_task = chain_agentTasks[-1]
            if latest_agent_task.accumulated_artifacts:
                # Merge existing accumulated artifacts (but don't overwrite chain_agentTasks)
                for key, value in latest_agent_task.accumulated_artifacts.items():
                    if key != 'chain_agentTasks':
                        accumulated_artifacts[key] = value
            
            logger.info(f"🔗 Built accumulated artifacts with {len(accumulated_artifacts['chain_agentTasks'])} agent tasks")

            resolved_previous_task_id = previous_task_id or latest_agent_task.id
            
            return {
                'root_task_id': root_task_id,
                'previous_task_id': resolved_previous_task_id,
                'chain_sequence_number': chain_sequence_number,
                'session_type': 'chain',  # Manual follow-up chain
                'accumulated_artifacts': accumulated_artifacts
            }
            
        except Exception as e:
            logger.error(f"Error building chain context: {e}", exc_info=True)
            return None

    async def process_agent_task_direct(self, agent_task: str, clarification_agent_task: str = None, agent_task_id: str = None, root_task_id: str = None, previous_task_id: str = None, reference_paths: Optional[List[str]] = None, model_id: Optional[str] = None) -> Dict[str, Any]:
        """Capability-named wrapper for delegated task processing."""
        if agent_task is None:
            raise ValueError("process_agent_task_direct requires agent_task")

        return await self._process_agent_task_direct_impl(
            agent_task,
            clarification_agent_task=clarification_agent_task,
            agent_task_id=agent_task_id,
            root_task_id=root_task_id,
            previous_task_id=previous_task_id,
            reference_paths=reference_paths,
            model_id=model_id,
        )
    
    async def add_clarification(self, agent_task_id: str, clarification_text: str) -> Dict[str, Any]:
        """
        Add clarification to an existing agent_task.
        
        Args:
            agent_task_id: The AgentTask ID to add clarification to
            clarification_text: The clarification text from the user
            
        Returns:
            Dictionary containing the result
        """
        logger.info(f"🎯 Adding clarification to agent task {agent_task_id}: '{clarification_text}'")
        
        try:
            # Delegate to the orchestrator's add_clarification method
            result = await self.agent_task_orchestrator.add_clarification(
                agent_task_id=agent_task_id,
                clarification_text=clarification_text
            )
            return result
            
        except Exception as e:
            logger.error(f"Error adding clarification: {e}", exc_info=True)
            return {
                "success": False,
                "agent_task_id": agent_task_id,
                "error": str(e),
                "message": "Failed to process clarification. Please try again."
            }
    
    async def cancel_current_agent_task(self, agent_task_id: str = None):
        """
        AGGRESSIVELY cancel agent task operations by directly identifying and terminating
        every specific operation that could be running as part of the agent task process.
        
        Args:
            agent_task_id: Optional specific AgentTask ID to cancel. If provided, only cancels
                       that agent task's processing via the orchestrator. If None, cancels all.
        
        This doesn't rely on passive flag checking - it actively hunts down and kills everything.
        """
        try:
            # If a specific agent_task_id is provided, cancel just that agent-task thread via orchestrator.
            # Intentionally avoid any global teardown path here.
            if agent_task_id:
                agent_task_id = agent_task_id.strip()
                if not agent_task_id:
                    logger.warning("🚫 [DIRECT_CANCEL] Received empty agent_task_id for scoped cancel")
                    return False
                logger.info(f"🚫 [DIRECT_CANCEL] Cancelling specific agent-task thread: {agent_task_id}")
                if self.agent_task_orchestrator and hasattr(self.agent_task_orchestrator, 'cancel_agent_task'):
                    return await self.agent_task_orchestrator.cancel_agent_task(agent_task_id)
                else:
                    logger.warning("🚫 [DIRECT_CANCEL] Orchestrator not available for specific cancel")
                    return False
            
            logger.info("🚫 [DIRECT_CANCEL] Starting AGGRESSIVE agent_task cancellation...")
            
            # STEP 1: Set flag to prevent new operations (but don't rely on it)
            try:
                import time as _time
                self._last_cancel_timestamp = _time.time()
            except Exception:
                self._last_cancel_timestamp = 0.0
            self._agent_task_cancelled = True
            
            # STEP 2: FORCE-STOP audio capturer immediately - don't check state, just force it
            logger.info("🚫 [DIRECT_CANCEL] FORCE-STOPPING audio capturer...")
            
            # Also sync cancellation with all services
            if self.wake_word_manager:
                self.wake_word_manager.set_agent_task_state(self._is_capturing_agent_task, True)
                logger.info("🚫 [DIRECT_CANCEL] Wake word manager cancellation flag set")
            
            if self.agent_task_capture_service:
                self.agent_task_capture_service.set_agent_task_cancelled(True)
                logger.info("🚫 [DIRECT_CANCEL] Agent-task capture service cancellation flag set")
            
            if self.agent_task_orchestration_service:
                self.agent_task_orchestration_service.set_agent_task_cancelled(True)
                logger.info("🚫 [DIRECT_CANCEL] Agent-task orchestration service cancellation flag set")
            
            if self.audio_capturer:
                current_mode = self.audio_capturer.get_current_capture_mode() 
                logger.info(f"🚫 [DIRECT_CANCEL] Audio capturer current mode: {current_mode}")
                
                # FORCE reset to WAKE_WORD mode regardless of current state
                try:
                    if hasattr(self.audio_capturer, '_agent_task_capture_lock'):
                        with self.audio_capturer._agent_task_capture_lock:
                            logger.info("🚫 [DIRECT_CANCEL] Forcing audio capturer state reset...")
                            self.audio_capturer._capture_mode = "WAKE_WORD"
                            self.audio_capturer._agent_task_audio_buffer.clear()
                            if hasattr(self.audio_capturer, '_agent_task_capture_start_time'):
                                self.audio_capturer._agent_task_capture_start_time = None
                            logger.info("🚫 [DIRECT_CANCEL] Audio capturer FORCE-RESET to WAKE_WORD mode")
                    
                    # Also try the normal stop method as backup
                    if current_mode == "AGENT_TASK_CAPTURE":
                        try:
                            self.audio_capturer.stop_agent_task_capture_and_get_audio()
                            logger.info("🚫 [DIRECT_CANCEL] Normal audio stop also succeeded")
                        except Exception as e:
                            logger.warning(f"🚫 [DIRECT_CANCEL] Normal audio stop failed (expected after force reset): {e}")
                            
                except Exception as e:
                    logger.error(f"🚫 [DIRECT_CANCEL] CRITICAL: Audio capturer force reset failed: {e}", exc_info=True)
            else:
                logger.warning("🚫 [DIRECT_CANCEL] Audio capturer is None")
                
            # STEP 3: TERMINATE all streaming sessions immediately 
            logger.info("🚫 [DIRECT_CANCEL] TERMINATING all streaming sessions...")
            try:
                from api.services.agent_task_streaming import cleanup_all_streaming_sessions
                cleanup_all_streaming_sessions()
                logger.info("🚫 [DIRECT_CANCEL] All streaming sessions terminated")
            except Exception as e:
                logger.error(f"🚫 [DIRECT_CANCEL] Error terminating streaming sessions: {e}")
            
            # STEP 4: CANCEL all asyncio tasks related to agent task processing
            logger.info("🚫 [DIRECT_CANCEL] CANCELLING all agent_task tasks...")
            
            # Cancel main agent-task capture task
            if self._agent_task_capture_task and not self._agent_task_capture_task.done():
                logger.info("🚫 [DIRECT_CANCEL] Cancelling main agent-task capture task")
                self._agent_task_capture_task.cancel()
                try:
                    await asyncio.wait_for(self._agent_task_capture_task, timeout=0.3)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    logger.info("🚫 [DIRECT_CANCEL] Main agent-task task cancelled")
            
            # Cancel transcription task
            if hasattr(self, '_active_transcription_task') and self._active_transcription_task:
                if not self._active_transcription_task.done():
                    logger.info("🚫 [DIRECT_CANCEL] Cancelling transcription task")
                    self._active_transcription_task.cancel()
                    try:
                        await asyncio.wait_for(self._active_transcription_task, timeout=0.2)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        logger.info("🚫 [DIRECT_CANCEL] Transcription task cancelled")
                self._active_transcription_task = None
            
            # STEP 5: Find and cancel ANY running tasks that might be part of agent task processing
            logger.info("🚫 [DIRECT_CANCEL] Scanning for any other agent_task related tasks...")
            current_task = asyncio.current_task()
            all_tasks = asyncio.all_tasks()
            
            agent_task_tasks = []
            for task in all_tasks:
                if task != current_task and not task.done():
                    # Look for tasks that might be related to agent task processing
                    if hasattr(task, '_context') or 'voice' in str(task) or 'agent_task' in str(task) or 'capture' in str(task):
                        agent_task_tasks.append(task)
            
            if agent_task_tasks:
                logger.info(f"🚫 [DIRECT_CANCEL] Found {len(agent_task_tasks)} potentially related tasks, cancelling...")
                for task in agent_task_tasks:
                    try:
                        task.cancel()
                        logger.debug(f"🚫 [DIRECT_CANCEL] Cancelled task: {task}")
                    except Exception as e:
                        logger.debug(f"🚫 [DIRECT_CANCEL] Error cancelling task {task}: {e}")
            
            # STEP 6: Cancel agent-task orchestrator operations
            if self.agent_task_orchestrator and hasattr(self.agent_task_orchestrator, 'cancel_current_processing'):
                logger.info("🚫 [DIRECT_CANCEL] Cancelling agent-task orchestrator operations")
                try:
                    await asyncio.wait_for(self.agent_task_orchestrator.cancel_current_processing(), timeout=1.0)
                    logger.info("🚫 [DIRECT_CANCEL] Agent-task orchestrator cancelled")
                except asyncio.TimeoutError:
                    logger.warning("🚫 [DIRECT_CANCEL] Agent-task orchestrator cancellation timed out")
                except Exception as e:
                    logger.error(f"🚫 [DIRECT_CANCEL] Error cancelling agent-task orchestrator: {e}")
            
            # STEP 7: FORCE reset all state flags
            logger.info("🚫 [DIRECT_CANCEL] FORCE-resetting all state flags...")
            self._is_capturing_agent_task = False
            self._agent_task_cancelled = False  # Clear this after everything is cancelled
            
            # CRITICAL: Also clear cancellation flags in all child services
            # This ensures subsequent wake word/hotkey triggers aren't blocked
            if self.wake_word_manager:
                self.wake_word_manager.set_agent_task_state(False, False)
                logger.info("🚫 [DIRECT_CANCEL] Wake word manager flags cleared")
            
            if self.agent_task_capture_service:
                self.agent_task_capture_service.set_agent_task_cancelled(False)
                logger.info("🚫 [DIRECT_CANCEL] Agent-task capture service flag cleared")
            
            if self.agent_task_orchestration_service:
                self.agent_task_orchestration_service.set_agent_task_cancelled(False)
                logger.info("🚫 [DIRECT_CANCEL] Agent-task orchestration service flag cleared")
            
            # STEP 8: FORCE resume wake word detection
            logger.info("🚫 [DIRECT_CANCEL] FORCE-resuming wake word detection...")
            try:
                self._resume_wake_word_detection()
                logger.info("🚫 [DIRECT_CANCEL] Wake word detection resumed")
            except Exception as e:
                logger.error(f"🚫 [DIRECT_CANCEL] Error resuming wake word detection: {e}")
            
            # STEP 9: FORCE restart listening if globally enabled
            if self._is_globally_enabled_by_user and not self._is_actively_listening:
                try:
                    self.start_listening()
                    logger.info("🚫 [DIRECT_CANCEL] Listening restarted")
                except Exception as e:
                    logger.error(f"🚫 [DIRECT_CANCEL] Error restarting listening: {e}")
                
            logger.info("🚫 [DIRECT_CANCEL] ✅ AGGRESSIVE agent_task cancellation completed")
                
        except Exception as e:
            logger.error(f"🚫 [DIRECT_CANCEL] CRITICAL ERROR during aggressive cancellation: {e}", exc_info=True)
            # Emergency fallback - force reset everything we can
            try:
                self._is_capturing_agent_task = False
                self._agent_task_cancelled = False
                if self.audio_capturer and hasattr(self.audio_capturer, '_capture_mode'):
                    self.audio_capturer._capture_mode = "WAKE_WORD"
                logger.warning("🚫 [DIRECT_CANCEL] Emergency fallback state reset completed")
            except Exception as fallback_error:
                logger.error(f"🚫 [DIRECT_CANCEL] Emergency fallback also failed: {fallback_error}")

    def set_event_loop(self, loop):
        """
        Set the main event loop reference for thread-safe async operations.
        This should be called after the FastAPI application starts.
        """
        self.main_event_loop = loop
        logger.info("Main event loop reference set for agent task processing")

    def update_audio_frame_heartbeat(self):
        """Called by audio capturer when processing audio frames to indicate health."""
        self._last_audio_frame_time = time.time()
        
    def update_wake_word_heartbeat(self):
        """Called by wake word detector when processing audio to indicate health."""
        self._last_heartbeat_time = time.time()

    async def _perform_functionality_health_check(self) -> bool:
        """
        Perform comprehensive health check by actually testing system functionality.
        Returns True if system is healthy, False if restart is needed.
        """
        try:
            # Check 1: Verify all core components exist and are initialized
            if not self.wake_word_detector or not self.audio_capturer:
                logger.warning("Health check failed: Core components not initialized")
                return False
            
            # Check 2: Verify wake word detector model is loaded
            if not self.wake_word_detector.oww_model:
                logger.warning("Health check failed: Wake word detector model not loaded")
                return False
            
            # Check 3: Check if audio capturer process is alive
            if hasattr(self.audio_capturer, '_ffmpeg_process'):
                ffmpeg_process = self.audio_capturer._ffmpeg_process
                if not ffmpeg_process or ffmpeg_process.poll() is not None:
                    logger.warning("Health check failed: FFmpeg audio capture process is not running")
                    return False
            
            # Check 4: Verify audio capturer is in correct state
            if not getattr(self.audio_capturer, '_is_capturing', False):
                logger.warning("Health check failed: Audio capturer not in capturing state")
                return False
            
            # Check 5: Test wake word detector functionality with synthetic audio
            test_successful = await self._test_wake_word_detector_functionality()
            if not test_successful:
                logger.warning("Health check failed: Wake word detector functionality test failed")
                return False
            
            # Check 6: Verify capture mode is correct
            current_mode = getattr(self.audio_capturer, '_capture_mode', None)
            if current_mode != "WAKE_WORD":
                logger.warning(f"Health check failed: Audio capturer in wrong mode: {current_mode}")
                return False
            
            # All checks passed
            logger.debug("Wake word detection health check passed")
            
            # Development mode logging - log detailed success information
            if settings.DEBUG:
                logger.info("🩺 [HEALTH_CHECK_DEBUG] ===== COMPREHENSIVE HEALTH CHECK PASSED =====")
                logger.info(f"🩺 [HEALTH_CHECK_DEBUG] ✅ Core components initialized: wake_word_detector={bool(self.wake_word_detector)}, audio_capturer={bool(self.audio_capturer)}")
                logger.info(f"🩺 [HEALTH_CHECK_DEBUG] ✅ Wake word model loaded: {bool(self.wake_word_detector.oww_model if self.wake_word_detector else False)}")
                
                # FFmpeg process status
                if hasattr(self.audio_capturer, '_ffmpeg_process'):
                    ffmpeg_process = self.audio_capturer._ffmpeg_process
                    process_status = "running" if ffmpeg_process and ffmpeg_process.poll() is None else "stopped"
                    process_pid = ffmpeg_process.pid if ffmpeg_process else "N/A"
                    logger.info(f"🩺 [HEALTH_CHECK_DEBUG] ✅ FFmpeg process status: {process_status} (PID: {process_pid})")
                
                # Audio capturer state
                capturing_state = getattr(self.audio_capturer, '_is_capturing', False)
                capture_mode = getattr(self.audio_capturer, '_capture_mode', 'unknown')
                logger.info(f"🩺 [HEALTH_CHECK_DEBUG] ✅ Audio capturer state: capturing={capturing_state}, mode={capture_mode}")
                
                # Wake word detector health
                if self.wake_word_detector:
                    error_count = getattr(self.wake_word_detector, '_consecutive_errors', 0)
                    is_paused = getattr(self.wake_word_detector, '_is_paused', False)
                    logger.info(f"🩺 [HEALTH_CHECK_DEBUG] ✅ Wake word detector health: errors={error_count}, paused={is_paused}")
                
                # Audio buffer status
                if hasattr(self.audio_capturer, '_audio_buffer'):
                    buffer_size = len(getattr(self.audio_capturer, '_audio_buffer', []))
                    logger.info(f"🩺 [HEALTH_CHECK_DEBUG] ✅ Audio buffer status: {buffer_size} bytes")
                
                logger.info(f"🩺 [HEALTH_CHECK_DEBUG] ✅ Synthetic functionality test: PASSED")
                logger.info(f"🩺 [HEALTH_CHECK_DEBUG] ===== ALL HEALTH CRITERIA MET - SYSTEM OPERATIONAL =====")
            
            return True
            
        except Exception as e:
            logger.error(f"Health check failed with exception: {e}")
            return False

    async def _test_wake_word_detector_functionality(self) -> bool:
        """
        Test wake word detector by sending a small synthetic audio sample.
        Returns True if detector processes it without error.
        """
        try:
            # Create a small synthetic audio frame (80ms of low-level noise)
            import numpy as np
            test_frame = np.random.randint(-100, 100, size=1280, dtype=np.int16)
            
            # Get initial state
            initial_consecutive_errors = getattr(self.wake_word_detector, '_consecutive_errors', 0)
            
            # Process the test frame
            self.wake_word_detector.process_audio_frame(test_frame)
            
            # Check if processing increased error count (indicates failure)
            current_consecutive_errors = getattr(self.wake_word_detector, '_consecutive_errors', 0)
            
            if current_consecutive_errors > initial_consecutive_errors:
                logger.warning("Wake word detector functionality test failed - error count increased")
                return False
                
            return True
            
        except Exception as e:
            logger.warning(f"Wake word detector functionality test failed with exception: {e}")
            return False

    async def _health_monitor(self):
        """Background task that actively tests wake word detection functionality."""
        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                
                if not self._is_globally_enabled_by_user or not self._is_actively_listening or self._restart_in_progress:
                    self._consecutive_health_failures = 0  # Reset failures when not monitoring
                    continue
                
                # Perform comprehensive health check
                is_healthy = await self._perform_functionality_health_check()
                
                if is_healthy:
                    self._consecutive_health_failures = 0
                else:
                    self._consecutive_health_failures += 1
                    logger.warning(f"Wake word detection health check failed ({self._consecutive_health_failures}/{self._max_failed_health_checks})")
                    
                    if self._consecutive_health_failures >= self._max_failed_health_checks:
                        logger.error("Wake word detection has failed multiple consecutive health checks - restarting")
                        await self._restart_wake_word_detection()
                        self._consecutive_health_failures = 0
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health monitor error: {e}")
                await asyncio.sleep(5)  # Brief pause before retrying

    async def _restart_wake_word_detection(self):
        """Restart wake word detection components to recover from failure."""
        if self._restart_in_progress:
            return
            
        self._restart_in_progress = True
        logger.info("🔄 Restarting wake word detection due to health check failure...")
        
        try:
            # Stop current listening
            if self._is_actively_listening:
                self.stop_listening()
                await asyncio.sleep(1)  # Brief pause for cleanup
            
            # Reinitialize components
            self._initialize_components()
            
            # Reset error counts in wake word detector after reinitialization
            if self.wake_word_detector:
                self.wake_word_detector.reset_error_count()
            
            # Restart listening
            if self._is_globally_enabled_by_user:
                self.start_listening()
                
            # Reset health tracking
            current_time = time.time()
            self._last_audio_frame_time = current_time
            self._last_heartbeat_time = current_time
            
            logger.info("✅ Wake word detection restart completed")
            
        except Exception as e:
            logger.error(f"Failed to restart wake word detection: {e}")
        finally:
            self._restart_in_progress = False

    def set_current_screenshot_data(self, screenshot_data: Dict[str, Any]):
        """Set the current screenshot data for agent-task processing."""
        self._current_screenshot_data = screenshot_data
        if self.agent_task_submission_service:
            self.agent_task_submission_service.set_current_screenshot_data(screenshot_data)
        if screenshot_data and screenshot_data.get('success'):
            logger.info(f"📸 Screenshot data stored in main service (app: {screenshot_data.get('app_name', 'Unknown')})")
        else:
            logger.info("📸 Screenshot data cleared in main service")

    def get_current_screenshot_data(self) -> Optional[Dict[str, Any]]:
        """Get the current screenshot data that was captured during wake word detection."""
        if self._current_screenshot_data and self._current_screenshot_data.get('success'):
            logger.info(f"📸 Retrieved screenshot data from main service (app: {self._current_screenshot_data.get('app_name', 'Unknown')})")
        else:
            logger.info("📸 No screenshot data available in main service")
        return self._current_screenshot_data

# Example of how this service might be managed by the application:
# app_startup():
#     global voice_listener_service_instance
#     # Initialize with Basil services
#     basil_services = {
#         'window_capture': window_capture_service,
#         'ocr': ocr_service,
#         'suggestion': suggestion_service,
#         'conversation': conversation_service,
#         'assistant_session': assistant_session_service,
#         'knowledge': knowledge_service,
#         'activity': activity_service
#     }
#     voice_listener_service_instance = VoiceListenerService(
#         llm_service=my_llm_service,
#         basil_services=basil_services
#     )

# app_shutdown():
#     if voice_listener_service_instance._agent_task_capture_task:
#         voice_listener_service_instance._agent_task_capture_task.cancel()