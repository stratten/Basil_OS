"""
AgentTask Streaming WebSocket Handler

CRITICAL ARCHITECTURAL NOTE:
==========================
This streaming processor is used ONLY for intelligent capture termination.
- Voice activity detection on the audio timeline determines WHEN to stop recording
- Final agent-task processing uses the COMPLETE recorded audio via existing batch transcription
- NO streaming content is used for building the actual agent_task request

This provides environment-independent capture termination while maintaining
the existing high-quality batch transcription pipeline for final processing.
"""

import asyncio
import time
import logging
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Dict, Any, Tuple
from fastapi import WebSocket

# UPDATED: Import from whisper_live_core (upstream) instead of old whisper_live
# whisper_streaming was renamed to local_agreement in upstream
from ...services.whisper_live_core.local_agreement.online_asr import OnlineASRProcessor
from ...services.whisper_live_core.timed_objects import ASRToken
from ...services.whisper_live_core.core import TranscriptionEngine  # Was WhisperLiveKit
from ...services.live_transcription.config_mapper import map_basil_config_to_upstream
from ...core.models.preferences import Preferences
from ...services.wake_word.capture_endpointing import (
    WAKE_WORD_SILENCE_SECONDS,
    CaptureEndpointTracker,
    EndpointSettings,
    SpeechProbability,
    create_speech_probability,
)

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

    The end of the request is decided from the audio itself: a voice activity model scores every
    frame and the countdown is measured in seconds of received audio, so how long the streaming
    transcription takes can no longer change when a capture ends. The streaming transcription
    runs on its own worker thread and only supplies the words shown while the person speaks.
    """

    # Silence shorter than this is a pause between words, so no countdown is shown for it.
    COUNTDOWN_GRACE_SECONDS = 0.5
    # Minimum audio time between countdown updates sent to the client.
    PROGRESS_INTERVAL_SECONDS = 0.08
    # Streaming transcription is kept to this much audio so it never falls behind the speaker.
    MAX_STREAMING_BUFFER_SECONDS = 2.0
    STREAMING_BUFFER_KEEP_SECONDS = 0.3

    def __init__(self, websocket: WebSocket, silence_threshold_seconds: float = WAKE_WORD_SILENCE_SECONDS, **kwargs):
        """
        Initialize the streaming processor for capture termination detection.

        Args:
            websocket: WebSocket connection for real-time feedback
            silence_threshold_seconds: Seconds of silence after speech before ending capture
            **kwargs: Passed to parent OnlineASRProcessor
        """
        speech_probability = kwargs.pop("speech_probability", None)
        super().__init__(**kwargs)
        self._init_capture_state(websocket, silence_threshold_seconds, speech_probability)

    def _init_capture_state(
        self,
        websocket: Optional[WebSocket],
        silence_threshold_seconds: float,
        speech_probability: Optional[SpeechProbability] = None,
    ) -> None:
        """Set up everything that belongs to the capture itself rather than to the ASR base class."""
        self.websocket = websocket
        self.silence_threshold = silence_threshold_seconds
        self.endpoint = CaptureEndpointTracker(
            speech_probability or create_speech_probability(),
            EndpointSettings(silence_seconds=silence_threshold_seconds),
        )
        self.capture_start_time = time.monotonic()
        self.capture_timeout = 120.0  # Maximum capture duration (safety) - matches intelligent capture timeout

        self.recent_committed_words: List[str] = []
        self.words_committed = False

        # Complete audio buffer preservation for final batch transcription
        # This is the ONLY audio that matters for the final agent task
        self.complete_audio_buffer: List[np.ndarray] = []

        self.capture_completed = False
        self.completion_reason: Optional[str] = None

        self._pending_asr_audio: List[np.ndarray] = []
        self._asr_task: Optional["asyncio.Task[None]"] = None
        self._asr_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="capture-asr")
        self._countdown_visible = False
        self._last_progress_audio_seconds = -1.0

        logger.info(
            f"AgentTaskStreamProcessor initialized - silence_threshold: {silence_threshold_seconds}s, "
            f"speech detector: {type(self.endpoint._probability).__name__}"
        )

    @property
    def speech_detected(self) -> bool:
        return self.endpoint.heard_speech

    def insert_audio_chunk(self, audio: np.ndarray):
        """
        Take in a chunk of audio: keep it for final batch transcription, advance the end-of-speech
        clock by its duration, and queue it for the streaming transcription worker.

        Args:
            audio: Audio chunk to process
        """
        # CRITICAL: Always preserve complete audio for final batch transcription
        self.complete_audio_buffer.append(audio.copy())
        self.endpoint.feed(audio)
        self._pending_asr_audio.append(audio)

    async def process_iter_with_termination_detection(self) -> Optional[List[ASRToken]]:
        """
        Check whether the capture is over and report the countdown to the client.

        Returns:
            Always an empty list; committed words are delivered to the client as they arrive.
        """
        if self.capture_completed:
            return []

        if time.monotonic() - self.capture_start_time > self.capture_timeout:
            logger.warning(f"AgentTask capture timeout reached ({self.capture_timeout}s)")
            await self._end_capture("timeout")
            return []

        endpoint = self.endpoint
        if endpoint.speech_has_ended:
            await self._end_capture("speech_end_detected")
        elif endpoint.no_speech_timed_out:
            await self._end_capture("no_speech_detected")
        else:
            self._start_asr_step_if_idle()
            await self._report_countdown()
        return []

    async def _report_countdown(self) -> None:
        """Tell the client how long until the capture ends, or that the speaker has resumed."""
        endpoint = self.endpoint
        trailing_silence = endpoint.trailing_silence_seconds
        if trailing_silence >= self.COUNTDOWN_GRACE_SECONDS:
            audio_seconds = endpoint.audio_seconds
            if audio_seconds - self._last_progress_audio_seconds >= self.PROGRESS_INTERVAL_SECONDS:
                self._last_progress_audio_seconds = audio_seconds
                self._countdown_visible = True
                await self._emit_silence_progress_event(trailing_silence)
        elif self._countdown_visible:
            self._countdown_visible = False
            await self._emit_silence_progress_event(0.0, counting=False)

    def _log_capture_termination_decision(self, reason: str) -> None:
        """Log the audio state that justified automatic capture completion."""
        endpoint = self.endpoint
        logger.info(
            "AgentTask capture termination decision: "
            f"reason={reason}, audio_seconds={endpoint.audio_seconds:.2f}, "
            f"trailing_silence={endpoint.trailing_silence_seconds:.2f}, "
            f"heard_speech={endpoint.heard_speech}, in_speech={endpoint.in_speech}, "
            f"recent_committed_words={self.recent_committed_words}"
        )

    # --- Streaming transcription (words for the UI only) ---

    def _start_asr_step_if_idle(self) -> None:
        """Hand the audio gathered so far to the transcription worker unless it is still busy."""
        if self._asr_task is not None and not self._asr_task.done():
            return
        if not self._pending_asr_audio:
            return
        chunks, self._pending_asr_audio = self._pending_asr_audio, []
        self._asr_task = asyncio.get_running_loop().create_task(self._run_asr_step(chunks))

    async def _run_asr_step(self, chunks: List[np.ndarray]) -> None:
        if self.capture_completed:
            return
        loop = asyncio.get_running_loop()
        try:
            tokens = await loop.run_in_executor(self._asr_executor, self._asr_step, chunks)
        except Exception as e:
            logger.error(f"Error in streaming transcription processing: {e}")
            return
        if self.capture_completed or not tokens:
            return
        self.words_committed = True
        self.recent_committed_words = (self.recent_committed_words + [token.text for token in tokens])[-10:]
        logger.debug(f"Words detected: {[token.text for token in tokens]}")
        await self._emit_word_detection_event(tokens)

    def _asr_step(self, chunks: List[np.ndarray]) -> List[ASRToken]:
        """Runs on the worker thread, the only place that touches the ASR buffers."""
        for chunk in chunks:
            OnlineASRProcessor.insert_audio_chunk(self, chunk)
        tokens, _ = self._process_streaming_iteration()
        if not tokens and self.words_committed:
            self._trim_streaming_buffer()
        return tokens

    def _trim_streaming_buffer(self) -> None:
        """Keep only recent audio in the streaming buffer so transcription stays close to real time."""
        if not hasattr(self, "audio_buffer"):
            return
        buffer_seconds = len(self.audio_buffer) / self.SAMPLING_RATE
        if buffer_seconds <= self.MAX_STREAMING_BUFFER_SECONDS:
            return
        keep_samples = int(self.STREAMING_BUFFER_KEEP_SECONDS * self.SAMPLING_RATE)
        if len(self.audio_buffer) > keep_samples:
            logger.info(
                f"Clearing excessive streaming buffer ({buffer_seconds:.2f}s -> {self.STREAMING_BUFFER_KEEP_SECONDS}s) "
                "- complete audio preserved separately"
            )
            self.audio_buffer = self.audio_buffer[-keep_samples:]
            # Update buffer time offset to maintain correct timing
            self.buffer_time_offset += buffer_seconds - self.STREAMING_BUFFER_KEEP_SECONDS

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

    # --- Client events ---

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

    async def _emit_silence_progress_event(self, silence_duration: float, counting: bool = True):
        """
        Emit the end-of-speech countdown for UI feedback.

        counting=False tells the client the speaker resumed, so it can drop the countdown at once
        instead of waiting for the next committed word.
        """
        try:
            remaining_time = max(0, self.silence_threshold - silence_duration) if counting else self.silence_threshold
            await self.websocket.send_json({
                "event_type": "agent_task_silence_progress",
                "data": {
                    "silence_duration": silence_duration,
                    "remaining_time": remaining_time,
                    "threshold": self.silence_threshold,
                    "counting": counting,
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
        self._log_capture_termination_decision(reason)

        # Calculate total capture duration and audio length
        total_duration = time.monotonic() - self.capture_start_time
        total_audio_samples = sum(len(chunk) for chunk in self.complete_audio_buffer)
        audio_duration = total_audio_samples / self.SAMPLING_RATE if total_audio_samples > 0 else 0

        logger.info(f"AgentTask capture completed - reason: {reason}")
        logger.info(f"Capture duration: {total_duration:.2f}s, Audio duration: {audio_duration:.2f}s")

        self.shutdown()

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

    def shutdown(self) -> None:
        """Stop the transcription worker. A step already running finishes, but nothing new starts."""
        self._pending_asr_audio = []
        self._asr_executor.shutdown(wait=False, cancel_futures=True)

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
        silence_threshold: float = WAKE_WORD_SILENCE_SECONDS
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
            self.active_sessions[session_id].shutdown()
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
    silence_threshold: float = WAKE_WORD_SILENCE_SECONDS
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