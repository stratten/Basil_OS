"""
AgentTask Streaming WebSocket Handler

CRITICAL ARCHITECTURAL NOTE:
==========================
This streaming processor is used ONLY for intelligent capture termination.
- Streaming transcription determines WHEN to stop recording (word-based silence detection)
- Final agent-task processing uses the COMPLETE recorded audio via existing batch transcription
- NO streaming content is used for building the actual agent_task request

This provides environment-independent capture termination while maintaining
the existing high-quality batch transcription pipeline for final processing.
"""

import asyncio
import time
import logging
import numpy as np
from typing import Optional, List, Dict, Any, Tuple
from fastapi import WebSocket

# UPDATED: Import from whisper_live_core (upstream) instead of old whisper_live
# whisper_streaming was renamed to local_agreement in upstream
from ...services.whisper_live_core.local_agreement.online_asr import OnlineASRProcessor
from ...services.whisper_live_core.timed_objects import ASRToken
from ...services.whisper_live_core.core import TranscriptionEngine  # Was WhisperLiveKit
from ...services.live_transcription.config_mapper import map_basil_config_to_upstream
from ...core.models.preferences import Preferences

logger = logging.getLogger(__name__)


async def _broadcast_agent_task_capture_complete(message_data: Dict[str, Any]) -> None:
    """Broadcast capture completion so the Swift capture owner always sees it."""
    try:
        from ...services.websocket_connection_manager import active_connections

        successful_sends = 0
        connection_count = len(active_connections)
        for connection in list(active_connections):
            try:
                await connection.send_json(message_data)
                successful_sends += 1
            except Exception as e:
                logger.error(f"Error broadcasting agent_task_capture_complete to connection: {e}")

        logger.info(
            "Broadcasted agent_task_capture_complete to "
            f"{successful_sends}/{connection_count} websocket clients"
        )
    except Exception as e:
        logger.error(f"Error broadcasting agent_task_capture_complete: {e}")


class AgentTaskStreamProcessor(OnlineASRProcessor):
    """
    Extends OnlineASRProcessor for agent_task capture termination detection.
    
    IMPORTANT: This processor is used ONLY for determining when to stop recording.
    The streaming tokens are NOT used for final agent-task processing - that uses
    the complete recorded audio via the existing batch transcription pipeline.
    """
    
    def __init__(self, websocket: WebSocket, silence_threshold_seconds: float = 2.0, **kwargs):
        """
        Initialize the streaming processor for capture termination detection.
        
        Args:
            websocket: WebSocket connection for real-time feedback
            silence_threshold_seconds: Seconds of word silence before ending capture
            **kwargs: Passed to parent OnlineASRProcessor
        """
        super().__init__(**kwargs)
        
        self.websocket = websocket
        self.silence_threshold = silence_threshold_seconds
        self.minimum_speech_duration = 0.5  # Minimum speech before silence detection starts
        
        # Word-based silence detection state
        self.last_word_time: Optional[float] = None
        self.speech_detected = False
        self.silence_start_time: Optional[float] = None
        self.capture_start_time = time.time()
        self.capture_timeout = 120.0  # Maximum capture duration (safety) - matches intelligent capture timeout
        
        # Audio-level silence detection state (fallback)
        self.audio_silence_threshold = 0.02  # RMS threshold for audio silence
        self.audio_silence_duration = 0.0
        self.last_audio_time: Optional[float] = None
        self.audio_silence_start_time: Optional[float] = None
        self.recent_audio_levels: List[float] = []  # Track recent RMS levels
        self.latest_average_rms = 0.0
        self.active_audio_grace_after_word_silence = 5.0
        self.recent_committed_words: List[str] = []
        
        # Complete audio buffer preservation for final batch transcription
        # This is the ONLY audio that matters for the final agent task
        self.complete_audio_buffer: List[np.ndarray] = []
        
        # Capture completion state
        self.capture_completed = False
        self.completion_reason: Optional[str] = None
        
        logger.info(f"AgentTaskStreamProcessor initialized - silence_threshold: {silence_threshold_seconds}s, audio_silence_threshold: {self.audio_silence_threshold}")
    
    def insert_audio_chunk(self, audio: np.ndarray):
        """
        Insert audio chunk for both streaming detection AND complete audio preservation.
        
        Args:
            audio: Audio chunk to process
        """
        # CRITICAL: Always preserve complete audio for final batch transcription
        self.complete_audio_buffer.append(audio.copy())
        
        # Calculate RMS level for audio-based silence detection
        if len(audio) > 0:
            rms_level = np.sqrt(np.mean(audio.astype(np.float64) ** 2))
            self.recent_audio_levels.append(rms_level)
            
            # Keep only last 5 audio chunks for RMS averaging
            if len(self.recent_audio_levels) > 5:
                self.recent_audio_levels.pop(0)
                
            current_time = time.time()
            
            # Update audio-level silence detection
            avg_rms = np.mean(self.recent_audio_levels)
            self.latest_average_rms = float(avg_rms)
            if avg_rms > self.audio_silence_threshold:
                # Audio detected - reset silence timer
                self.last_audio_time = current_time
                self.audio_silence_start_time = None
                self.audio_silence_duration = 0.0
                logger.debug(f"Audio activity detected - RMS: {avg_rms:.4f}")
            elif self.last_audio_time is not None:
                # Check if we've had sufficient audio activity before starting silence detection
                audio_activity_duration = current_time - self.capture_start_time
                if audio_activity_duration >= self.minimum_speech_duration:
                    if self.audio_silence_start_time is None:
                        # Start audio silence timer
                        self.audio_silence_start_time = current_time
                        logger.debug(f"Started audio silence detection - RMS: {avg_rms:.4f}")
                    else:
                        # Update silence duration
                        self.audio_silence_duration = current_time - self.audio_silence_start_time
        
        # Also process for streaming word detection (termination only)
        super().insert_audio_chunk(audio)
    
    async def process_iter_with_termination_detection(self) -> Optional[List[ASRToken]]:
        """
        Process audio iteration with word-based AND audio-level termination detection.
        
        Returns:
            List of committed tokens (for UI feedback only - NOT final processing)
        """
        if self.capture_completed:
            return []
        
        current_time = time.time()
        
        # Safety timeout check
        if current_time - self.capture_start_time > self.capture_timeout:
            logger.warning(f"AgentTask capture timeout reached ({self.capture_timeout}s)")
            await self._end_capture("timeout")
            return []
        
        # Check audio-level silence detection (fallback mechanism only)
        if (self.audio_silence_duration >= self.silence_threshold and 
            self.last_audio_time is not None and
            not self.speech_detected):  # Only use audio fallback if no speech detected yet
            logger.info(f"Audio-level silence detected ({self.audio_silence_duration:.1f}s) - ending capture")
            await self._end_capture("audio_silence_detected")
            return []
        
        # Process streaming transcription for word detection
        try:
            committed_tokens, _ = self._process_streaming_iteration()
        except Exception as e:
            logger.error(f"Error in streaming transcription processing: {e}")
            committed_tokens = []
        
        # Handle word-based silence detection (primary mechanism)
        if committed_tokens:
            # New words detected - reset silence detection
            self.last_word_time = current_time
            self.speech_detected = True
            self.silence_start_time = None
            committed_words = [token.text for token in committed_tokens]
            self.recent_committed_words = (self.recent_committed_words + committed_words)[-10:]
            
            logger.debug(f"Words detected: {committed_words}")
            
            # Send word detection event for UI feedback
            await self._emit_word_detection_event(committed_tokens)
            
        elif self.speech_detected and self.last_word_time:
            # Check if we have sufficient speech duration before starting silence detection
            speech_duration = current_time - self.capture_start_time
            if speech_duration < self.minimum_speech_duration:
                return committed_tokens

            # Handle buffer management separately from word silence detection
            audio_buffer_duration = len(self.audio_buffer) / self.SAMPLING_RATE if hasattr(self, 'audio_buffer') else 0
            max_streaming_buffer = 2.0  # Maximum streaming buffer duration (seconds)

            # Clear excessive buffer to prevent processing lag (independent of silence detection)
            if audio_buffer_duration > max_streaming_buffer:
                # Clear most of the buffer, keeping only recent audio for termination detection
                keep_samples = int(0.3 * self.SAMPLING_RATE)  # Keep 0.3s of recent audio
                if len(self.audio_buffer) > keep_samples:
                    logger.info(f"Clearing excessive streaming buffer ({audio_buffer_duration:.2f}s -> 0.3s) - complete audio preserved separately")
                    self.audio_buffer = self.audio_buffer[-keep_samples:]
                    # Update buffer time offset to maintain correct timing
                    self.buffer_time_offset += audio_buffer_duration - 0.3

            # Dual-signal silence detection: missing streaming tokens are not
            # enough to stop capture while microphone audio remains active.
            time_since_last_word = current_time - self.last_word_time
            # Emit silence progress for UI feedback
            await self._emit_silence_progress_event(time_since_last_word)
            if time_since_last_word >= self.silence_threshold:
                audio_is_quiet_enough = (
                    self.audio_silence_duration >= self.silence_threshold
                    and self.latest_average_rms <= self.audio_silence_threshold
                )
                active_audio_grace_elapsed = (
                    time_since_last_word
                    >= self.silence_threshold + self.active_audio_grace_after_word_silence
                )
                if audio_is_quiet_enough:
                    await self._end_capture("word_silence_detected")
                elif active_audio_grace_elapsed:
                    await self._end_capture("word_silence_with_active_audio_grace_elapsed")
                else:
                    logger.info(
                        "Token silence threshold reached, but audio is still active; continuing capture "
                        f"(time_since_last_word={time_since_last_word:.1f}s, "
                        f"audio_silence_duration={self.audio_silence_duration:.1f}s, "
                        f"latest_average_rms={self.latest_average_rms:.4f}, "
                        f"audio_threshold={self.audio_silence_threshold:.4f})"
                    )

        return committed_tokens

    def _log_capture_termination_decision(self, reason: str, time_since_last_word: Optional[float] = None) -> None:
        """Log the audio/token state that justified automatic capture completion."""
        recent_audio = [float(level) for level in self.recent_audio_levels]
        logger.info(
            "AgentTask capture termination decision: "
            f"reason={reason}, time_since_last_word={time_since_last_word}, "
            f"audio_silence_duration={self.audio_silence_duration:.2f}, latest_average_rms={self.latest_average_rms:.4f}, "
            f"audio_silence_threshold={self.audio_silence_threshold:.4f}, recent_audio_levels={recent_audio}, "
            f"recent_committed_words={self.recent_committed_words}, speech_detected={self.speech_detected}"
        )

    def _process_streaming_iteration(self) -> Tuple[List[ASRToken], float]:
        """
        Run one streaming transcription iteration and normalize the upstream return.

        LocalAgreement returns (committed_tokens, processed_upto). Older wrappers
        returned only committed_tokens, so keep accepting both shapes here.
        """
        process_result = self.process_iter()
        if isinstance(process_result, tuple):
            committed_tokens, processed_upto = process_result
            return committed_tokens or [], processed_upto

        return process_result or [], self.get_audio_buffer_end_time()
    
    async def _emit_word_detection_event(self, tokens: List[ASRToken]):
        """
        Emit word detection event for UI feedback.
        
        NOTE: These tokens are for UI feedback only - NOT final agent-task processing.
        """
        try:
            await self.websocket.send_json({
                "event_type": "agent_task_word_detected",
                "data": {
                    "words": [token.text for token in tokens],
                    "timestamp": time.time(),
                    "note": "streaming_tokens_for_ui_feedback_only"
                }
            })
        except Exception as e:
            logger.error(f"Error emitting word detection event: {e}")
    
    async def _emit_silence_progress_event(self, silence_duration: float):
        """
        Emit silence progress for UI feedback.
        """
        try:
            remaining_time = max(0, self.silence_threshold - silence_duration)
            await self.websocket.send_json({
                "event_type": "agent_task_silence_progress",
                "data": {
                    "silence_duration": silence_duration,
                    "remaining_time": remaining_time,
                    "threshold": self.silence_threshold
                }
            })
        except Exception as e:
            logger.error(f"Error emitting silence progress event: {e}")
    
    async def _end_capture(self, reason: str):
        """
        End the agent_task capture and emit completion event.
        
        Args:
            reason: Reason for capture completion
        """
        if self.capture_completed:
            return
        
        self.capture_completed = True
        self.completion_reason = reason
        time_since_last_word = (
            time.time() - self.last_word_time
            if self.last_word_time is not None
            else None
        )
        self._log_capture_termination_decision(reason, time_since_last_word)
        
        # Calculate total capture duration and audio length
        total_duration = time.time() - self.capture_start_time
        total_audio_samples = sum(len(chunk) for chunk in self.complete_audio_buffer)
        audio_duration = total_audio_samples / self.SAMPLING_RATE if total_audio_samples > 0 else 0
        
        logger.info(f"AgentTask capture completed - reason: {reason}")
        logger.info(f"Capture duration: {total_duration:.2f}s, Audio duration: {audio_duration:.2f}s")
        
        # Emit capture completion event to every websocket client. The selected
        # websocket above is only a feedback channel; the Swift capture widget
        # may be attached to a different connection.
        try:
            await _broadcast_agent_task_capture_complete({
                "event_type": "agent_task_capture_complete",
                "data": {
                    "reason": reason,
                    "capture_duration": total_duration,
                    "audio_duration": audio_duration,
                    "speech_detected": self.speech_detected,
                    "note": "complete_audio_ready_for_batch_transcription"
                }
            })
        except Exception as e:
            logger.error(f"Error emitting capture completion event: {e}")
    
    def get_complete_audio(self) -> Optional[np.ndarray]:
        """
        Get the complete recorded audio for final batch transcription.
        
        Returns:
            Complete audio array for batch processing, or None if no audio
        """
        if not self.complete_audio_buffer:
            logger.warning("No audio buffer available for final transcription")
            return None
        
        # Concatenate all audio chunks into single array
        complete_audio = np.concatenate(self.complete_audio_buffer)
        
        logger.info(f"Complete audio ready: {len(complete_audio)} samples, "
                   f"{len(complete_audio) / self.SAMPLING_RATE:.2f}s duration")
        
        return complete_audio
    
    def is_capture_complete(self) -> bool:
        """Check if capture has been completed."""
        return self.capture_completed
    
    def get_completion_reason(self) -> Optional[str]:
        """Get the reason why capture was completed."""
        return self.completion_reason


class AgentTaskStreamingManager:
    """
    Manages agent_task streaming sessions for word-based capture termination.
    """
    
    def __init__(self):
        self.active_sessions: Dict[str, AgentTaskStreamProcessor] = {}
        self.whisper_kit = None
        self._initialization_lock = asyncio.Lock()
        self._initializing = False
    
    async def _ensure_whisper_kit_initialized(self):
        """
        Ensure TranscriptionEngine (upstream WhisperLiveKit) is initialized asynchronously.
        This prevents blocking the event loop during model loading.
        """
        if self.whisper_kit is not None:
            return
            
        async with self._initialization_lock:
            # Double-check after acquiring lock
            if self.whisper_kit is not None:
                return
                
            logger.info("Initializing TranscriptionEngine asynchronously...")
            
            # Run the synchronous initialization in a thread pool
            def _init_whisper_kit():
                # Get current preferences for language only
                preferences = Preferences.load()
                
                # Configure TranscriptionEngine for streaming termination detection
                # Use the fastest, smallest model since this is ONLY for termination detection
                # The final transcription will use the user's preferred high-quality model
                basil_config = {
                    "model": "Tiny",  # Fastest model optimized for termination detection
                    "language": preferences.behavior.transcription_language or "en", 
                    "diarization": False,  # Disable diarization for speed in termination detection
                    "vac": True,  # Enable Voice Activity Detection
                    "transcription": True,
                    "backend_policy": "local_agreement",  # Use stable local_agreement backend (not simulstreaming)
                }
                
                # Map to upstream format
                upstream_config = map_basil_config_to_upstream(basil_config)
                
                kit = TranscriptionEngine(**upstream_config)
                # Pre-load the ASR to trigger warmup in the thread
                _ = kit.asr  # This triggers synchronous warmup
                return kit
            
            loop = asyncio.get_event_loop()
            self.whisper_kit = await loop.run_in_executor(
                None,  # Use default thread pool
                _init_whisper_kit
            )
            
            logger.info("TranscriptionEngine initialization completed asynchronously")
    
    async def create_streaming_session(
        self, 
        websocket: WebSocket, 
        session_id: str,
        silence_threshold: float = 2.0
    ) -> AgentTaskStreamProcessor:
        """
        Create a new streaming session for agent_task capture termination.
        
        Args:
            websocket: WebSocket connection
            session_id: Unique session identifier
            silence_threshold: Word silence threshold in seconds
            
        Returns:
            AgentTaskStreamProcessor instance
        """
        logger.info(f"Creating agent_task streaming session: {session_id}")
        
        # Ensure WhisperLive is initialized asynchronously
        await self._ensure_whisper_kit_initialized()
        
        # Create streaming processor using kit's ASR directly
        # The upstream OnlineASRProcessor extracts tokenizer, buffer_trimming, and
        # confidence_validation from the ASR object itself
        processor = AgentTaskStreamProcessor(
            websocket=websocket,
            silence_threshold_seconds=silence_threshold,
            asr=self.whisper_kit.asr
        )
        
        # Store session
        self.active_sessions[session_id] = processor
        
        logger.info(f"AgentTask streaming session created: {session_id}")
        return processor
    
    def get_session(self, session_id: str) -> Optional[AgentTaskStreamProcessor]:
        """Get an active streaming session."""
        return self.active_sessions.get(session_id)
    
    def remove_session(self, session_id: str):
        """Remove a streaming session."""
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]
            logger.info(f"AgentTask streaming session removed: {session_id}")
    
    def get_active_session_count(self) -> int:
        """Get the number of active streaming sessions."""
        return len(self.active_sessions)


# Global streaming manager instance
streaming_manager = AgentTaskStreamingManager()


async def handle_agent_task_streaming_audio(
    websocket: WebSocket,
    session_id: str,
    audio_data: bytes
) -> bool:
    """
    Handle incoming audio data for agent_task streaming termination detection.
    
    Args:
        websocket: WebSocket connection
        session_id: Session identifier
        audio_data: Raw audio bytes
        
    Returns:
        True if capture should continue, False if completed
    """
    processor = streaming_manager.get_session(session_id)
    if not processor:
        logger.error(f"No streaming session found for ID: {session_id}")
        return False
    
    if processor.is_capture_complete():
        return False
    
    try:
        # Handle empty audio data (used for silence detection checks)
        if len(audio_data) == 0:
            # Just call the termination detection without adding audio
            await processor.process_iter_with_termination_detection()
        else:
            # Convert audio bytes to numpy array
            audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            
            # Process audio for termination detection
            processor.insert_audio_chunk(audio_array)
            await processor.process_iter_with_termination_detection()
        
        return not processor.is_capture_complete()
        
    except Exception as e:
        logger.error(f"Error processing streaming audio: {e}")
        await processor._end_capture("processing_error")
        return False


async def create_agent_task_streaming_session(
    websocket: WebSocket,
    session_id: str,
    silence_threshold: float = 2.0
) -> AgentTaskStreamProcessor:
    """
    Create a new agent_task streaming session.
    
    Returns:
        AgentTaskStreamProcessor for termination detection
    """
    return await streaming_manager.create_streaming_session(
        websocket, session_id, silence_threshold
    )


def get_session_complete_audio(session_id: str) -> Optional[np.ndarray]:
    """
    Get complete audio from a streaming session for final batch transcription.
    
    IMPORTANT: This is the audio that gets used for actual agent-task processing.
    
    Returns:
        Complete audio array for batch transcription
    """
    processor = streaming_manager.get_session(session_id)
    if not processor:
        return None
    
    return processor.get_complete_audio()


def cleanup_streaming_session(session_id: str):
    """Clean up a completed streaming session."""
    # Force stop the processor before removing to ensure immediate cleanup
    processor = streaming_manager.get_session(session_id)
    if processor and not processor.capture_completed:
        # Synchronously mark as complete to stop further processing
        processor.capture_completed = True
        processor.completion_reason = "canceled"
        logger.debug(f"Force-stopped streaming processor for session: {session_id}")
    
    streaming_manager.remove_session(session_id)


def cleanup_all_streaming_sessions():
    """
    Clean up all active streaming sessions.
    Used for emergency cleanup during cancellation.
    """
    active_count = streaming_manager.get_active_session_count()
    if active_count > 0:
        logger.info(f"Cleaning up {active_count} active streaming sessions")
        # Get list of session IDs to avoid modifying dict during iteration
        session_ids = list(streaming_manager.active_sessions.keys())
        for session_id in session_ids:
            cleanup_streaming_session(session_id)
        logger.info("All streaming sessions cleaned up")
    else:
        logger.debug("No active streaming sessions to clean up") 