import asyncio
import math
import numpy as np
from time import time
import logging
import traceback
from typing import Optional, Union, List, Any, AsyncGenerator
from whisper_live_core.timed_objects import ASRToken, Silence, Line, FrontData, State, Transcript, ChangeSpeaker
from .core import TranscriptionEngine, online_factory, online_diarization_factory, online_translation_factory
from whisper_live_core.silero_vad_iterator import FixedVADIterator
from whisper_live_core.ffmpeg_manager import FFmpegManager, FFmpegState
from whisper_live_core.tokens_alignment import TokensAlignment
from .token_timeline import assign_token_timeline, suppress_hallucinated_silence_tokens
from .diagnostics.stream_commit_watchdog import StreamCommitWatchdog
from .vad_threshold_policy import vad_params_for_source
from .repetition_degeneration_guard import (
    RepetitionDegenerationTracker,
    repetition_policy_for_source,
)
from .nonspeech_prob_policy import nonspeech_prob_for_source
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

SENTINEL = object() # unique sentinel object for end of stream marker
MIN_DURATION_REAL_SILENCE = 2  # Reduced to 2 seconds to match line break logic and prevent context contamination

async def get_all_from_queue(queue: asyncio.Queue) -> Union[object, Silence, np.ndarray, List[Any]]:
    items: List[Any] = []

    first_item = await queue.get()
    queue.task_done()
    if first_item is SENTINEL:
        return first_item
    if isinstance(first_item, Silence):
        return first_item
    items.append(first_item)
    
    while True:
        if not queue._queue:
            break
        next_item = queue._queue[0]
        if next_item is SENTINEL:
            break
        if isinstance(next_item, Silence):
            break
        items.append(await queue.get())
        queue.task_done()
    if isinstance(items[0], np.ndarray):
        return np.concatenate(items)
    else: #translation
        return items

class AudioProcessor:
    """
    Processes audio streams for transcription and diarization.
    Handles audio processing, state management, and result formatting.
    """
    
    def __init__(self, **kwargs: Any) -> None:
        """Initialize the audio processor with configuration, models, and state."""
        
        if 'transcription_engine' in kwargs and isinstance(kwargs['transcription_engine'], TranscriptionEngine):
            models = kwargs['transcription_engine']
        else:
            models = TranscriptionEngine(**kwargs)
        
        # Extract meeting_recorder from kwargs if provided
        self.meeting_recorder = kwargs.get('meeting_recorder', None)
        
        # Audio processing settings
        self.args = models.args
        self.sample_rate = 16000
        self.channels = 1
        self.samples_per_sec = int(self.sample_rate * self.args.min_chunk_size)
        self.bytes_per_sample = 2
        self.bytes_per_sec = self.samples_per_sec * self.bytes_per_sample
        self.max_bytes_per_sec = 32000 * 5  # 5 seconds of audio at 32 kHz
        self.is_pcm_input = self.args.pcm_input
        logger.info(f"AudioProcessor initialized: pcm_input={self.is_pcm_input}, backend={self.args.backend_policy}, meeting_recorder={'enabled' if self.meeting_recorder else 'disabled'}")
        self.audio_source_name = getattr(self.args, "audio_source", kwargs.get("audio_source", "unknown"))
        self.received_pcm_message_count = 0
        self.handled_pcm_chunk_count = 0
        self.enqueued_active_audio_count = 0
        # Diagnostics-only: detect "audio keeps arriving but no transcript is
        # committed" stalls (the system-audio truncation symptom). Tagged by
        # source so the two concurrent streams are distinguishable in logs.
        self._commit_watchdog = StreamCommitWatchdog(self.audio_source_name)

        # State management
        self.is_stopping: bool = False
        self.current_silence: Optional[Silence] = None
        self.state: State = State()
        self.lock: asyncio.Lock = asyncio.Lock()
        self.sep: str = " "  # Default separator
        self.last_response_content: FrontData = FrontData()

        self.tokens_alignment: TokensAlignment = TokensAlignment(self.state, self.args, self.sep)
        self.beg_loop: Optional[float] = None

        # Models and processing
        self.asr: Any = models.asr
        self.vac_model: Any = models.vac_model
        if self.args.vac:
            # Pick a per-source VAD profile: the microphone path stays strict,
            # while system-audio streams get a more lenient, dip-bridging gate so
            # audible produced audio is not silently dropped from the live
            # transcript. See vad_threshold_policy for the rationale and values.
            vad_threshold, vad_min_silence_ms = vad_params_for_source(self.audio_source_name)
            logger.info(
                f"VAD profile for source='{self.audio_source_name}': "
                f"threshold={vad_threshold}, min_silence_ms={vad_min_silence_ms}"
            )
            self.vac: Optional[FixedVADIterator] = FixedVADIterator(
                models.vac_model,
                threshold=vad_threshold,
                min_silence_duration_ms=vad_min_silence_ms,
            )
        else:
            self.vac: Optional[FixedVADIterator] = None

        # Output-stage degeneration guard. Drops decoder repetition/non-speech
        # loops (music-driven "no no no" / "[Music]" runs) after they are
        # committed, using a per-source policy. This is independent of the
        # (deliberately lenient) VAD input gate above: it keys on degenerate
        # output structure, so legible speech is never affected. State is held
        # per source so a loop spanning multiple commits is still caught.
        self._repetition_tracker = RepetitionDegenerationTracker(
            repetition_policy_for_source(self.audio_source_name)
        )

        self.ffmpeg_manager: Optional[FFmpegManager] = None
        self.ffmpeg_reader_task: Optional[asyncio.Task] = None
        self._ffmpeg_error: Optional[str] = None

        if not self.is_pcm_input:
            self.ffmpeg_manager = FFmpegManager(
                sample_rate=self.sample_rate,
                channels=self.channels
            )
            async def handle_ffmpeg_error(error_type: str):
                logger.error(f"FFmpeg error: {error_type}")
                self._ffmpeg_error = error_type
            self.ffmpeg_manager.on_error_callback = handle_ffmpeg_error
             
        self.transcription_queue: Optional[asyncio.Queue] = asyncio.Queue() if self.args.transcription else None
        self.diarization_queue: Optional[asyncio.Queue] = asyncio.Queue() if self.args.diarization else None
        self.translation_queue: Optional[asyncio.Queue] = asyncio.Queue() if self.args.target_language else None
        self.pcm_buffer: bytearray = bytearray()
        self.total_pcm_samples: int = 0
        self.native_stream_offset_seconds: float = 0.0
        self.transcription_task: Optional[asyncio.Task] = None
        self.diarization_task: Optional[asyncio.Task] = None
        self.translation_task: Optional[asyncio.Task] = None
        self.watchdog_task: Optional[asyncio.Task] = None
        self.all_tasks_for_cleanup: List[asyncio.Task] = []
        
        self.transcription: Optional[Any] = None
        self.translation: Optional[Any] = None
        self.diarization: Optional[Any] = None

        if self.args.transcription:
            self.transcription = online_factory(self.args, models.asr)        
            self.sep = self.transcription.asr.sep   
            # Apply the per-source non-speech gate threshold to the streaming
            # decoder instance when it exposes one (SimulStreaming). Set on the
            # instance, never on the cfg shared across pooled models; other
            # backends without this attribute are left untouched.
            backend_model = getattr(self.transcription, "model", None)
            if backend_model is not None and hasattr(backend_model, "nonspeech_prob"):
                backend_model.nonspeech_prob = nonspeech_prob_for_source(
                    self.audio_source_name
                )
        if self.args.diarization:
            self.diarization = online_diarization_factory(self.args, models.diarization_model)
        if models.translation_model:
            self.translation = online_translation_factory(self.args, models.translation_model)

    async def _push_silence_event(self) -> None:
        if self.transcription_queue:
            await self.transcription_queue.put(self.current_silence)
        if self.args.diarization and self.diarization_queue:
            await self.diarization_queue.put(self.current_silence)
        if self.translation_queue:
            await self.translation_queue.put(self.current_silence)

    def set_native_stream_offset_seconds(self, offset_seconds: float) -> None:
        """Set the native capture origin for emitted token timelines."""
        if not math.isfinite(offset_seconds) or offset_seconds < 0.0:
            raise ValueError("native stream offset must be a finite non-negative value")
        self.native_stream_offset_seconds = offset_seconds
        if self.meeting_recorder:
            self.meeting_recorder.set_stream_timeline_origin_seconds(
                self.meeting_recorder.timeline_offset_seconds + offset_seconds
            )

    async def _begin_silence(self) -> None:
        if self.current_silence:
            return
        now = time() - self.beg_loop
        self.current_silence = Silence(
            is_starting=True, start=now
        )
        await self._push_silence_event()

    async def _end_silence(self) -> None:
        if not self.current_silence:
            return
        now = time() - self.beg_loop
        self.current_silence.end = now
        self.current_silence.is_starting=False
        self.current_silence.has_ended=True
        self.current_silence.compute_duration()
        if self.current_silence.duration > MIN_DURATION_REAL_SILENCE:
            self.state.new_tokens.append(self.current_silence)
        await self._push_silence_event()
        self.current_silence = None

    async def _enqueue_active_audio(self, pcm_chunk: np.ndarray) -> None:
        if pcm_chunk is None or pcm_chunk.size == 0:
            return
        self.enqueued_active_audio_count += 1
        transcription_queue_size_before = self.transcription_queue.qsize() if self.transcription_queue else None
        if self.transcription_queue:
            await self.transcription_queue.put(pcm_chunk.copy())
        transcription_queue_size_after = self.transcription_queue.qsize() if self.transcription_queue else None
        if self._should_log_pcm_diagnostic(self.enqueued_active_audio_count):
            rms, peak = self._calculate_pcm_stats(pcm_chunk)
            logger.info(
                "[PCM Enqueue] source=%s enqueue_count=%s samples=%s duration=%.3fs rms=%.4f peak=%.4f transcription_queue=%s->%s",
                self.audio_source_name,
                self.enqueued_active_audio_count,
                pcm_chunk.size,
                pcm_chunk.size / self.sample_rate,
                rms,
                peak,
                transcription_queue_size_before,
                transcription_queue_size_after,
            )
        if self.args.diarization and self.diarization_queue:
            # Apply backpressure: if diarization queue is too deep, drop oldest chunks
            # This keeps diarization synchronized with real-time transcription
            queue_size = self.diarization_queue.qsize()
            if queue_size > 10:
                # Queue is overloaded, drop oldest chunks to stay current
                # More aggressive than transcription (10 vs 30) because diarization is slower
                try:
                    # Remove oldest item (non-blocking)
                    self.diarization_queue.get_nowait()
                    if queue_size % 5 == 0:  # Log every 5th time
                        logger.warning(f"⚠️ Diarization queue overloaded ({queue_size}), dropped oldest chunk to maintain real-time sync")
                except asyncio.QueueEmpty:
                    pass
            await self.diarization_queue.put(pcm_chunk.copy())

    def _slice_before_silence(self, pcm_array: np.ndarray, chunk_sample_start: int, silence_sample: Optional[int]) -> Optional[np.ndarray]:
        if silence_sample is None:
            return None
        relative_index = int(silence_sample - chunk_sample_start)
        if relative_index <= 0:
            return None
        split_index = min(relative_index, len(pcm_array))
        if split_index <= 0:
            return None
        return pcm_array[:split_index]

    def _should_log_pcm_diagnostic(self, count: int) -> bool:
        return count <= 10 or count % 50 == 0

    def _calculate_pcm_stats(self, pcm_array: np.ndarray) -> tuple[float, float]:
        if pcm_array is None or pcm_array.size == 0:
            return 0.0, 0.0
        finite_pcm = pcm_array[np.isfinite(pcm_array)]
        if finite_pcm.size == 0:
            return 0.0, 0.0
        rms = float(np.sqrt(np.mean(finite_pcm ** 2)))
        peak = float(np.max(np.abs(finite_pcm)))
        return rms, peak

    def _describe_vad_result(self, vad_result: Optional[dict]) -> str:
        if vad_result is None:
            return "none"
        return ",".join(f"{key}={value}" for key, value in vad_result.items())

    def convert_pcm_to_float(self, pcm_buffer: Union[bytes, bytearray]) -> np.ndarray:
        """Convert PCM buffer in s16le format to normalized NumPy array."""
        audio_array = np.frombuffer(pcm_buffer, dtype=np.int16).astype(np.float32) / 32768.0
        
        # Diagnostic logging for audio levels
        if len(audio_array) > 0:
            rms = np.sqrt(np.mean(audio_array**2))
            max_amplitude = np.max(np.abs(audio_array))
            logger.debug(f"[PCM Audio] RMS: {rms:.4f}, Max: {max_amplitude:.4f}, Samples: {len(audio_array)}")
        
        return audio_array
            
    async def get_current_state(self) -> State:
        """Get current state."""
        async with self.lock:
            current_time = time()
            
            remaining_transcription = 0
            if self.state.end_buffer > 0:
                remaining_transcription = max(0, round(current_time - self.beg_loop - self.state.end_buffer, 1))
                
            remaining_diarization = 0
            if self.state.tokens:
                latest_end = max(self.state.end_buffer, self.state.tokens[-1].end if self.state.tokens else 0)
                remaining_diarization = max(0, round(latest_end - self.state.end_attributed_speaker, 1))
                
            self.state.remaining_time_transcription = remaining_transcription
            self.state.remaining_time_diarization = remaining_diarization
            
            return self.state

    async def ffmpeg_stdout_reader(self) -> None:
        """Read audio data from FFmpeg stdout and process it into the PCM pipeline."""
        beg = time()
        while True:
            try:
                if self.is_stopping:
                    logger.info("Stopping ffmpeg_stdout_reader due to stopping flag.")
                    break

                state = await self.ffmpeg_manager.get_state() if self.ffmpeg_manager else FFmpegState.STOPPED
                if state == FFmpegState.FAILED:
                    logger.error("FFmpeg is in FAILED state, cannot read data")
                    break
                elif state == FFmpegState.STOPPED:
                    logger.info("FFmpeg is stopped")
                    break
                elif state != FFmpegState.RUNNING:
                    await asyncio.sleep(0.1)
                    continue

                current_time = time()
                elapsed_time = max(0.0, current_time - beg)
                buffer_size = max(int(32000 * elapsed_time), 4096)  # dynamic read
                beg = current_time

                chunk = await self.ffmpeg_manager.read_data(buffer_size)
                if not chunk:
                    # No data currently available
                    await asyncio.sleep(0.05)
                    continue

                self.pcm_buffer.extend(chunk)
                await self.handle_pcm_data()

            except asyncio.CancelledError:
                logger.info("ffmpeg_stdout_reader cancelled.")
                break
            except Exception as e:
                logger.warning(f"Exception in ffmpeg_stdout_reader: {e}")
                logger.debug(f"Traceback: {traceback.format_exc()}")
                await asyncio.sleep(0.2)

        logger.info("FFmpeg stdout processing finished. Signaling downstream processors if needed.")
        if self.transcription_queue:
            await self.transcription_queue.put(SENTINEL)
        if self.diarization:
            await self.diarization_queue.put(SENTINEL)
        if self.translation:
            await self.translation_queue.put(SENTINEL)

    async def transcription_processor(self) -> None:
        """Process audio chunks for transcription."""
        cumulative_pcm_duration_stream_time = 0.0
        
        while True:
            try:
                # item = await self.transcription_queue.get()
                item = await get_all_from_queue(self.transcription_queue)
                if item is SENTINEL:
                    logger.debug("Transcription processor received sentinel. Finishing.")
                    break

                asr_internal_buffer_duration_s = len(getattr(self.transcription, 'audio_buffer', [])) / self.transcription.SAMPLING_RATE
                transcription_lag_s = max(0.0, time() - self.beg_loop - self.state.end_buffer)
                asr_processing_logs = f"internal_buffer={asr_internal_buffer_duration_s:.2f}s | lag={transcription_lag_s:.2f}s |"
                stream_time_end_of_current_pcm = cumulative_pcm_duration_stream_time
                new_tokens = []
                current_audio_processed_upto = self.state.end_buffer

                if isinstance(item, Silence):
                    if item.is_starting:
                        new_tokens, current_audio_processed_upto = await asyncio.to_thread(
                            self.transcription.start_silence
                        )
                        asr_processing_logs += f" + Silence starting"
                    if item.has_ended:
                        asr_processing_logs += f" + Silence of = {item.duration:.2f}s"
                        cumulative_pcm_duration_stream_time += item.duration
                        current_audio_processed_upto = cumulative_pcm_duration_stream_time
                        # Offload off the event loop (mirrors the process_iter /
                        # start_silence offload above) so a slow end_silence call
                        # never blocks uvicorn's keepalive ping for the sibling
                        # source's socket.
                        await asyncio.to_thread(
                            self.transcription.end_silence,
                            item.duration,
                            self.state.tokens[-1].end if self.state.tokens else 0,
                        )
                    if self.state.tokens:
                        asr_processing_logs += f" | last_end = {self.state.tokens[-1].end} |"
                    logger.info(asr_processing_logs)
                    new_tokens = new_tokens or []
                    current_audio_processed_upto = max(current_audio_processed_upto, stream_time_end_of_current_pcm)
                elif isinstance(item, ChangeSpeaker):
                    self.transcription.new_speaker(item)
                    continue
                elif isinstance(item, np.ndarray):
                    pcm_array = item
                    logger.info(asr_processing_logs)
                    cumulative_pcm_duration_stream_time += len(pcm_array) / self.sample_rate
                    stream_time_end_of_current_pcm = cumulative_pcm_duration_stream_time
                    self.transcription.insert_audio_chunk(pcm_array, stream_time_end_of_current_pcm)
                    logger.info(f"[AUDIO_PROCESSOR] Calling process_iter()...")
                    new_tokens, current_audio_processed_upto = await asyncio.to_thread(self.transcription.process_iter)
                    new_tokens = new_tokens or []
                    logger.info(f"[AUDIO_PROCESSOR] process_iter() returned {len(new_tokens)} tokens")

                    # Drop hallucinated speech tokens committed over an
                    # acoustically silent chunk (the "engvid on silence" case)
                    # before they are buffered/committed. Speech chunks with any
                    # real energy are unaffected.
                    if new_tokens:
                        filtered_tokens = suppress_hallucinated_silence_tokens(
                            pcm_array,
                            new_tokens,
                            sample_rate=self.sample_rate,
                        )
                        if len(filtered_tokens) != len(new_tokens):
                            logger.info(
                                f"[TRANSCRIPTION] Suppressed {len(new_tokens) - len(filtered_tokens)} "
                                f"hallucinated token(s) on silent chunk"
                            )
                        new_tokens = filtered_tokens

                    # Drop decoder repetition/non-speech degeneration loops
                    # (e.g. music-driven "no no no" / "[Music]" runs) before they
                    # are buffered/committed. Keyed on degenerate output
                    # structure (not loudness), so legible speech is unaffected;
                    # state carries across commits to catch loops that span them.
                    if new_tokens:
                        deduped_tokens = self._repetition_tracker.filter(new_tokens)
                        if len(deduped_tokens) != len(new_tokens):
                            logger.info(
                                f"[TRANSCRIPTION] Suppressed {len(new_tokens) - len(deduped_tokens)} "
                                f"degenerate repetition token(s)"
                            )
                        new_tokens = deduped_tokens
                    
                    # Diagnostic logging
                    if new_tokens:
                        logger.info(f"[TRANSCRIPTION] Got {len(new_tokens)} new tokens: {[t.text for t in new_tokens]}")
                    else:
                        logger.info(f"[TRANSCRIPTION] No new tokens produced (process_iter returned empty)")

                _buffer_transcript = self.transcription.get_buffer()
                buffer_text = _buffer_transcript.text
                logger.debug(f"[TRANSCRIPTION] Buffer text: '{buffer_text}', Buffer end: {_buffer_transcript.end}")

                if new_tokens:
                    validated_text = self.sep.join([t.text for t in new_tokens])
                    if buffer_text.startswith(validated_text):
                        _buffer_transcript.text = buffer_text[len(validated_text):].lstrip()
                    else:
                        # CRITICAL: If buffer doesn't match, clear it anyway to prevent contamination
                        logger.warning(f"[BUFFER] Buffer text doesn't match validated tokens. Clearing to prevent contamination. Buffer: '{buffer_text[:50]}...', Validated: '{validated_text[:50]}...'")
                        _buffer_transcript.text = ""
                    assign_token_timeline(
                        new_tokens,
                        stream_time_end_of_current_pcm + self.native_stream_offset_seconds,
                    )

                candidate_end_times = [self.state.end_buffer]

                if new_tokens:
                    candidate_end_times.append(new_tokens[-1].end)
                
                if _buffer_transcript.end is not None:
                    candidate_end_times.append(_buffer_transcript.end)
                
                candidate_end_times.append(current_audio_processed_upto)
                
                async with self.lock:
                    self.state.tokens.extend(new_tokens)
                    self.state.buffer_transcription = _buffer_transcript
                    self.state.end_buffer = max(candidate_end_times)
                    self.state.new_tokens.extend(new_tokens)
                    self.state.new_tokens_buffer = _buffer_transcript

                if self.translation_queue:
                    for token in new_tokens:
                        await self.translation_queue.put(token)                
            except Exception as e:
                logger.warning(f"Exception in transcription_processor: {e}")
                logger.warning(f"Traceback: {traceback.format_exc()}")
                if 'pcm_array' in locals() and pcm_array is not SENTINEL : # Check if pcm_array was assigned from queue
                    self.transcription_queue.task_done()
        
        if self.is_stopping:
            logger.info("Transcription processor finishing due to stopping flag.")
            if self.diarization_queue:
                await self.diarization_queue.put(SENTINEL)
            if self.translation_queue:
                await self.translation_queue.put(SENTINEL)

        logger.info("Transcription processor task finished.")


    async def diarization_processor(self) -> None:
        while True:
            try:
                item = await get_all_from_queue(self.diarization_queue)
                if item is SENTINEL:
                    break
                elif type(item) is Silence:
                    if item.has_ended:
                        self.diarization.insert_silence(item.duration)
                    continue

                await self.diarization.diarize(item)
                
                # Get segments from the observer with timeout to prevent deadlock
                # Increased timeout from 5s to 15s to allow diarization model more processing time
                # for complex multi-speaker scenarios (e.g., panel discussions)
                try:
                    diarization_segments = await asyncio.wait_for(
                        asyncio.to_thread(self.diarization.observer.get_segments),
                        timeout=15.0
                    )
                    self.state.new_diarization = diarization_segments
                    
                    # Log queue depth to monitor backpressure
                    if self.diarization_queue and not self.diarization_queue.empty():
                        queue_size = self.diarization_queue.qsize()
                        if queue_size > 10:
                            logger.warning(f"Diarization queue building up: {queue_size} items pending")
                            
                except asyncio.TimeoutError:
                    logger.warning("Diarization get_segments() timed out after 15s - skipping update. Queue may be overloaded.")
                except Exception as seg_err:
                    logger.error(f"Error getting diarization segments: {seg_err}")
                
            except Exception as e:
                logger.warning(f"Exception in diarization_processor: {e}")
                logger.warning(f"Traceback: {traceback.format_exc()}")
        logger.info("Diarization processor task finished.")

    async def translation_processor(self) -> None:
        # the idea is to ignore diarization for the moment. We use only transcription tokens. 
        # And the speaker is attributed given the segments used for the translation
        # in the future we want to have different languages for each speaker etc, so it will be more complex.
        while True:
            try:
                item = await get_all_from_queue(self.translation_queue)
                if item is SENTINEL:
                    logger.debug("Translation processor received sentinel. Finishing.")
                    break
                elif type(item) is Silence:
                    if item.is_starting:
                        new_translation, new_translation_buffer = self.translation.validate_buffer_and_reset()
                    if item.has_ended:
                        self.translation.insert_silence(item.duration)
                        continue
                elif isinstance(item, ChangeSpeaker):
                    new_translation, new_translation_buffer = self.translation.validate_buffer_and_reset()
                    pass
                else:
                    self.translation.insert_tokens(item)
                    new_translation, new_translation_buffer = await asyncio.to_thread(self.translation.process)
                async with self.lock:
                    self.state.new_translation.append(new_translation)
                    self.state.new_translation_buffer = new_translation_buffer
            except Exception as e:
                logger.warning(f"Exception in translation_processor: {e}")
                logger.warning(f"Traceback: {traceback.format_exc()}")
        logger.info("Translation processor task finished.")

    async def results_formatter(self) -> AsyncGenerator[FrontData, None]:
        """Format processing results for output."""
        while True:
            try:
                if self._ffmpeg_error:
                    yield FrontData(status="error", error=f"FFmpeg error: {self._ffmpeg_error}")
                    self._ffmpeg_error = None
                    await asyncio.sleep(1)
                    continue

                self.tokens_alignment.update()
                lines, buffer_diarization_text, buffer_translation_text = self.tokens_alignment.get_lines(
                    diarization=self.args.diarization,
                    translation=bool(self.translation),
                    current_silence=self.current_silence
                )
                state = await self.get_current_state()

                buffer_transcription_text = state.buffer_transcription.text if state.buffer_transcription else ''

                response_status = "active_transcription"
                if not lines and not buffer_transcription_text and not buffer_diarization_text:
                    response_status = "no_audio_detected"

                response = FrontData(
                    status=response_status,
                    lines=lines,
                    buffer_transcription=buffer_transcription_text,
                    buffer_diarization=buffer_diarization_text,
                    buffer_translation=buffer_translation_text,
                    remaining_time_transcription=state.remaining_time_transcription,
                    remaining_time_diarization=state.remaining_time_diarization if self.args.diarization else 0
                )
                
                # Diagnostics-only: finalized lines = a commit; clears any stall.
                if lines:
                    self._commit_watchdog.note_commit(time())

                # Save transcript segments to meeting recorder if active
                if self.meeting_recorder and lines:
                    try:
                        for line in lines:
                            # Save final (non-interim) transcript lines to meeting
                            if hasattr(line, 'start') and hasattr(line, 'end') and hasattr(line, 'text'):
                                speaker = getattr(line, 'speaker', None)
                                timeline_start = getattr(line, 'timeline_start_seconds', None)
                                timeline_end = getattr(line, 'timeline_end_seconds', None)
                                self.meeting_recorder.add_transcript_segment(
                                    start=timeline_start if timeline_start is not None else line.start,
                                    end=timeline_end if timeline_end is not None else line.end,
                                    text=line.text,
                                    speaker=speaker,
                                    is_interim=False
                                )
                    except Exception as e:
                        logger.error(f"Failed to save transcript segments to meeting recorder: {e}", exc_info=True)
                                
                should_push = (response != self.last_response_content)
                if should_push:
                    yield response
                    self.last_response_content = response
                
                if self.is_stopping and self._processing_tasks_done():
                    logger.info("Results formatter: All upstream processors are done and in stopping state. Terminating.")
                    return
                
                await asyncio.sleep(0.05)
                
            except Exception as e:
                logger.warning(f"Exception in results_formatter. Traceback: {traceback.format_exc()}")
                await asyncio.sleep(0.5)
        
    async def create_tasks(self) -> AsyncGenerator[FrontData, None]:
        """Create and start processing tasks."""
        self.all_tasks_for_cleanup = []
        processing_tasks_for_watchdog: List[asyncio.Task] = []

        # If using FFmpeg (non-PCM input), start it and spawn stdout reader
        if not self.is_pcm_input:
            success = await self.ffmpeg_manager.start()
            if not success:
                logger.error("Failed to start FFmpeg manager")
                async def error_generator() -> AsyncGenerator[FrontData, None]:
                    yield FrontData(
                        status="error",
                        error="FFmpeg failed to start. Please check that FFmpeg is installed."
                    )
                return error_generator()
            self.ffmpeg_reader_task = asyncio.create_task(self.ffmpeg_stdout_reader())
            self.all_tasks_for_cleanup.append(self.ffmpeg_reader_task)
            processing_tasks_for_watchdog.append(self.ffmpeg_reader_task)

        if self.transcription:
            self.transcription_task = asyncio.create_task(self.transcription_processor())
            self.all_tasks_for_cleanup.append(self.transcription_task)
            processing_tasks_for_watchdog.append(self.transcription_task)
            
        if self.diarization:
            self.diarization_task = asyncio.create_task(self.diarization_processor())
            self.all_tasks_for_cleanup.append(self.diarization_task)
            processing_tasks_for_watchdog.append(self.diarization_task)
        
        if self.translation:
            self.translation_task = asyncio.create_task(self.translation_processor())
            self.all_tasks_for_cleanup.append(self.translation_task)
            processing_tasks_for_watchdog.append(self.translation_task)
        
        # Monitor overall system health
        self.watchdog_task = asyncio.create_task(self.watchdog(processing_tasks_for_watchdog))
        self.all_tasks_for_cleanup.append(self.watchdog_task)
        
        return self.results_formatter()

    async def watchdog(self, tasks_to_monitor: List[asyncio.Task]) -> None:
        """Monitors the health of critical processing tasks."""
        tasks_remaining: List[asyncio.Task] = [task for task in tasks_to_monitor if task]
        while True:
            try:
                if not tasks_remaining:
                    logger.info("Watchdog task finishing: all monitored tasks completed.")
                    return

                await asyncio.sleep(10)
                
                for i, task in enumerate(list(tasks_remaining)):
                    if task.done():
                        exc = task.exception()
                        task_name = task.get_name() if hasattr(task, 'get_name') else f"Monitored Task {i}"
                        if exc:
                            logger.error(f"{task_name} unexpectedly completed with exception: {exc}")
                        else:
                            logger.info(f"{task_name} completed normally.")
                        tasks_remaining.remove(task)
                    
            except asyncio.CancelledError:
                logger.info("Watchdog task cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in watchdog task: {e}", exc_info=True)
        
    async def cleanup(self) -> None:
        """Clean up resources when processing is complete."""
        logger.info("Starting cleanup of AudioProcessor resources.")
        self.is_stopping = True
        for task in self.all_tasks_for_cleanup:
            if task and not task.done():
                task.cancel()
            
        created_tasks = [t for t in self.all_tasks_for_cleanup if t]
        if created_tasks:
            await asyncio.gather(*created_tasks, return_exceptions=True)
        logger.info("All processing tasks cancelled or finished.")

        if not self.is_pcm_input and self.ffmpeg_manager:
            try:
                await self.ffmpeg_manager.stop()
                logger.info("FFmpeg manager stopped.")
            except Exception as e:
                logger.warning(f"Error stopping FFmpeg manager: {e}")
        if self.diarization:
            self.diarization.close()
        logger.info("AudioProcessor cleanup complete.")

    def _processing_tasks_done(self) -> bool:
        """Return True when all active processing tasks have completed."""
        tasks_to_check = [
            self.transcription_task,
            self.diarization_task,
            self.translation_task,
            self.ffmpeg_reader_task,
        ]
        return all(task.done() for task in tasks_to_check if task)


    async def process_audio(self, message: Optional[bytes]) -> None:
        """Process incoming audio data."""

        if not self.beg_loop:
            self.beg_loop = time()
            self.current_silence = Silence(start=0.0, is_starting=True)
            self.tokens_alignment.beg_loop = self.beg_loop

        if not message:
            logger.info("Empty audio message received, initiating stop sequence.")
            self.is_stopping = True
             
            if self.transcription_queue:
                await self.transcription_queue.put(SENTINEL)

            if not self.is_pcm_input and self.ffmpeg_manager:
                await self.ffmpeg_manager.stop()

            return

        if self.is_stopping:
            logger.warning("AudioProcessor is stopping. Ignoring incoming audio.")
            return

        if self.is_pcm_input:
            self.received_pcm_message_count += 1
            self.pcm_buffer.extend(message)
            if self._should_log_pcm_diagnostic(self.received_pcm_message_count):
                logger.info(
                    "[PCM Receive] source=%s message_count=%s message_bytes=%s buffered_bytes=%s buffered_duration=%.3fs current_silence_active=%s",
                    self.audio_source_name,
                    self.received_pcm_message_count,
                    len(message),
                    len(self.pcm_buffer),
                    len(self.pcm_buffer) / self.bytes_per_sec,
                    self.current_silence is not None,
                )
            await self.handle_pcm_data()
        else:
            if not self.ffmpeg_manager:
                logger.error("FFmpeg manager not initialized for non-PCM input.")
                return
            success = await self.ffmpeg_manager.write_data(message)
            if not success:
                ffmpeg_state = await self.ffmpeg_manager.get_state()
                if ffmpeg_state == FFmpegState.FAILED:
                    logger.error("FFmpeg is in FAILED state, cannot process audio")
                else:
                    logger.warning("Failed to write audio data to FFmpeg")

    async def handle_pcm_data(self) -> None:
        # Process when enough data
        if len(self.pcm_buffer) < self.bytes_per_sec:
            return

        if len(self.pcm_buffer) > self.max_bytes_per_sec:
            logger.warning(
                f"Audio buffer too large: {len(self.pcm_buffer) / self.bytes_per_sec:.2f}s. "
                f"Consider using a smaller model."
            )

        chunk_size = min(len(self.pcm_buffer), self.max_bytes_per_sec)
        aligned_chunk_size = (chunk_size // self.bytes_per_sample) * self.bytes_per_sample
        
        if aligned_chunk_size == 0:
            return
        
        # Write audio chunk to meeting recorder if active
        if self.meeting_recorder and aligned_chunk_size > 0:
            try:
                self.meeting_recorder.write_audio_chunk(bytes(self.pcm_buffer[:aligned_chunk_size]))
            except Exception as e:
                logger.error(f"Failed to write audio chunk to meeting recorder: {e}", exc_info=True)

        # Diagnostics-only: note audio is still arriving and warn once per stall
        # episode if no transcript has committed while audio keeps flowing.
        now = time()
        self._commit_watchdog.note_audio_received(now)
        stall_seconds = self._commit_watchdog.should_warn(now)
        if stall_seconds is not None:
            logger.warning(
                "[StreamCommitWatchdog] source=%s STALL: no committed transcript for %.1fs while audio keeps arriving "
                "(commits=%s handled_chunks=%s enqueued_active=%s current_silence_active=%s). "
                "Likely the system-audio mid-recording stall; capture surrounding [PCM VAD]/[PCM Enqueue] logs.",
                self.audio_source_name,
                stall_seconds,
                self._commit_watchdog.commit_count,
                self.handled_pcm_chunk_count,
                self.enqueued_active_audio_count,
                self.current_silence is not None,
            )
        
        pcm_array = self.convert_pcm_to_float(self.pcm_buffer[:aligned_chunk_size])
        self.pcm_buffer = self.pcm_buffer[aligned_chunk_size:]
        self.handled_pcm_chunk_count += 1

        num_samples = len(pcm_array)
        chunk_sample_start = self.total_pcm_samples
        chunk_sample_end = chunk_sample_start + num_samples
        rms, peak = self._calculate_pcm_stats(pcm_array)
        silence_active_before_vad = self.current_silence is not None
        vad_action = "vac_disabled"

        res = None
        if self.args.vac:
            res = self.vac(pcm_array)
            vad_action = "no_transition"

        if res is not None:
            silence_detected = res.get("end", 0) > res.get("start", 0)
            if silence_detected and not self.current_silence:
                pre_silence_chunk = self._slice_before_silence(
                    pcm_array, chunk_sample_start, res.get("end")
                )
                if pre_silence_chunk is not None and pre_silence_chunk.size > 0:
                    vad_action = "enqueue_pre_silence_then_begin_silence"
                    await self._enqueue_active_audio(pre_silence_chunk)
                else:
                    vad_action = "begin_silence_without_pre_silence_audio"
                await self._begin_silence()
            elif self.current_silence:
                vad_action = "end_silence"
                await self._end_silence()

        if not self.current_silence:
            if vad_action == "no_transition":
                vad_action = "enqueue_active_audio"
            await self._enqueue_active_audio(pcm_array)
        elif vad_action == "no_transition":
            vad_action = "blocked_by_current_silence"

        should_log_vad_diagnostic = (
            self._should_log_pcm_diagnostic(self.handled_pcm_chunk_count)
            or res is not None
        )
        if should_log_vad_diagnostic:
            logger.info(
                "[PCM VAD] source=%s chunk_count=%s samples=%s rms=%.4f peak=%.4f silence_before=%s silence_after=%s vad_result=%s action=%s total_pcm_samples=%s",
                self.audio_source_name,
                self.handled_pcm_chunk_count,
                num_samples,
                rms,
                peak,
                silence_active_before_vad,
                self.current_silence is not None,
                self._describe_vad_result(res),
                vad_action,
                self.total_pcm_samples,
            )

        self.total_pcm_samples = chunk_sample_end

        if not self.args.transcription and not self.args.diarization:
            await asyncio.sleep(0.1)
