import logging
import numpy as np
import time # For basic timing/delay in placeholder listening loop
import os # For bundled model detection
import sys # For bundled app detection
import glob # For bundled model verification

# Use the exact same logger setup as basil_api.py (creates api.api.main)
from ...core.logging.api_logger import setup_api_logger
from ...core.config.api_settings import settings

# Use the same logging setup as main.py to ensure logs appear in packaged builds
logger = setup_api_logger(
    "api.main",
    level=logging.DEBUG if settings.DEBUG else logging.INFO
)

# CRITICAL DEBUG: Log import attempt at module level
logger.info("🔍 [OPENWAKEWORD_DEBUG] Starting OpenWakeWord import attempt...")

try:
    logger.info("🔍 [OPENWAKEWORD_DEBUG] Attempting to import openwakeword.model.Model...")
    from openwakeword.model import Model as OpenWakeWordModel
    logger.info("✅ [OPENWAKEWORD_DEBUG] openwakeword.model.Model imported successfully")
    
    logger.info("🔍 [OPENWAKEWORD_DEBUG] Attempting to import openwakeword.utils.download_models...")
    from openwakeword.utils import download_models # Import for downloading models
    logger.info("✅ [OPENWAKEWORD_DEBUG] openwakeword.utils.download_models imported successfully")
    
    # For OpenWakeWord >= 0.5.0, VAD is often integrated or handled differently.
    # from openwakeword.vad import VAD # May not be needed if using built-in VAD options
    OPENWAKEWORD_AVAILABLE = True
    logger.info("✅ [OPENWAKEWORD_DEBUG] All OpenWakeWord imports successful!")
except ImportError as e:
    logger.error(f"❌ [OPENWAKEWORD_DEBUG] OpenWakeWord ImportError: {e}")
    OpenWakeWordModel = None
    download_models = None
    OPENWAKEWORD_AVAILABLE = False
except Exception as e:
    logger.error(f"❌ [OPENWAKEWORD_DEBUG] OpenWakeWord unexpected error: {e}")
    OpenWakeWordModel = None
    download_models = None
    OPENWAKEWORD_AVAILABLE = False

logger.info(f"🔍 [OPENWAKEWORD_DEBUG] Final result - OPENWAKEWORD_AVAILABLE: {OPENWAKEWORD_AVAILABLE}")

# Using pre-trained OpenWakeWord models.
# The actual .onnx file paths will be resolved by OpenWakeWord after models are downloaded.
# We will primarily use "hey_jarvis". We can add "basil" if a separate model
# exists or is trained later.
PRE_TRAINED_MODELS_TO_USE = ["hey_jarvis", "hey_basil_proper", "hey_basil_american"]

class WakeWordDetector:
    def __init__(self, 
                 wake_phrases_models: list[str] = None, 
                 sensitivity: float = 0.5, # Default sensitivity for OWW models
                 on_wake_word_detected_callback=None,
                 heartbeat_callback=None,
                 inference_framework: str = 'onnx'): # 'onnx' or 'tflite'
        """
        Initializes the WakeWordDetector using OpenWakeWord.

        Args:
            wake_phrases_models: A list of pre-trained model names (e.g., ["hey_jarvis"]) 
                                 or paths to custom .onnx model files.
                                 If None, uses PRE_TRAINED_MODELS_TO_USE.
            sensitivity: Detection sensitivity/threshold for OpenWakeWord (typically 0.0 to 1.0).
                         This might be overridden by individual model thresholds if OWW supports it.
            on_wake_word_detected_callback: A callback function to execute when a wake word is detected.
                                            This callback might receive the detected phrase/model name as an argument.
            heartbeat_callback: A callback function to call after successful audio processing
                               to indicate the detector is working properly (for health monitoring).
            inference_framework: The inference framework to use ('onnx' or 'tflite').
                                 'onnx' is generally preferred if available.
        """
        if not OPENWAKEWORD_AVAILABLE:
            logger.error("🚨 [OPENWAKEWORD_IMPORT_ERROR] OpenWakeWord library not found. WakeWordDetector will not function.")
            logger.error("🚨 [OPENWAKEWORD_IMPORT_ERROR] This will prevent 'Hey Basil' wake word detection.")
            logger.error("🚨 [OPENWAKEWORD_IMPORT_ERROR] In packaged apps: Check if openwakeword is in hiddenimports")
            logger.error("🚨 [OPENWAKEWORD_IMPORT_ERROR] In development: Install with 'pip install openwakeword'")
            self.oww_model = None
            self.active_models = {}
            return

        # Check for bundled models first (for packaged app)
        bundled_models_dir = self._find_bundled_models_directory()
        models_to_use = wake_phrases_models if wake_phrases_models else PRE_TRAINED_MODELS_TO_USE
        
        if bundled_models_dir:
            logger.info(f"🎯 Found bundled wake word models directory: {bundled_models_dir}")
            # Convert model names to bundled file paths
            bundled_model_paths = []
            for model_name in models_to_use:
                # Handle both model names and existing file paths
                if not ('.' in model_name and ('/' in model_name or '\\' in model_name)):
                    # It's a model name, convert to bundled path (handle versioned filenames)
                    # Only check for .onnx files (TFLite support removed)
                    onnx_matches = glob.glob(os.path.join(bundled_models_dir, f"{model_name}*.onnx"))
                    
                    if onnx_matches:
                        bundled_path = onnx_matches[0]
                    else:
                        # Fall back to expected .onnx path for download
                        bundled_path = os.path.join(bundled_models_dir, f"{model_name}.onnx")
                    
                    if os.path.exists(bundled_path):
                        bundled_model_paths.append(bundled_path)
                        logger.info(f"✅ Using bundled model: {bundled_path}")
                    else:
                        logger.warning(f"⚠️ Bundled model not found: {bundled_path}")
                        bundled_model_paths.append(model_name)  # Fall back to name
                else:
                    # It's already a path
                    bundled_model_paths.append(model_name)
            
            self.wake_phrases_models_config = bundled_model_paths
            logger.info(f"🎯 Using bundled wake word models: {self.wake_phrases_models_config}")
        else:
            logger.info("🔽 No bundled models found, attempting to download models...")
            # Original download logic for development environment
            try:
                # For now, attempt to download the specific models we intend to use.
                # If wake_phrases_models is provided by the user, they are responsible for ensuring those models are present.
                models_to_check_or_download = models_to_use
                if download_models: # Check if import was successful
                     # Filter out actual file paths if any are mixed in, only download by name
                    downloadable_model_names = [m for m in models_to_check_or_download if not ('.' in m and ('/' in m or '\\' in m))]
                    if downloadable_model_names:
                        logger.info(f"Ensuring OpenWakeWord models are available: {downloadable_model_names}")
                        download_models(model_names=downloadable_model_names) 
            except Exception as e:
                logger.error(f"Error during OpenWakeWord model download attempt: {e}")
                # Proceeding, oww_model initialization will likely fail if models are missing.

            self.wake_phrases_models_config = models_to_use

        self.sensitivity = sensitivity # This is a general threshold; OWW might have per-model thresholds
        self.on_wake_word_detected_callback = on_wake_word_detected_callback
        self.heartbeat_callback = heartbeat_callback
        self.inference_framework = inference_framework
        
        self.oww_model = None
        self.active_models = {}

        # Health tracking
        self._last_successful_prediction = None
        self._consecutive_errors = 0
        self._max_consecutive_errors = 5
        self._model_disabled = False  # Track if model is disabled due to errors

        try:
            logger.info(f"Initializing OpenWakeWordModel with models: {self.wake_phrases_models_config}")
            self.oww_model = OpenWakeWordModel(
                wakeword_models=self.wake_phrases_models_config, 
                # inference_framework=self.inference_framework # Newer versions might take this
                # enable_speex_noise_suppression=True, # Optional: good for noisy environments
                # vad_threshold=0.5 # Optional: Silero VAD threshold
            )
            # For newer versions, inference_framework might be specified differently or automatically chosen.
            # Check OpenWakeWord documentation for the version you are using.
            
            # Initialize active_models keys based on loaded models in oww_model
            # The oww_model.models dictionary keys are the "prediction keys"
            if self.oww_model and hasattr(self.oww_model, 'models'):
                 for model_key in self.oww_model.models.keys():
                    self.active_models[model_key] = 0.0 # Initialize scores to 0
                 logger.info(f"OpenWakeWord detector initialized for models: {list(self.active_models.keys())}")
            else:
                logger.warning("OpenWakeWord model object does not have 'models' attribute or failed to initialize. Prediction keys might be missing.")

        except Exception as e:
            logger.error(f"Failed to initialize OpenWakeWordModel: {e}")
            logger.error("Ensure 'openwakeword' is installed and models are downloaded/paths are correct.")
            self.oww_model = None # Ensure it's None if initialization fails

        # Placeholder for listening state
        self._is_listening = False
        self._audio_input_task = None

        # Pause state for preventing false triggers during transcription
        self._is_paused = False

    def _find_bundled_models_directory(self):
        """
        Find the bundled wake word models directory.
        
        Returns:
            str: Path to bundled models directory, or None if not found
        """
        
        # Possible bundled model locations
        possible_locations = []
        
        # Check if we're in a bundled app (app bundle structure)
        if hasattr(sys, '_MEIPASS'):
            # PyInstaller bundle
            possible_locations.append(os.path.join(sys._MEIPASS, 'wake_word_models'))
        
        # Check for macOS app bundle structure
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        
        # If we're in a .app bundle (Contents/MacOS/), go up to Resources/backend/wake_word_models
        if 'Contents/MacOS' in exe_dir:
            app_bundle_contents = os.path.dirname(exe_dir)  # Contents/
            app_bundle_resources = os.path.join(app_bundle_contents, 'Resources')
            possible_locations.append(os.path.join(app_bundle_resources, 'backend', 'wake_word_models'))
        
        # Check relative to current working directory (for development)
        cwd = os.getcwd()
        possible_locations.extend([
            os.path.join(cwd, 'wake_word_models'),
            os.path.join(cwd, 'backend', 'wake_word_models'),
            os.path.join(cwd, '..', 'wake_word_models'),
            # Check vendor models directory
            os.path.join(cwd, 'Basil', 'src', 'api', 'vendor', 'models', 'wake_word'),
            os.path.join(cwd, 'src', 'api', 'vendor', 'models', 'wake_word'),
        ])
        
        # Check each possible location
        for location in possible_locations:
            if os.path.isdir(location):
                # Only look for .onnx files (TFLite support removed)
                onnx_files = glob.glob(os.path.join(location, '*.onnx'))
                
                if len(onnx_files) > 0:
                    logger.info(f"🎯 Found bundled models directory with {len(onnx_files)} .onnx files: {location}")
                    return location
                else:
                    logger.debug(f"Directory exists but no .onnx files found: {location}")
        
        logger.info("🔍 No bundled wake word models directory found")
        return None

    def process_audio_frame(self, frame: np.ndarray):
        """
        Processes a single audio frame for wake word detection.

        Args:
            frame: A NumPy array containing audio samples (16-bit PCM, 16kHz).
                   The frame size should ideally be 80ms (1280 samples).
        """
        # DEBUG: Track frame processing to diagnose audio flow issues
        if not hasattr(self, '_frame_count'):
            self._frame_count = 0
        self._frame_count += 1
        
        # Log first few frames and then every 100th frame
        if self._frame_count <= 5 or self._frame_count % 100 == 0:
            logger.info(f"🎵 [WAKE_WORD_DEBUG] Processing audio frame #{self._frame_count}, shape: {frame.shape}, dtype: {frame.dtype}")
        
        if not self.oww_model or not OPENWAKEWORD_AVAILABLE:
            # logger.warning("OpenWakeWord model not initialized or library not available. Cannot process audio.")
            return

        # If model has been disabled due to errors, skip processing silently
        if self._model_disabled:
            return

        # Skip processing if wake word detection is paused
        if self._is_paused:
            # Only log occasionally to avoid spam, but log it so we know it's working
            import random
            if random.random() < 0.01:  # Log ~1% of skipped frames
                logger.info("🔇 Skipping audio frame processing - wake word detection is paused")
            return

        if not isinstance(frame, np.ndarray):
            logger.warning("Audio frame is not a NumPy array. Skipping.")
            self._consecutive_errors += 1
            return
        
        # Ensure frame is int16 if it's not already, as OWW expects int16 PCM
        if frame.dtype != np.int16:
            if np.issubdtype(frame.dtype, np.floating): # e.g. float32, float64
                # Assuming float is in range -1.0 to 1.0, convert to int16
                frame = (frame * 32767).astype(np.int16)
            else:
                try:
                    frame = frame.astype(np.int16)
                except ValueError:
                    logger.error(f"Could not convert audio frame of dtype {frame.dtype} to int16. Skipping.")
                    self._consecutive_errors += 1
                    return

        try:
            # Get predictions for the current frame
            # The result is a dictionary with model names as keys and scores (0-1) as values
            predictions = self.oww_model.predict(frame)
            
            # Track successful prediction for health monitoring
            self._last_successful_prediction = time.time()
            self._consecutive_errors = 0  # Reset error count on success
            
            for model_name, score in predictions.items():
                self.active_models[model_name] = score # Update score for this model
                
                # Log near-misses to help diagnose model reliability
                if score > 0.5 and score <= self.sensitivity:
                    logger.debug(f"⚠️ Near-miss: '{model_name}' score {score:.2f} (threshold: {self.sensitivity:.2f})")
                
                if score > self.sensitivity: # Using the global sensitivity for now
                    logger.info(f"Wake word '{model_name}' detected with score: {score:.2f}")
                    if self.on_wake_word_detected_callback:
                        try:
                            self.on_wake_word_detected_callback(model_name)
                        except Exception as e:
                            logger.error(f"Error in on_wake_word_detected_callback for '{model_name}': {e}")
            
            # Send heartbeat to health monitoring system
            if self.heartbeat_callback:
                try:
                    self.heartbeat_callback()
                except Exception as e:
                    logger.warning(f"Error in heartbeat callback: {e}")
                    
        except Exception as e:
            self._consecutive_errors += 1
            
            # Only log errors for the first few attempts and then every 50th error to reduce spam
            if self._consecutive_errors <= self._max_consecutive_errors or self._consecutive_errors % 50 == 0:
                logger.error(f"Error during OpenWakeWord prediction: {e} (consecutive errors: {self._consecutive_errors})")
            
            # If we've had too many consecutive errors, disable the model to stop spam
            if self._consecutive_errors >= self._max_consecutive_errors and not self._model_disabled:
                logger.error(f"🚨 WakeWordDetector: {self._consecutive_errors} consecutive errors detected - DISABLING wake word detection to prevent log spam")
                logger.error(f"🚨 Likely cause: Custom 'hey_basil' model incompatible with OpenWakeWord preprocessing")
                logger.error(f"🚨 Recommendation: Retrain custom model or fall back to 'hey_jarvis' only")
                self._model_disabled = True
                
                # Try to fall back to just hey_jarvis if hey_basil is causing issues
                self._attempt_fallback_to_hey_jarvis()

    def _attempt_fallback_to_hey_jarvis(self):
        """
        Attempt to reinitialize the model with only 'hey_jarvis' to avoid custom model issues.
        """
        try:
            logger.warning("🔄 Attempting to fall back to 'hey_jarvis' model only...")
            
            # Find the path to hey_jarvis model
            fallback_models = []
            
            # Check if we have bundled models
            bundled_models_dir = self._find_bundled_models_directory()
            if bundled_models_dir:
                # Look for hey_jarvis in bundled models
                import glob
                jarvis_matches = glob.glob(os.path.join(bundled_models_dir, "hey_jarvis*.onnx"))
                if jarvis_matches:
                    fallback_models = [jarvis_matches[0]]
                    logger.info(f"Found bundled hey_jarvis model: {jarvis_matches[0]}")
            
            # If no bundled model, try standard name
            if not fallback_models:
                fallback_models = ["hey_jarvis"]
                logger.info("Using standard 'hey_jarvis' model name for fallback")
            
            # Try to reinitialize with just hey_jarvis
            logger.info(f"Reinitializing OpenWakeWord with fallback models: {fallback_models}")
            self.oww_model = OpenWakeWordModel(wakeword_models=fallback_models)
            
            # Reset error tracking
            self._consecutive_errors = 0
            self._model_disabled = False
            
            # Update active models
            self.active_models = {}
            if self.oww_model and hasattr(self.oww_model, 'models'):
                for model_key in self.oww_model.models.keys():
                    self.active_models[model_key] = 0.0
                logger.info(f"✅ Fallback successful! Active models: {list(self.active_models.keys())}")
            else:
                logger.error("❌ Fallback failed - model still not working")
                self._model_disabled = True
                
        except Exception as e:
            logger.error(f"❌ Fallback to hey_jarvis failed: {e}")
            self._model_disabled = True

    # --- Placeholder methods for starting/stopping listening ---
    # These would be controlled by a higher-level service that manages 
    # audio input and the lifecycle of this detector.

    def start_listening(self, audio_input_callable):
        """
        Starts the wake word detection process. (Conceptual)
        In a real implementation, this would likely mean an external audio
        source starts feeding frames to process_audio_frame.

        Args:
            audio_input_callable: A function that, when called, provides the next audio frame.
                                   This is a placeholder for a real audio input stream.
        """
        if not OPENWAKEWORD_AVAILABLE or not self.oww_model:
            logger.error("Cannot start listening: OpenWakeWord not available or model not loaded.")
            return
            
        if self._is_listening:
            logger.info("Already listening.")
            return

        logger.info("WakeWordDetector starting to 'listen' (placeholder loop)...")
        self._is_listening = True
        
        # This is a simplified conceptual loop. In reality, audio frames would come from
        # a dedicated audio capturer running in its own thread/task.
        def _placeholder_listener_loop():
            while self._is_listening:
                try:
                    # In a real scenario, audio_input_callable would block until a frame is ready
                    # or be part of an async system.
                    # frame = audio_input_callable() # Example: get_audio_frame_from_microphone()
                    # self.process_audio_frame(frame)
                    
                    # Simulate receiving frames for demonstration if no callable provided
                    if audio_input_callable is None:
                        # Create a dummy 80ms frame of random noise for testing
                        dummy_frame = np.random.randint(-1000, 1000, size=1280, dtype=np.int16)
                        self.process_audio_frame(dummy_frame)
                        time.sleep(0.080) # Sleep for 80ms to simulate real-time processing
                    else:
                        # If a callable is provided, it should handle its own timing/blocking
                        frame = audio_input_callable()
                        if frame is not None:
                             self.process_audio_frame(frame)
                        else: # If callable returns None, perhaps stream ended
                            logger.info("Audio input callable returned None, stopping placeholder loop.")
                            self._is_listening = False # Or handle according to callable's contract
                            
                except Exception as e:
                    logger.error(f"Error in placeholder listening loop: {e}")
                    self._is_listening = False # Stop on error
                    break
            logger.info("Placeholder listening loop stopped.")

        # Running the placeholder loop in a separate thread for non-blocking behavior
        # Again, this is conceptual for a self-contained test.
        # A real audio capturer would manage its own threading.
        if audio_input_callable is None: # Only run placeholder if no real input is given
            import threading
            self._audio_input_task = threading.Thread(target=_placeholder_listener_loop)
            self._audio_input_task.daemon = True # Allow main program to exit
            self._audio_input_task.start()
        else:
            # If an audio_input_callable is provided, it's assumed to be handled externally
            # or this start_listening method would be part of a system that calls
            # process_audio_frame in a loop.
            logger.info("Audio input callable provided. process_audio_frame should be called externally or by the callable's mechanism.")


    def stop_listening(self):
        """
        Stops the wake word detection process. (Conceptual)
        """
        if not self._is_listening:
            logger.info("Not currently listening.")
            return

        logger.info("WakeWordDetector stopping 'listening'...")
        self._is_listening = False
        if self._audio_input_task and self._audio_input_task.is_alive():
            # self._audio_input_task.join(timeout=1.0) # Wait briefly for thread to stop
            pass # In a real scenario, a more robust thread/task cancellation is needed
        self._audio_input_task = None
        logger.info("WakeWordDetector 'listening' stopped.")

    def set_paused(self, paused: bool):
        """
        Pause or resume wake word detection.
        
        When paused, process_audio_frame will immediately return without processing.
        This is useful during transcription processing to prevent false wake word triggers
        from audio feedback or processing artifacts.
        
        Args:
            paused: True to pause detection, False to resume
        """
        logger.info(f"🔇 [PAUSE_DEBUG] set_paused() called with paused={paused}, current _is_paused={self._is_paused}")
        
        if paused != self._is_paused:
            logger.info(f"🔇 [PAUSE_DEBUG] State change needed: {self._is_paused} → {paused}")
            
            # CRITICAL: Set the state IMMEDIATELY before any complex operations
            # This prevents race conditions where exceptions could leave us in inconsistent state
            old_state = self._is_paused
            self._is_paused = paused
            logger.info(f"🔇 [PAUSE_DEBUG] State updated: _is_paused set to {self._is_paused}")
            
            # When pausing OR resuming, clear internal model buffers to ensure clean state
            if self.oww_model:
                try:
                    action = "pausing" if paused else "resuming"
                    logger.info(f"🧹 Clearing OpenWakeWord model internal buffers while {action}...")
                    
                    # Multi-layer buffer clearing approach for thorough cleanup
                    # Layer 1: Standard model reset
                    if hasattr(self.oww_model, 'reset'):
                        self.oww_model.reset()
                        logger.debug("✅ Called OpenWakeWord model.reset()")
                    
                    # Layer 2: Clear our local active model scores
                    for model_key in self.active_models.keys():
                        self.active_models[model_key] = 0.0
                    logger.debug("✅ Reset local active model scores")
                    
                    # Layer 3: Additional thorough clearing when resuming (most critical for phantom detection prevention)
                    if not paused:  # Only when resuming
                        try:
                            # Process several silent frames to flush any residual internal state
                            # This helps clear temporal buffers and feature extraction state
                            silent_frame = np.zeros(1280, dtype=np.int16)  # 80ms of silence at 16kHz
                            
                            logger.debug("🧹 Flushing OpenWakeWord internal state with silent frames...")
                            for i in range(3):  # Process 3 silent frames (240ms total)
                                try:
                                    # Temporarily disable callback to prevent any detections during flush
                                    temp_callback = self.on_wake_word_detected_callback
                                    self.on_wake_word_detected_callback = None
                                    
                                    # Process silent frame to flush internal buffers
                                    predictions = self.oww_model.predict(silent_frame)
                                    
                                    # Restore callback
                                    self.on_wake_word_detected_callback = temp_callback
                                    
                                    logger.debug(f"✅ Processed silent frame {i+1}/3 for buffer flush")
                                except Exception as e:
                                    logger.warning(f"Error during silent frame flush {i+1}: {e}")
                                    break
                            
                            logger.debug("✅ Completed silent frame flush sequence")
                        except Exception as flush_error:
                            logger.warning(f"Silent frame flush failed, but continuing: {flush_error}")
                    
                    logger.info("✅ OpenWakeWord model reset completed")
                except Exception as e:
                    logger.error(f"❌ [PAUSE_DEBUG] Buffer clearing failed: {e}")
                    # CRITICAL: Don't let buffer clearing failure prevent state change
                    # The state was already set above, so this is just cleanup
                    logger.warning(f"🔇 [PAUSE_DEBUG] Buffer clearing failed, but state change still applied: _is_paused={self._is_paused}")
            else:
                logger.warning("🔇 [PAUSE_DEBUG] No oww_model available for buffer clearing")
            
            state_str = "paused" if paused else "resumed"
            logger.info(f"🔇 Wake word detection {state_str} (was: {old_state}, now: {self._is_paused})")
            logger.info(f"🔇 [PAUSE_DEBUG] Final verification: _is_paused={self._is_paused}, target_paused={paused}")
        else:
            logger.info(f"🔇 Wake word detection already {('paused' if paused else 'active')} - no change needed")
            logger.info(f"🔇 [PAUSE_DEBUG] No state change: _is_paused={self._is_paused} matches target={paused}")

    def is_paused(self) -> bool:
        """
        Check if wake word detection is currently paused.
        
        Returns:
            True if paused, False if active
        """
        return self._is_paused

    def get_health_status(self) -> dict:
        """
        Get health status information for monitoring.
        
        Returns:
            Dictionary with health metrics
        """
        current_time = time.time()
        return {
            "model_loaded": self.oww_model is not None,
            "model_disabled": self._model_disabled,
            "last_successful_prediction": self._last_successful_prediction,
            "time_since_last_success": current_time - self._last_successful_prediction if self._last_successful_prediction else None,
            "consecutive_errors": self._consecutive_errors,
            "max_consecutive_errors": self._max_consecutive_errors,
            "is_paused": self._is_paused,
            "active_models": list(self.active_models.keys()) if self.active_models else [],
            "openwakeword_available": OPENWAKEWORD_AVAILABLE
        }

    def reset_error_count(self):
        """Reset the consecutive error count (used during recovery)."""
        self._consecutive_errors = 0
        logger.info("🔄 WakeWordDetector error count reset")


# Example Usage (conceptual, for testing this file directly)
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    logger.info("Running WakeWordDetector example...")

    if not OPENWAKEWORD_AVAILABLE:
        logger.error("OpenWakeWord not installed. Cannot run example.")
    else:
        def my_callback(phrase):
            print(f"CALLBACK: Wake word '{phrase}' DETECTED!")

        # Initialize with the pre-trained "hey_jarvis" model
        detector = WakeWordDetector(on_wake_word_detected_callback=my_callback)

        if detector.oww_model: # Check if model loaded successfully
            print("Starting placeholder listening for 10 seconds...")
            # For this direct test, we use the internal placeholder loop that generates dummy audio.
            # In a real app, an external audio source would call process_audio_frame().
            detector.start_listening(audio_input_callable=None) 
            
            time.sleep(10) # Let it run for a bit
            detector.stop_listening()
            print("Example finished.")
        else:
            print("Failed to initialize WakeWordDetector model. Example cannot run.") 