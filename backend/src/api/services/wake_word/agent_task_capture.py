import logging
import asyncio
from typing import Optional, Dict, Any
import numpy as np
import uuid
import time
import tempfile
import soundfile as sf
import os

# Import streaming processor for intelligent capture termination
from api.services.agent_task_streaming import (
    create_agent_task_streaming_session,
    get_session_complete_audio,
    cleanup_streaming_session,
    handle_agent_task_streaming_audio
)

logger = logging.getLogger(__name__)

class VoiceListenerAgentTaskCapture:
    def __init__(self, audio_capturer, transcription_service):
        """
        Initialize the agent-task capture service.
        
        Args:
            audio_capturer: The audio capturer instance
            transcription_service: The transcription service instance
        """
        self.audio_capturer = audio_capturer
        self.transcription_service = transcription_service
        self._agent_task_cancelled = False
        self._active_transcription_task: Optional[asyncio.Task] = None

    def set_agent_task_cancelled(self, cancelled: bool):
        """Set the agent-task cancellation flag."""
        self._agent_task_cancelled = cancelled

    async def _capture_agent_task(self, hotkey_mode: bool = False) -> Optional[str]:
        """
        Capture the agent_task that follows the wake word using intelligent word-based termination.
        
        IMPORTANT: Uses streaming processor for capture termination detection only.
        Final agent-task processing still uses complete recorded audio via batch transcription.
        
        Args:
            hotkey_mode: If True, uses longer timeout for hotkey-initiated agent tasks
        
        Returns:
            Transcribed agent_task or None if capture failed
        """
        try:
            logger.info("🎤 [VOICE_CAPTURE_DEBUG] Starting agent_task capture with intelligent termination...")
            if not self.audio_capturer:
                logger.error("🎤 [VOICE_CAPTURE_DEBUG] Audio capturer not available for agent-task capture.")
                return None

            # Hotkey-mode bypass: let the client own recording window (press-to-start/press-to-stop)
            # Do NOT start streaming termination detection or backend audio capture here.
            # Final processing will come from the client via /agent_task/process_audio.
            if hotkey_mode:
                logger.info("🎤 [VOICE_CAPTURE_DEBUG] Hotkey mode enabled - bypassing streaming termination and backend capture; client will submit final audio")
                # Return placeholder immediately so the pipeline advances without waiting on backend listener
                return "ffmpeg_complete_awaiting_swift_transcription"

            # Create streaming session for intelligent capture termination
            session_id = str(uuid.uuid4())
            logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] Creating streaming session for intelligent capture: {session_id}")
            
            try:
                # Get WebSocket connection for real-time feedback
                from api.services.websocket_connection_manager import active_connections
                logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] Active connections count: {len(active_connections) if active_connections else 0}")
                websocket = next(iter(active_connections)) if active_connections else None
                
                if not websocket:
                    logger.warning("🎤 [VOICE_CAPTURE_DEBUG] No active WebSocket connection for streaming feedback - using fallback timer method")
                    return await self._capture_agent_task_fallback()
                    
                logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] Found WebSocket connection: {websocket}")
                
                # Create streaming processor for word-based termination detection
                logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] About to create streaming processor...")
                
                # Use different silence threshold based on mode
                silence_threshold = 30.0 if hotkey_mode else 2.0  # 30 seconds for hotkey, 2 seconds for wake word
                logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] Using silence threshold: {silence_threshold}s (hotkey_mode: {hotkey_mode})")
                
                streaming_processor = await create_agent_task_streaming_session(
                    websocket=websocket,
                    session_id=session_id,
                    silence_threshold=silence_threshold
                )
                
                logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] Streaming processor created successfully: {streaming_processor}")
                
            except Exception as e:
                logger.error(f"🎤 [VOICE_CAPTURE_DEBUG] Error creating streaming session: {e} - falling back to timer method")
                return await self._capture_agent_task_fallback()

            # Start agent-task capture mode in audio capturer
            max_capture_duration = 120.0  # Safety timeout - extended for detailed requests (2 minutes)
            logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] About to start audio capturer in agent-task mode...")
            self.audio_capturer.start_agent_task_capture(max_capture_duration)
            logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] Audio capturer started in agent-task mode (max {max_capture_duration}s)")

            # Wake word detection is already paused from _handle_wake_word_detected
            logger.debug("Wake word detection already paused - proceeding with intelligent audio capture")

            try:
                # Intelligent capture loop with streaming termination detection
                capture_complete = False
                check_interval = 0.1
                audio_chunk_buffer = bytearray()
                import time  # Ensure time module is available in local scope
                last_chunk_time = time.time()
                initial_wait_timeout = 10.0  # Wait up to 10 seconds for first audio
                first_audio_received = False
                loop_start_time = time.time()
                capture_start_time = time.time()  # Track total capture duration
                last_audio_time = capture_start_time  # Track heartbeat for audio reception
                max_no_audio_timeout = 30.0  # End capture if no audio received for 30 seconds
                
                logger.info("🎤 [VOICE_CAPTURE_DEBUG] Starting intelligent capture monitoring loop...")
                
                while not capture_complete:
                    current_time = time.time()
                    
                    # TERMINATION CHECK 1: Max capture duration exceeded
                    if current_time - capture_start_time > max_capture_duration:
                        logger.warning(f"🎤 [VOICE_CAPTURE_DEBUG] Max capture duration ({max_capture_duration}s) exceeded - ending capture")
                        capture_complete = True
                        break
                    
                    # TERMINATION CHECK 2: No audio heartbeat timeout (prevents infinite loops)
                    if first_audio_received and current_time - last_audio_time > max_no_audio_timeout:
                        logger.warning(f"🎤 [VOICE_CAPTURE_DEBUG] No audio received for {max_no_audio_timeout}s - ending capture")
                        capture_complete = True
                        break
                    
                    # TERMINATION CHECK 3: Streaming processor signaled completion
                    if first_audio_received and streaming_processor.is_capture_complete():
                        completion_reason = streaming_processor.get_completion_reason()
                        logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] Streaming processor signaled completion: {completion_reason}")
                        capture_complete = True
                        break
                    # Check for cancellation
                    if self._agent_task_cancelled:
                        logger.info("🎤 [VOICE_CAPTURE_DEBUG] Agent-task processing cancelled during intelligent capture")
                        self.audio_capturer.stop_agent_task_capture_and_get_audio()  # Discard the audio
                        return None
                    
                    # Get recent audio chunks from the audio capturer for streaming analysis
                    audio_processed_this_iteration = False
                    
                    # Check if we have new audio data to process
                    if hasattr(self.audio_capturer, '_agent_task_audio_buffer'):
                        with self.audio_capturer._agent_task_capture_lock:
                            current_buffer_size = len(self.audio_capturer._agent_task_audio_buffer)
                            logger.debug(f"🎤 [VOICE_CAPTURE_DEBUG] Buffer check - current: {current_buffer_size}, processed: {len(audio_chunk_buffer)}")
                            
                            # Process new audio chunks (if any)
                            if current_buffer_size > len(audio_chunk_buffer):
                                # Extract new audio data
                                new_audio_bytes = bytes(self.audio_capturer._agent_task_audio_buffer[len(audio_chunk_buffer):])
                                audio_chunk_buffer.extend(new_audio_bytes)
                                logger.debug(f"🎤 [VOICE_CAPTURE_DEBUG] Found {len(new_audio_bytes)} new audio bytes")
                                
                                # Mark that we've received first audio
                                if not first_audio_received:
                                    first_audio_received = True
                                    logger.info("🎤 [VOICE_CAPTURE_DEBUG] First audio chunk received - starting intelligent processing")
                                
                                # Update heartbeat - we received audio
                                last_audio_time = current_time
                                
                                # Send new audio to streaming processor for word detection
                                if len(new_audio_bytes) >= 512:  # Lower threshold for more responsive processing
                                    try:
                                        logger.debug(f"🎤 [VOICE_CAPTURE_DEBUG] Sending {len(new_audio_bytes)} bytes to streaming processor...")
                                        should_continue = await handle_agent_task_streaming_audio(
                                            websocket=websocket,
                                            session_id=session_id, 
                                            audio_data=new_audio_bytes
                                        )
                                        last_chunk_time = current_time
                                        audio_processed_this_iteration = True
                                        logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] Sent {len(new_audio_bytes)} bytes to streaming processor, continue: {should_continue}")
                                        
                                        # Check if streaming processor detected completion
                                        if not should_continue:
                                            logger.info("🎤 [VOICE_CAPTURE_DEBUG] Streaming processor indicated capture completion")
                                            capture_complete = True
                                            break
                                            
                                    except Exception as e:
                                        logger.error(f"🎤 [VOICE_CAPTURE_DEBUG] Error processing streaming audio chunk: {e}")
                                else:
                                    logger.debug(f"🎤 [VOICE_CAPTURE_DEBUG] Chunk too small ({len(new_audio_bytes)} bytes), waiting for more audio")
                            else:
                                logger.debug(f"🎤 [VOICE_CAPTURE_DEBUG] No new audio data available")
                    
                    # CRITICAL: Always call the streaming processor to check for silence timeouts,
                    # even when there's no new audio. This is essential for word-based silence detection.
                    if first_audio_received and not audio_processed_this_iteration:
                        try:
                            logger.debug("🎤 [VOICE_CAPTURE_DEBUG] No new audio - calling streaming processor to check for silence timeout...")
                            # Call streaming processor with empty audio to trigger silence detection check
                            should_continue = await handle_agent_task_streaming_audio(
                                websocket=websocket,
                                session_id=session_id,
                                audio_data=b''  # Empty audio - just trigger the silence detection check
                            )
                            
                            # Check if streaming processor detected completion via silence timeout
                            if not should_continue:
                                logger.info("🎤 [VOICE_CAPTURE_DEBUG] Streaming processor detected silence timeout - ending capture")
                                capture_complete = True
                                # Don't break here, continue to the capture_complete check below
                                
                        except Exception as e:
                            logger.error(f"🎤 [VOICE_CAPTURE_DEBUG] Error checking streaming processor for silence timeout: {e}")
                    
                    # Check if we're waiting too long for first audio
                    if not first_audio_received:
                        elapsed = current_time - loop_start_time
                        if elapsed > initial_wait_timeout:
                            logger.warning(f"🎤 [VOICE_CAPTURE_DEBUG] No audio received after {elapsed:.1f}s - ending capture")
                            capture_complete = True
                            break
                        elif elapsed > 2.0:  # Log progress after 2 seconds
                            logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] Still waiting for first audio chunk... ({elapsed:.1f}s elapsed)")
                    
                    await asyncio.sleep(check_interval)
                    
                    # CRITICAL: Check cancellation flag again after sleep
                    if self._agent_task_cancelled:
                        logger.info("🎤 [VOICE_CAPTURE_DEBUG] Agent task cancelled during intelligent capture loop")
                        capture_complete = True
                        break
                    
                    # Safety check - if no audio for too long, something may be wrong
                    if first_audio_received and current_time - last_chunk_time > 5.0:
                        logger.warning("🎤 [VOICE_CAPTURE_DEBUG] No new audio chunks received for 5 seconds during intelligent capture")
                        # Continue anyway - the regular capturer might still be working
                
                # Get the complete recorded audio from the regular audio capturer
                # This is the SAME audio that was being recorded before - no quality loss
                agent_task_audio_s16le_bytes = self.audio_capturer.stop_agent_task_capture_and_get_audio()
                
                if not agent_task_audio_s16le_bytes:
                    logger.warning("No audio data retrieved from agent-task capture.")
                    return None

                logger.info(f"Retrieved {len(agent_task_audio_s16le_bytes)} bytes of s16le agent-task audio via intelligent capture.")
                
                # CRITICAL: Verify that streaming processor also has complete audio
                # This is redundant but ensures we have proper audio preservation
                streaming_audio = get_session_complete_audio(session_id)
                if streaming_audio is not None:
                    streaming_duration = len(streaming_audio) / 16000  # 16kHz sample rate
                    regular_duration = len(agent_task_audio_s16le_bytes) / (16000 * 2)  # 16-bit samples
                    logger.info(f"Audio validation - Regular: {regular_duration:.2f}s, Streaming: {streaming_duration:.2f}s")
                
            finally:
                # Always cleanup streaming session to prevent runaway processing
                try:
                    cleanup_streaming_session(session_id)
                    logger.info(f"🎤 [VOICE_CAPTURE_DEBUG] Cleaned up streaming session: {session_id}")
                except Exception as e:
                    logger.warning(f"🎤 [VOICE_CAPTURE_DEBUG] Error cleaning up streaming session: {e}")

            # Check for cancellation before audio processing
            if self._agent_task_cancelled:
                logger.info("Agent-task processing cancelled before audio processing")
                return None

            # Convert s16le bytes to temporary WAV file for proven file-based transcription
            audio_s16le_np = np.frombuffer(agent_task_audio_s16le_bytes, dtype=np.int16)

            # Save as temporary WAV file using same format as working transcription/AssistantSession suggestions
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                temp_wav_path = temp_file.name

            # Write audio as 16kHz mono WAV file (matches transcription service expectations)
            sf.write(temp_wav_path, audio_s16le_np, 16000, subtype='PCM_16', format='WAV')
            logger.info(f"Saved agent_task audio to temporary file: {temp_wav_path} ({len(agent_task_audio_s16le_bytes)} bytes -> {os.path.getsize(temp_wav_path)} WAV bytes)")

            # Read the WAV file back as bytes for transcription service
            with open(temp_wav_path, 'rb') as f:
                audio_wav_file_bytes = f.read()
            logger.info(f"Read WAV file back as {len(audio_wav_file_bytes)} bytes for transcription service")

            # Check for cancellation before transcription
            if self._agent_task_cancelled:
                logger.info("Agent-task processing cancelled before transcription")
                return None

            if not self.transcription_service:
                logger.error("Transcription service not available.")
                return None

            # DUAL-TRACK ARCHITECTURE NOTE:
            # The Python-side `transcription_service` is intentionally NOT awaited here.
            # Final transcription is owned by the Swift client (which POSTs the captured
            # WAV to /api/v1/agent-tasks/audio and the route uses the user's configured
            # API or local model for batch transcription). The streaming Tiny model used
            # for capture-end detection lives in AgentTaskStreamingManager and has already
            # done its job by this point.
            #
            # Previously this block waited up to 30 s for the local backend transcription
            # model to load before returning the placeholder, which kept wake-word
            # detection paused for ~30 s after the very first capture per app session
            # even though the loaded model was never used in this code path.

            # Final cancellation check before handing off to Swift transcription
            if self._agent_task_cancelled:
                logger.info("Agent-task processing cancelled just before Swift transcription handoff")
                return None

            logger.info("FFmpeg track complete - Swift will handle final transcription")
            
            # DUAL-TRACK ARCHITECTURE:
            # FFmpeg job is DONE - it provided:
            # 1. Real-time streaming transcription for UI feedback
            # 2. Agent-task end detection 
            # 
            # Swift track will handle final batch transcription via /agent_task/process_audio
            # 
            # Return a placeholder - the real transcription comes from Swift
            return "ffmpeg_complete_awaiting_swift_transcription"
                
        except Exception as e:
            logger.error(f"Error during agent_task audio processing or transcription: {e}", exc_info=True)
            return None

    async def _capture_agent_task_fallback(self) -> Optional[str]:
        """
        Fallback agent_task capture using the original timer-based method.
        Used when streaming processor is not available or fails.
        
        Returns:
            Transcribed agent_task or None if capture failed
        """
        try:
            logger.info("Using fallback timer-based agent_task capture...")
            
            # Start agent-task capture mode in audio capturer (original method)
            capture_duration = getattr(self.audio_capturer, '_agent_task_capture_duration_seconds', 12.0)
            self.audio_capturer.start_agent_task_capture(capture_duration)
            logger.info(f"Started fallback agent-task capture mode for {capture_duration}s")

            # Wait for the agent-task audio capture duration with cancellation checks
            capture_wait_time = capture_duration + 0.5
            logger.debug(f"Waiting {capture_wait_time:.1f}s for fallback agent-task audio capture...")
            
            # Check for cancellation every 0.1 seconds
            elapsed_time = 0.0
            check_interval = 0.1
            while elapsed_time < capture_wait_time:
                if self._agent_task_cancelled:
                    logger.info("Agent-task processing cancelled during fallback audio capture")
                    try:
                        self.audio_capturer.stop_agent_task_capture_and_get_audio()  # Discard the audio
                    except Exception as e:
                        logger.debug(f"Error stopping fallback audio capture early: {e}")
                    return None
                
                await asyncio.sleep(check_interval)
                elapsed_time += check_interval

            # Get the recorded audio
            agent_task_audio_s16le_bytes = self.audio_capturer.stop_agent_task_capture_and_get_audio()

            # CRITICAL: Check for cancellation immediately after audio retrieval
            if self._agent_task_cancelled:
                logger.info("Agent-task processing cancelled immediately after fallback audio retrieval")
                return None

            if not agent_task_audio_s16le_bytes:
                logger.warning("No audio data retrieved from fallback agent-task capture.")
                return None

            logger.info(f"Retrieved {len(agent_task_audio_s16le_bytes)} bytes of s16le agent-task audio via fallback.")

            # Check for cancellation before audio processing
            if self._agent_task_cancelled:
                logger.info("Agent-task processing cancelled before fallback audio processing")
                return None

            # Convert s16le bytes to temporary WAV file for proven file-based transcription (same as main method)
            audio_s16le_np = np.frombuffer(agent_task_audio_s16le_bytes, dtype=np.int16)

            # Save as temporary WAV file using same format as working transcription/AssistantSession suggestions
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                temp_wav_path = temp_file.name

            # Write audio as 16kHz mono WAV file (matches transcription service expectations)
            sf.write(temp_wav_path, audio_s16le_np, 16000, subtype='PCM_16', format='WAV')
            logger.info(f"Saved fallback agent_task audio to temporary file: {temp_wav_path} ({len(agent_task_audio_s16le_bytes)} bytes -> {os.path.getsize(temp_wav_path)} WAV bytes)")

            # Read the WAV file back as bytes for transcription service
            with open(temp_wav_path, 'rb') as f:
                audio_wav_file_bytes = f.read()
            logger.info(f"Read fallback WAV file back as {len(audio_wav_file_bytes)} bytes for transcription service")

            # Process transcription (same logic as main method)
            if not self.transcription_service:
                logger.error("Transcription service not available for fallback.")
                return None

            if not self.transcription_service.is_model_loaded():
                logger.info("Transcription model not yet loaded for fallback, waiting...")
                wait_interval = 0.5
                elapsed = 0.0
                max_wait_time = 30.0
                
                while not self.transcription_service.is_model_loaded() and elapsed < max_wait_time:
                    if self._agent_task_cancelled:
                        logger.info("Agent task cancelled while waiting for model loading in fallback")
                        return None
                        
                    await asyncio.sleep(wait_interval)
                    elapsed += wait_interval
                
                if not self.transcription_service.is_model_loaded():
                    logger.warning("Fallback: Loading model synchronously as final attempt...")
                    try:
                        self.transcription_service.load_model()
                        logger.info("Transcription model loaded successfully (fallback).")
                    except Exception as e:
                        logger.error(f"Error loading transcription model (fallback): {e}", exc_info=True)
                        return None
            
            # Final cancellation check
            if self._agent_task_cancelled:
                logger.info("Agent-task processing cancelled just before fallback transcription")
                return None
            
            # CRITICAL: Final cancellation check before expensive transcription operation
            if self._agent_task_cancelled:
                logger.info("Agent-task processing cancelled just before fallback transcription - skipping expensive operation")
                return None
            
            logger.info("Transcribing fallback agent-task audio...")
            
            logger.info("FFmpeg fallback track complete - Swift will handle final transcription")
            
            # DUAL-TRACK ARCHITECTURE (FALLBACK):
            # FFmpeg job is DONE - Swift handles final transcription
            return "ffmpeg_fallback_complete_awaiting_swift_transcription"
                
        except Exception as e:
            logger.error(f"Error during fallback agent_task processing: {e}", exc_info=True)
            return None

# Import the required functions from the streaming module
from api.services.agent_task_streaming import (
    create_agent_task_streaming_session,
    get_session_complete_audio,
    cleanup_streaming_session,
    handle_agent_task_streaming_audio
) 