"""Per-socket live stream state: records every PCM byte and optionally runs live transcription."""

from __future__ import annotations

import asyncio
import bisect
import json
import logging
import math
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from .stream_clock import StreamClock

logger = logging.getLogger(__name__)

PCM_SAMPLE_RATE = 16000
PCM_BYTES_PER_SAMPLE = 2
MAX_STREAM_SECONDS = 24 * 60 * 60
RETIRING_PROCESSOR_DRAIN_SECONDS = 30.0
NATIVE_STREAM_CLOCK_TYPE = "native_stream_clock"
NATIVE_CAPTURE_STATE_TYPE = "native_capture_state"
NATIVE_LIVE_TRANSCRIPTION_TYPE = "native_live_transcription"
LIVE_TRANSCRIPTION_UNAVAILABLE_STATUS = "live_transcription_unavailable"
RECORDING_ONLY_STATUS = "recording_only"

_ENABLED = "enabled"
_ABANDONED = "abandoned"
_UNAVAILABLE = "unavailable"

EngineProvider = Callable[[], Awaitable[Any]]
ProcessorFactory = Callable[..., Any]
ResultsForwarder = Callable[[Any], Awaitable[None]]
SendJson = Callable[[Dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class LiveStreamControl:
    kind: str
    elapsed_seconds: Optional[float] = None
    flag: Optional[bool] = None


def status_payload(status: str) -> Dict[str, Any]:
    """A results-shaped message the native client decodes as a transcription response with no lines."""
    return {
        "status": status,
        "lines": [],
        "buffer_transcription": "",
        "buffer_diarization": "",
        "buffer_translation": "",
        "remaining_time_transcription": 0.0,
        "remaining_time_diarization": 0.0,
        "line_complete": False,
    }


def parse_live_stream_control(text: str) -> Optional[LiveStreamControl]:
    """Parse a clock, capture-state, or live-transcription control message; None for anything else."""
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    kind = payload.get("type")
    if kind == NATIVE_STREAM_CLOCK_TYPE:
        elapsed = payload.get("elapsed_seconds")
        if (
            isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(elapsed)
            or not 0.0 <= elapsed <= MAX_STREAM_SECONDS
        ):
            return None
        return LiveStreamControl(kind=kind, elapsed_seconds=float(elapsed))
    if kind == NATIVE_CAPTURE_STATE_TYPE:
        paused = payload.get("paused")
        if not isinstance(paused, bool):
            return None
        return LiveStreamControl(kind=kind, flag=paused)
    if kind == NATIVE_LIVE_TRANSCRIPTION_TYPE:
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            return None
        return LiveStreamControl(kind=kind, flag=enabled)
    return None


class ProcessorSampleMap:
    """Translate one processor's sample positions into session sample positions.

    A processor can start partway through a session (live transcription enabled mid-recording) and can skip session samples it never processes (audio flushed straight to the recorder on pause), so each processor keeps its own piecewise base. Queried values are exclusive chunk ends, so a chunk ending exactly at a skip point keeps the earlier base.
    """

    def __init__(self, session_sample_at_start: int) -> None:
        self._thresholds: List[int] = [0]
        self._bases: List[int] = [session_sample_at_start]

    def record_skip(self, processor_sample: int, skipped_samples: int) -> None:
        if skipped_samples <= 0:
            return
        base = self._bases[-1] + skipped_samples
        if processor_sample <= self._thresholds[-1]:
            self._bases[-1] = base
            return
        self._thresholds.append(processor_sample)
        self._bases.append(base)

    def session_sample_for_end(self, processor_sample_end: int) -> int:
        index = max(0, bisect.bisect_left(self._thresholds, processor_sample_end) - 1)
        return self._bases[index] + processor_sample_end


class LiveStreamSession:
    """Owns one audio socket's recording, clock anchors, pause state, and optional live processor."""

    def __init__(
        self,
        *,
        meeting_recorder: Any,
        audio_source: Optional[str],
        input_format: str,
        send_json: SendJson,
        engine_provider: EngineProvider,
        processor_factory: ProcessorFactory,
        results_forwarder: ResultsForwarder,
    ) -> None:
        self.meeting_recorder = meeting_recorder
        self.audio_source = audio_source
        self.input_format = input_format
        self._send_json = send_json
        self._engine_provider = engine_provider
        self._processor_factory = processor_factory
        self._results_forwarder = results_forwarder
        self.clock = StreamClock(PCM_SAMPLE_RATE)
        self.processor: Any = None
        self.results_task: Optional[asyncio.Task] = None
        self.bytes_received = 0
        self.is_capture_paused = False
        self._live_requested = False
        self._sample_map: Optional[ProcessorSampleMap] = None
        self._pending_byte = b""
        self._starting_processor: Any = None
        self._enable_task: Optional[asyncio.Task] = None
        self._retiring_tasks: Set[asyncio.Task] = set()

    @property
    def samples_received(self) -> int:
        return self.bytes_received // PCM_BYTES_PER_SAMPLE

    @property
    def is_live(self) -> bool:
        return self.processor is not None

    @property
    def uses_live_engine(self) -> bool:
        """True while this session transcribes live, is starting to, or is still draining a retired processor."""
        return (
            self.processor is not None
            or self._live_requested
            or self._starting_processor is not None
            or bool(self._retiring_tasks)
        )

    @property
    def supports_record_only(self) -> bool:
        return self.input_format == "pcm"

    async def start_live(self) -> bool:
        """Start live transcription inline at connect; False when the engine is unavailable."""
        self._live_requested = True
        outcome = await self._enable_live()
        if outcome != _ENABLED:
            self._live_requested = False
        return outcome == _ENABLED

    async def _enable_live(self) -> str:
        if self.processor is not None:
            return _ENABLED
        engine = await self._engine_provider()
        if engine is None:
            return _UNAVAILABLE
        asr = getattr(engine, "asr", None)
        if asr is not None and hasattr(asr, "ensure_model_ready"):
            await asyncio.to_thread(asr.ensure_model_ready)
        if not self._live_requested:
            return _ABANDONED
        processor = self._processor_factory(
            transcription_engine=engine,
            input_format=self.input_format,
            meeting_recorder=self.meeting_recorder,
            audio_source=self.audio_source,
        )
        self._starting_processor = processor
        if asr is not None and hasattr(asr, "new_model_to_stack"):
            asyncio.create_task(asyncio.to_thread(asr.new_model_to_stack))
        try:
            results_generator = await processor.create_tasks()
        except Exception:
            self._starting_processor = None
            await processor.cleanup()
            raise
        self._starting_processor = None
        if not self._live_requested:
            await processor.cleanup()
            return _ABANDONED
        if self.supports_record_only:
            sample_map = ProcessorSampleMap(self.samples_received)
            clock = self.clock
            self._sample_map = sample_map
            processor.timeline_seconds_for_sample = lambda sample_end: clock.timeline_seconds_for_sample(
                sample_map.session_sample_for_end(sample_end)
            )
            if self._pending_byte:
                processor.pcm_buffer.extend(self._pending_byte)
                self._pending_byte = b""
        self.processor = processor
        self.results_task = asyncio.create_task(self._results_forwarder(results_generator))
        return _ENABLED

    def request_live(self) -> None:
        """Turn live transcription on mid-recording without blocking the receive loop."""
        self._live_requested = True
        if self.processor is not None:
            return
        if self._enable_task is not None and not self._enable_task.done():
            return
        self._enable_task = asyncio.create_task(self._enable_live_in_background())

    async def _enable_live_in_background(self) -> None:
        while True:
            try:
                outcome = await self._enable_live()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error("Enabling live transcription failed: %s", error, exc_info=True)
                outcome = _UNAVAILABLE
            if outcome == _ENABLED:
                return
            if outcome == _ABANDONED:
                if self._live_requested:
                    continue
                return
            break
        if not self._live_requested:
            return
        self._live_requested = False
        try:
            await self._send_json(status_payload(LIVE_TRANSCRIPTION_UNAVAILABLE_STATUS))
        except Exception as error:
            logger.warning("Could not report unavailable live transcription: %s", error)

    def disable_live(self) -> None:
        """Turn live transcription off mid-recording; audio keeps flowing to the recorder with no gap."""
        self._live_requested = False
        if not self.supports_record_only or self.processor is None:
            return
        processor = self.processor
        results_task = self.results_task
        self.processor = None
        self.results_task = None
        self._sample_map = None
        self._write_record_only(processor.take_unhandled_pcm(include_partial_sample=True))
        task = asyncio.create_task(self._retire_processor(processor, results_task))
        self._retiring_tasks.add(task)
        task.add_done_callback(self._retiring_tasks.discard)

    async def _retire_processor(self, processor: Any, results_task: Optional[asyncio.Task]) -> None:
        try:
            await processor.process_audio(b"")
            if results_task is not None:
                await asyncio.wait({results_task}, timeout=RETIRING_PROCESSOR_DRAIN_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error("Retiring live processor failed: %s", error, exc_info=True)
        finally:
            if results_task is not None and not results_task.done():
                results_task.cancel()
            try:
                await processor.cleanup()
            except Exception as error:
                logger.error("Live processor cleanup failed: %s", error, exc_info=True)

    async def handle_audio(self, data: bytes) -> None:
        if self.processor is not None:
            self.bytes_received += len(data)
            await self.processor.process_audio(data)
            return
        if not data or not self.supports_record_only:
            return
        self.bytes_received += len(data)
        self._write_record_only(data)

    def _write_record_only(self, data: bytes) -> None:
        if not data:
            return
        combined = self._pending_byte + bytes(data)
        aligned = len(combined) - (len(combined) % PCM_BYTES_PER_SAMPLE)
        self._pending_byte = combined[aligned:]
        if aligned:
            self._write_recorder(combined[:aligned])

    def _write_recorder(self, pcm: bytes) -> None:
        if self.meeting_recorder is None or not pcm:
            return
        try:
            self.meeting_recorder.write_audio_chunk(pcm)
        except Exception as error:
            logger.error("Failed to write audio chunk to meeting recorder: %s", error, exc_info=True)

    def set_native_stream_offset_seconds(self, offset_seconds: float) -> None:
        """Apply a native_stream_timing control: anchor the clock and open a recorder timeline range."""
        if not math.isfinite(offset_seconds) or offset_seconds < 0.0:
            raise ValueError("native stream offset must be a finite non-negative value")
        self.clock.add_anchor(self.samples_received, offset_seconds)
        if self.processor is not None:
            self.processor.set_native_stream_offset_seconds(offset_seconds)
        elif self.meeting_recorder is not None:
            self.meeting_recorder.set_stream_timeline_origin_seconds(
                self.meeting_recorder.timeline_offset_seconds + offset_seconds
            )

    def _reanchor_empty_recorder_range(self, elapsed_seconds: float) -> None:
        """The first clock marker carries the true capture time of the first sample; native capture can start seconds after the timing control."""
        if self.meeting_recorder is None:
            return
        reanchored = self.meeting_recorder.reanchor_empty_stream_timeline_range(
            self.meeting_recorder.timeline_offset_seconds + elapsed_seconds
        )
        if reanchored and self.processor is not None:
            self.processor.native_stream_offset_seconds = elapsed_seconds

    async def set_capture_paused(self, paused: bool) -> None:
        if paused == self.is_capture_paused:
            return
        self.is_capture_paused = paused
        if not paused:
            return
        self.flush_pending_audio()
        if self.processor is not None:
            await self.processor.begin_capture_pause()

    def flush_pending_audio(self) -> None:
        """Write audio the live processor has buffered but not handled, so pause and teardown never drop it."""
        if not self.supports_record_only or self.processor is None:
            return
        pcm = self.processor.take_unhandled_pcm()
        if not pcm:
            return
        if self._sample_map is not None:
            self._sample_map.record_skip(self.processor.total_pcm_samples, len(pcm) // PCM_BYTES_PER_SAMPLE)
        self._write_recorder(pcm)

    async def handle_control(self, text: str) -> Optional[str]:
        """Apply a session control message; returns its type, or None when the text is not one."""
        control = parse_live_stream_control(text)
        if control is None:
            return None
        if control.kind == NATIVE_STREAM_CLOCK_TYPE and control.elapsed_seconds is not None:
            if self.clock.add_anchor(self.samples_received, control.elapsed_seconds):
                self._reanchor_empty_recorder_range(control.elapsed_seconds)
        elif control.kind == NATIVE_CAPTURE_STATE_TYPE:
            await self.set_capture_paused(bool(control.flag))
        elif control.kind == NATIVE_LIVE_TRANSCRIPTION_TYPE and self.supports_record_only:
            if control.flag:
                self.request_live()
            else:
                self.disable_live()
        return control.kind

    async def cleanup(self) -> None:
        self._live_requested = False
        pending: List[asyncio.Task] = []
        if self._enable_task is not None and not self._enable_task.done():
            self._enable_task.cancel()
            pending.append(self._enable_task)
        for task in list(self._retiring_tasks):
            task.cancel()
            pending.append(task)
        if self.results_task is not None and not self.results_task.done():
            self.results_task.cancel()
            pending.append(self.results_task)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for processor in (self.processor, self._starting_processor):
            if processor is None:
                continue
            try:
                await processor.cleanup()
            except Exception as error:
                logger.error("Live processor cleanup failed: %s", error, exc_info=True)
        self.processor = None
        self._starting_processor = None
        self.results_task = None
        self._sample_map = None
