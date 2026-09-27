import ffmpeg
import threading
import time
import numpy as np
import logging
import subprocess
import os
import sys
from typing import Optional # Added for type hinting

# Use the exact same logger setup as basil_api.py (creates api.api.main)
from ...core.logging.api_logger import setup_api_logger
from ...core.config.api_settings import settings

# Import FFmpeg discovery utilities
from .ffmpeg_utils import find_ffmpeg_executable

logger = setup_api_logger(
    "api.main",
    level=logging.DEBUG if settings.DEBUG else logging.INFO
)

# Audio parameters required by OpenWakeWord and for our setup
TARGET_SAMPLE_RATE = 16000  # Hz
TARGET_CHANNELS = 1         # Mono
TARGET_SAMPLE_WIDTH = 2     # Bytes (for 16-bit PCM s16le)
TARGET_CHUNK_DURATION_MS = 80 # Milliseconds
TARGET_SAMPLES_PER_CHUNK = int((TARGET_SAMPLE_RATE / 1000) * TARGET_CHUNK_DURATION_MS) # 1280 samples
TARGET_BYTES_PER_CHUNK = TARGET_SAMPLES_PER_CHUNK * TARGET_SAMPLE_WIDTH * TARGET_CHANNELS # 2560 bytes

# Capture modes
CAPTURE_MODE_WAKE_WORD = "WAKE_WORD"
CAPTURE_MODE_AGENT_TASK = "AGENT_TASK_CAPTURE"
DEFAULT_AGENT_TASK_CAPTURE_DURATION_SECONDS = 12.0 # Set to 12 seconds

class WakeWordAudioCapturer:
    def __init__(self, wake_word_detector, audio_device_name="default"):
        """
        Initializes the audio capturer.

        Args:
            wake_word_detector: An instance of WakeWordDetector to send audio frames to.
            audio_device_name: The name or index of the audio input device for FFmpeg.
                               On macOS, for avfoundation, "default" usually works for the default mic.
                               On Linux, for alsa, it might be "hw:0,0" or similar.
        """
        self.wake_word_detector = wake_word_detector
        self.audio_device_name = audio_device_name
        self._ffmpeg_process = None
        self._capture_thread = None
        self._is_capturing = False
        self._pcm_buffer = bytearray()
        self._stderr_thread = None # Added for stderr logging

        # New state variables for agent-task capture
        self._capture_mode = CAPTURE_MODE_WAKE_WORD  # Can be "WAKE_WORD" or "AGENT_TASK_CAPTURE"
        self._agent_task_audio_buffer = bytearray()
        self._agent_task_capture_duration_seconds = DEFAULT_AGENT_TASK_CAPTURE_DURATION_SECONDS
        self._agent_task_capture_start_time: Optional[float] = None
        self._agent_task_capture_lock = threading.Lock() # To protect agent-task capture buffer and mode
        
        # Buffer housekeeping to prevent indefinite accumulation
        self._last_buffer_clear_time = 0.0
        self._buffer_clear_interval = 30.0  # Clear PCM buffer every 30 seconds during wake word mode
        
        # Find bundled FFmpeg path using utility function
        self._ffmpeg_path = find_ffmpeg_executable()
        logger.info(f"🎵 Audio capturer will use FFmpeg at: {self._ffmpeg_path}")

    def _log_stderr_loop(self, process):
        """Reads and logs lines from the ffmpeg process's stderr stream."""
        try:
            if process and process.stderr:
                for line in iter(process.stderr.readline, b''):
                    if not line:
                        break
                    logger.info(f"FFMPEG_STDERR: {line.decode(errors='ignore').strip()}")
            logger.info("FFmpeg stderr stream ended.")
        except Exception as e:
            logger.error(f"Exception in _log_stderr_loop: {e}", exc_info=True)
        finally:
            logger.info("FFmpeg stderr logging thread finished.")

    def _start_ffmpeg_process(self):
        """Starts the FFmpeg process to capture audio from the microphone."""
        logger.info(f"Starting FFmpeg to capture from device: '{self.audio_device_name}'")
        
        # ENHANCED DIAGNOSTICS FOR PACKAGED APP DEBUGGING
        logger.info(f"🔍 [FFMPEG_DEBUG] FFmpeg path being used: {self._ffmpeg_path}")
        logger.info(f"🔍 [FFMPEG_DEBUG] sys.executable: {sys.executable}")
        logger.info(f"🔍 [FFMPEG_DEBUG] Current working directory: {os.getcwd()}")
        logger.info(f"🔍 [FFMPEG_DEBUG] Audio device name: {self.audio_device_name}")
        
        # Test FFmpeg executable before using it
        try:
            result = subprocess.run([self._ffmpeg_path, '-version'], 
                                  capture_output=True, text=True, timeout=10)
            logger.info(f"🔍 [FFMPEG_DEBUG] FFmpeg version check successful:")
            logger.info(f"🔍 [FFMPEG_DEBUG] FFmpeg stdout: {result.stdout[:200]}...")
            logger.info(f"🔍 [FFMPEG_DEBUG] FFmpeg stderr: {result.stderr[:200]}...")
        except Exception as e:
            logger.error(f"🚨 [FFMPEG_DEBUG] FFmpeg version check failed: {e}")
            # Continue anyway to see what specific error we get

        # Test audio device listing
        try:
            result = subprocess.run([self._ffmpeg_path, '-f', 'avfoundation', '-list_devices', 'true', '-i', ''], 
                                  capture_output=True, text=True, timeout=10)
            logger.info(f"🔍 [FFMPEG_DEBUG] Audio device listing:")
            logger.info(f"🔍 [FFMPEG_DEBUG] Device list stdout: {result.stdout}")
            logger.info(f"🔍 [FFMPEG_DEBUG] Device list stderr: {result.stderr}")
        except Exception as e:
            logger.error(f"🚨 [FFMPEG_DEBUG] Audio device listing failed: {e}")

        try:
            # Determine the FFmpeg input format based on OS or explicit setting later
            # For macOS, avfoundation is standard. For Linux, alsa.
            # This might need to be more configurable.
            input_format = "avfoundation" # macOS default
            # if platform.system() == "Linux":
            #     input_format = "alsa"
            
            # For avfoundation, explicitly try to tell it we don't want video and specify audio params carefully.
            # We also specify the sample rate and channels in the output arguments.
            input_device_specifier = f":{self.audio_device_name}" # Try to be more specific for avfoundation
            logger.info(f"Attempting to use input device specifier: {input_device_specifier}")
            
            # Log the exact FFmpeg command being constructed
            logger.info(f"🔍 [FFMPEG_DEBUG] Building FFmpeg command with:")
            logger.info(f"🔍 [FFMPEG_DEBUG]   - Input: {input_device_specifier}, format: {input_format}")
            logger.info(f"🔍 [FFMPEG_DEBUG]   - Output: pipe:1, format: s16le, codec: pcm_s16le")
            logger.info(f"🔍 [FFMPEG_DEBUG]   - Sample rate: {TARGET_SAMPLE_RATE}, channels: {TARGET_CHANNELS}")
            
            self._ffmpeg_process = (
                ffmpeg
                .input(input_device_specifier, format=input_format, vn=None) # vn=None to disable video input
                .output(
                    "pipe:1", 
                    format="s16le", 
                    acodec="pcm_s16le", 
                    ar=str(TARGET_SAMPLE_RATE), 
                    ac=str(TARGET_CHANNELS)
                )
                .global_args("-hide_banner", "-loglevel", "info") # Changed to info for better debugging
                .run_async(pipe_stdin=False, pipe_stdout=True, pipe_stderr=True, cmd=self._ffmpeg_path)
            )
            logger.info(f"FFmpeg process started. PID: {self._ffmpeg_process.pid}")
            logger.info(f"🔍 [FFMPEG_DEBUG] FFmpeg process poll status: {self._ffmpeg_process.poll()}")

            # Start stderr logging thread
            if self._ffmpeg_process and self._ffmpeg_process.stderr:
                self._stderr_thread = threading.Thread(target=self._log_stderr_loop, args=(self._ffmpeg_process,), daemon=True)
                self._stderr_thread.name = "FFmpegStderrLogThread"
                self._stderr_thread.start()
            else:
                logger.warning("FFmpeg process started but stderr pipe not available for logging.")

        except ffmpeg.Error as e:
            stderr_output = e.stderr.decode('utf8') if e.stderr else "No stderr"
            logger.error(f"🚨 [FFMPEG_DEBUG] Failed to start FFmpeg process: {e}. FFmpeg stderr: {stderr_output}")
            self._ffmpeg_process = None
            raise # Re-raise the exception so the caller knows it failed
        except Exception as e:
            logger.error(f"🚨 [FFMPEG_DEBUG] An unexpected error occurred while starting FFmpeg: {e}")
            logger.error(f"🚨 [FFMPEG_DEBUG] Exception type: {type(e).__name__}")
            logger.error(f"🚨 [FFMPEG_DEBUG] Exception details: {str(e)}")
            self._ffmpeg_process = None
            raise

    def _capture_loop(self):
        """The main loop for capturing audio from FFmpeg and processing it."""
        logger.info("Audio capture loop started.")
        logger.info(f"🔍 [CAPTURE_DEBUG] FFmpeg process: {self._ffmpeg_process}")
        logger.info(f"🔍 [CAPTURE_DEBUG] FFmpeg stdout: {self._ffmpeg_process.stdout if self._ffmpeg_process else None}")
        
        if not self._ffmpeg_process or not self._ffmpeg_process.stdout:
            logger.error("FFmpeg process not running or stdout not available. Cannot capture.")
            self._is_capturing = False # Ensure loop terminates if wrongly started
            return

        try:
            iteration_count = 0
            bytes_read_total = 0
            last_audio_log_time = time.time()
            
            while self._is_capturing:
                iteration_count += 1
                
                # Log first few iterations and then every 50th iteration
                if iteration_count <= 5 or iteration_count % 50 == 0:
                    logger.info(f"🔍 [CAPTURE_DEBUG] Capture loop iteration #{iteration_count}")
                    logger.info(f"🔍 [CAPTURE_DEBUG] FFmpeg process poll: {self._ffmpeg_process.poll()}")
                    logger.info(f"🔍 [CAPTURE_DEBUG] Total bytes read so far: {bytes_read_total}")
                
                try:
                    raw_audio_chunk = self._ffmpeg_process.stdout.read(TARGET_BYTES_PER_CHUNK * 4)
                    
                    # Log detailed info about the audio chunk
                    chunk_size = len(raw_audio_chunk) if raw_audio_chunk else 0
                    bytes_read_total += chunk_size
                    
                    current_time = time.time()
                    if iteration_count <= 10 or current_time - last_audio_log_time > 5.0:  # Log first 10 or every 5 seconds
                        logger.info(f"🔍 [CAPTURE_DEBUG] Read {chunk_size} bytes (iteration #{iteration_count})")
                        if chunk_size == 0:
                            logger.warning(f"🚨 [CAPTURE_DEBUG] Zero bytes read from FFmpeg stdout!")
                        last_audio_log_time = current_time
                        
                except Exception as e:
                    logger.error(f"🚨 [CAPTURE_DEBUG] Error reading from FFmpeg stdout: {e}")
                    if self._ffmpeg_process and self._ffmpeg_process.stderr:
                        try:
                            ffmpeg_err = self._ffmpeg_process.stderr.read(1024).decode(errors='ignore')
                            logger.error(f"🚨 [CAPTURE_DEBUG] FFmpeg stderr (last 1KB): {ffmpeg_err}")
                        except Exception as stderr_e:
                            logger.error(f"🚨 [CAPTURE_DEBUG] Could not read FFmpeg stderr: {stderr_e}")
                    self._is_capturing = False # Stop capturing on read error
                    break

                if not raw_audio_chunk:
                    logger.info("🚨 [CAPTURE_DEBUG] FFmpeg stdout stream ended - no more audio data.")
                    logger.info(f"🔍 [CAPTURE_DEBUG] Final stats: {iteration_count} iterations, {bytes_read_total} total bytes")
                    self._is_capturing = False
                    break
                
                with self._agent_task_capture_lock:
                    if self._capture_mode == CAPTURE_MODE_AGENT_TASK:
                        self._agent_task_audio_buffer.extend(raw_audio_chunk)
                        
                        # Enhanced logging for agent-task capture mode
                        if len(self._agent_task_audio_buffer) % (TARGET_BYTES_PER_CHUNK * 10) == 0:  # Log every ~800ms worth
                            duration_captured = len(self._agent_task_audio_buffer) / (TARGET_SAMPLE_RATE * TARGET_SAMPLE_WIDTH)
                            logger.info(f"🔍 [AGENT_TASK_CAPTURE_DEBUG] Buffer size: {len(self._agent_task_audio_buffer)} bytes ({duration_captured:.2f}s)")
                        
                        # Check if agent-task capture duration has elapsed
                        # VoiceListenerService is expected to call stop_agent_task_capture_and_get_audio()
                        # This is a safety log if it runs too long.
                        if self._agent_task_capture_start_time and \
                           (time.time() - self._agent_task_capture_start_time > self._agent_task_capture_duration_seconds + 2): # 2s buffer
                            logger.warning(f"Agent-task capture mode active for over {self._agent_task_capture_duration_seconds + 2}s. "
                                           f"Ensure stop_agent_task_capture_and_get_audio() is called.")
                            # Optionally, could automatically switch back here as a failsafe
                            # self._capture_mode = CAPTURE_MODE_WAKE_WORD
                            # self._agent_task_audio_buffer.clear()
                            # logger.info("Switched back to WAKE_WORD mode due to timeout.")
                        continue # Skip wake word processing during agent-task capture

                    # If in WAKE_WORD mode, proceed as before
                    self._pcm_buffer.extend(raw_audio_chunk)

                # Process all full chunks available in the buffer for WAKE_WORD mode
                # This part should only run if not in AGENT_TASK_CAPTURE or after lock is released.
                # The lock ensures that mode checks and buffer operations are atomic.
                if self._capture_mode == CAPTURE_MODE_WAKE_WORD: # Re-check mode outside lock for pcm_buffer processing
                    while len(self._pcm_buffer) >= TARGET_BYTES_PER_CHUNK:
                        if not self._is_capturing: # Check again in case stop was called
                            break
                        
                        chunk_to_process = self._pcm_buffer[:TARGET_BYTES_PER_CHUNK]
                        self._pcm_buffer = self._pcm_buffer[TARGET_BYTES_PER_CHUNK:]

                        np_chunk = np.frombuffer(chunk_to_process, dtype=np.int16)
                        
                        if self.wake_word_detector:
                            try:
                                self.wake_word_detector.process_audio_frame(np_chunk)
                            except Exception as e:
                                logger.error(f"Error calling wake_word_detector.process_audio_frame: {e}")
                    
                    # Periodic buffer housekeeping to prevent indefinite accumulation
                    current_time = time.time()
                    if current_time - self._last_buffer_clear_time > self._buffer_clear_interval:
                        buffer_size = len(self._pcm_buffer)
                        # Only clear if buffer has accumulated beyond a few chunks (~800ms worth)
                        if buffer_size > TARGET_BYTES_PER_CHUNK * 10:
                            logger.debug(f"🧹 Periodic buffer housekeeping: clearing {buffer_size} bytes from PCM buffer")
                            self._pcm_buffer.clear()
                        self._last_buffer_clear_time = current_time
                    
                if not self._is_capturing: # If stop was called during chunk processing
                    break

        except Exception as e:
            logger.error(f"🚨 [CAPTURE_DEBUG] Exception in audio capture loop: {e}", exc_info=True)
        finally:
            logger.info("🔍 [CAPTURE_DEBUG] Audio capture loop ended.")
            logger.info(f"🔍 [CAPTURE_DEBUG] Final total bytes read: {bytes_read_total}")
            if self._ffmpeg_process:
                logger.info("Ensuring FFmpeg process is terminated.")
                if self._stderr_thread and self._stderr_thread.is_alive():
                    pass 
                try:
                    self._ffmpeg_process.terminate()
                    self._ffmpeg_process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    logger.warning("FFmpeg did not terminate in time, killing.")
                    self._ffmpeg_process.kill()
                except Exception as e:
                    logger.error(f"Error terminating FFmpeg process: {e}")
                self._ffmpeg_process = None
            self._is_capturing = False

    def start_agent_task_capture(self, duration_seconds: float = DEFAULT_AGENT_TASK_CAPTURE_DURATION_SECONDS) -> None:
        """
        Switches the capturer to agent-task capture mode.
        Audio will be buffered for the specified duration.
        """
        with self._agent_task_capture_lock:
            if not self._is_capturing:
                # Allow standalone hotkey-based agent-task capture by starting the capturer on demand
                logger.info("🎤 [VOICE_CAPTURE_DEBUG] Main capture not running; attempting standalone start for agent-task capture...")
                self.start()
                # Briefly wait for the capture thread to initialize
                start_wait_begin = time.time()
                while not self._is_capturing and (time.time() - start_wait_begin) < 1.0:
                    time.sleep(0.05)
                if not self._is_capturing:
                    logger.error("🚨 [VOICE_CAPTURE_DEBUG] Failed to start audio capturer for agent-task capture; aborting.")
                    return
                logger.info("✅ [VOICE_CAPTURE_DEBUG] Audio capturer started for standalone agent-task capture.")
            
            logger.info(f"Switching to AGENT_TASK_CAPTURE mode for {duration_seconds} seconds.")
            self._capture_mode = CAPTURE_MODE_AGENT_TASK
            self._agent_task_capture_duration_seconds = duration_seconds
            self._agent_task_audio_buffer.clear()
            
            # CRITICAL: Clear PCM buffer to prevent wake word audio contamination
            # The PCM buffer contains audio from the wake word detection that just triggered
            # this agent-task capture. If we don't clear it, when we switch back to WAKE_WORD mode,
            # this old wake word audio will be processed again, causing phantom detections.
            logger.debug(f"Clearing PCM buffer ({len(self._pcm_buffer)} bytes) to prevent audio contamination")
            self._pcm_buffer.clear()
            
            self._agent_task_capture_start_time = time.time()

    def stop_agent_task_capture_and_get_audio(self) -> Optional[bytes]:
        """
        Stops agent-task capture mode, returns the buffered audio, and resumes wake word detection.
        """
        with self._agent_task_capture_lock:
            logger.info(f"🔍 [AUDIO_RETRIEVAL_DEBUG] stop_agent_task_capture_and_get_audio called")
            logger.info(f"🔍 [AUDIO_RETRIEVAL_DEBUG] Current capture mode: {self._capture_mode}")
            logger.info(f"🔍 [AUDIO_RETRIEVAL_DEBUG] AgentTask audio buffer size: {len(self._agent_task_audio_buffer)} bytes")
            
            if self._capture_mode != CAPTURE_MODE_AGENT_TASK:
                logger.warning("🚨 [AUDIO_RETRIEVAL_DEBUG] Not in agent-task capture mode. Cannot stop agent-task capture.")
                # Clear buffer just in case, though it should be empty if not in mode
                self._agent_task_audio_buffer.clear()
                return None

            logger.info("🔍 [AUDIO_RETRIEVAL_DEBUG] Stopping AGENT_TASK_CAPTURE mode and retrieving audio.")
            captured_audio = bytes(self._agent_task_audio_buffer) # Make a copy
            
            # Calculate duration for logging
            if len(captured_audio) > 0:
                duration_seconds = len(captured_audio) / (TARGET_SAMPLE_RATE * TARGET_SAMPLE_WIDTH)
                logger.info(f"🔍 [AUDIO_RETRIEVAL_DEBUG] Retrieved {len(captured_audio)} bytes ({duration_seconds:.2f}s duration)")
            else:
                logger.warning(f"🚨 [AUDIO_RETRIEVAL_DEBUG] ZERO BYTES retrieved from agent-task capture buffer!")
                
            # Log capture session details
            if self._agent_task_capture_start_time:
                session_duration = time.time() - self._agent_task_capture_start_time
                logger.info(f"🔍 [AUDIO_RETRIEVAL_DEBUG] Capture session lasted {session_duration:.2f}s")
            
            self._agent_task_audio_buffer.clear()
            self._capture_mode = CAPTURE_MODE_WAKE_WORD # Switch back to wake word detection
            
            # ADDITIONAL SAFETY: Clear PCM buffer when resuming wake word detection
            # This ensures we start with a completely clean slate for wake word detection
            # and don't process any residual agent-task audio that might trigger false detections
            logger.debug(f"Clearing PCM buffer ({len(self._pcm_buffer)} bytes) when resuming wake word detection")
            self._pcm_buffer.clear()
            
            self._agent_task_capture_start_time = None
            logger.info("🔍 [AUDIO_RETRIEVAL_DEBUG] Switched back to WAKE_WORD mode. AgentTask audio retrieved.")
            
            # Final validation
            if len(captured_audio) == 0:
                logger.error("🚨 [AUDIO_RETRIEVAL_DEBUG] CRITICAL: Returning empty audio buffer - agent_task will fail!")
            
            return captured_audio

    def get_current_capture_mode(self) -> str:
        """Returns the current capture mode ('WAKE_WORD' or 'AGENT_TASK_CAPTURE')."""
        with self._agent_task_capture_lock:
            return self._capture_mode

    def clear_all_buffers(self):
        """Clear all audio buffers to prevent phantom detections on restart."""
        with self._agent_task_capture_lock:
            pcm_size = len(self._pcm_buffer)
            agent_task_size = len(self._agent_task_audio_buffer)
            
            self._pcm_buffer.clear()
            self._agent_task_audio_buffer.clear()
            
            if pcm_size > 0 or agent_task_size > 0:
                logger.info(f"🧹 Cleared all audio buffers - PCM: {pcm_size} bytes, AgentTask: {agent_task_size} bytes")

    def start(self):
        """Starts the audio capture process in a new thread."""
        if self._is_capturing:
            logger.info("Audio capture is already running.")
            return

        try:
            self._start_ffmpeg_process() # This might raise an exception
            if not self._ffmpeg_process:
                 logger.error("FFmpeg process failed to start. Cannot start capture thread.")
                 return
        except Exception as e:
            logger.error(f"Cannot start audio capture due to FFmpeg initialization failure: {e}")
            return

        self._is_capturing = True
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.name = "WakeWordAudioCaptureThread"
        self._capture_thread.start()
        logger.info("WakeWordAudioCapturer started.")

    def stop(self):
        """Stops the audio capture process."""
        if not self._is_capturing and not (self._capture_thread and self._capture_thread.is_alive()):
            logger.info("Audio capture is not running.")
            # Also ensure ffmpeg is cleaned up if it exists but thread is dead
            if self._ffmpeg_process:
                logger.warning("Capture not running, but FFmpeg process exists. Attempting cleanup.")
                if self._stderr_thread and self._stderr_thread.is_alive():
                    # FFmpeg process termination will close its stderr, letting the thread exit
                    pass
                try:
                    self._ffmpeg_process.terminate()
                    self._ffmpeg_process.wait(timeout=1.0)
                except:
                    self._ffmpeg_process.kill()
                self._ffmpeg_process = None
            return

        logger.info("Stopping audio capture...")
        self._is_capturing = False # Signal the loop to stop
        
        # Close FFmpeg's stdout to help unblock the read in the thread
        if self._ffmpeg_process and self._ffmpeg_process.stdout:
            try:
                self._ffmpeg_process.stdout.close()
                logger.info("FFmpeg stdout closed.")
            except Exception as e:
                logger.warning(f"Error closing FFmpeg stdout: {e}")

        if self._capture_thread and self._capture_thread.is_alive():
            logger.info("Waiting for capture thread to join...")
            self._capture_thread.join(timeout=5.0) # Wait for the thread to finish
            if self._capture_thread.is_alive():
                logger.warning("Capture thread did not join in time.")
        
        if self._stderr_thread and self._stderr_thread.is_alive():
            logger.info("Waiting for stderr logging thread to join...")
            # The stderr thread should exit when ffmpeg's stderr pipe is closed by ffmpeg terminating.
            # Giving it a short timeout here just in case.
            self._stderr_thread.join(timeout=2.0)
            if self._stderr_thread.is_alive():
                logger.warning("Stderr logging thread did not join in time.")
            self._stderr_thread = None # Clear the thread reference
        
        # FFmpeg process termination is handled in the _capture_loop finally block
        # but as a safeguard if the loop exited unexpectedly:
        if self._ffmpeg_process:
            logger.warning("Capture loop stopped, but FFmpeg process might still exist. Ensuring termination.")
            if self._stderr_thread and self._stderr_thread.is_alive():
                # FFmpeg process termination will close its stderr, letting the thread exit
                pass
            try:
                self._ffmpeg_process.terminate()
                self._ffmpeg_process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                 self._ffmpeg_process.kill()
            except Exception:
                 pass # Already logged if it failed in loop
            self._ffmpeg_process = None

        self._capture_thread = None
        self._stderr_thread = None # Also clear here
        self._pcm_buffer = bytearray() # Clear buffer
        logger.info("WakeWordAudioCapturer stopped.")

# Example Usage (conceptual, for testing this file directly)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(threadName)s - %(message)s')
    logger.info("Running WakeWordAudioCapturer example...")

    # Mock WakeWordDetector for this example
    class MockWakeWordDetector:
        def __init__(self):
            self.detected_count = 0
        def process_audio_frame(self, frame):
            # Simulate some processing and occasionally "detect" a wake word
            # logger.debug(f"MockDetector processing frame of shape {frame.shape}, dtype {frame.dtype}, sum {np.sum(frame)}")
            if np.sum(frame) % 100 == 0: # Arbitrary condition for mock detection
                self.detected_count += 1
                logger.info(f"MOCK WAKE WORD DETECTED! (Count: {self.detected_count})")
        def start_listening(self, audio_input_callable):
            pass # Not used in this direction
        def stop_listening(self):
            pass

    mock_detector = MockWakeWordDetector()
    capturer = WakeWordAudioCapturer(wake_word_detector=mock_detector)

    print("Starting audio capture for 15 seconds...")
    capturer.start()
    
    try:
        time.sleep(15) # Let it run for a bit
    except KeyboardInterrupt:
        print("User interrupted.")
    finally:
        print("Stopping audio capture...")
        capturer.stop()
        print("Example finished.") 