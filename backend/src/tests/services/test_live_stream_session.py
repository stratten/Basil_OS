"""Tests for the per-socket live stream session (record-only, live toggle, pause, timing)."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from api.services.live_transcription.live_stream_session import (
    LIVE_TRANSCRIPTION_UNAVAILABLE_STATUS,
    LiveStreamSession,
    ProcessorSampleMap,
    parse_live_stream_control,
    status_payload,
)


class FakeRecorder:
    def __init__(self) -> None:
        self.chunks: List[bytes] = []
        self.origins: List[float] = []
        self.timeline_offset_seconds = 0.0

    def write_audio_chunk(self, pcm: bytes) -> None:
        self.chunks.append(bytes(pcm))

    def set_stream_timeline_origin_seconds(self, origin: float) -> None:
        self.origins.append(origin)
        self._chunks_at_origin = len(self.chunks)

    def reanchor_empty_stream_timeline_range(self, origin: float) -> bool:
        if not self.origins or len(self.chunks) != getattr(self, "_chunks_at_origin", 0):
            return False
        self.origins[-1] = origin
        return True

    @property
    def written(self) -> bytes:
        return b"".join(self.chunks)


class FakeProcessor:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.pcm_buffer = bytearray()
        self.total_pcm_samples = 0
        self.offsets: List[float] = []
        self.pause_calls = 0
        self.cleaned = False
        self.stopped = False
        self.timeline_seconds_for_sample = None
        self._results: asyncio.Queue = asyncio.Queue()

    async def create_tasks(self):
        async def results():
            while True:
                item = await self._results.get()
                if item is None:
                    return
                yield item
        return results()

    async def process_audio(self, data: bytes) -> None:
        if not data:
            self.stopped = True
            await self._results.put(None)
            return
        self.pcm_buffer.extend(data)

    def take_unhandled_pcm(self, include_partial_sample: bool = False) -> bytes:
        size = len(self.pcm_buffer)
        if not include_partial_sample:
            size -= size % 2
        pcm = bytes(self.pcm_buffer[:size])
        del self.pcm_buffer[:size]
        return pcm

    def set_native_stream_offset_seconds(self, offset: float) -> None:
        self.offsets.append(offset)

    async def begin_capture_pause(self) -> None:
        self.pause_calls += 1

    async def cleanup(self) -> None:
        self.cleaned = True


def build(input_format: str = "pcm", engine: Any = SimpleNamespace(asr=None), engine_gate: Any = None) -> SimpleNamespace:
    harness = SimpleNamespace(recorder=FakeRecorder(), sent=[], forwarded=[], processors=[])

    async def send_json(payload: Dict[str, Any]) -> None:
        harness.sent.append(payload)

    async def engine_provider() -> Any:
        if engine_gate is not None:
            await engine_gate.wait()
        return engine

    def factory(**kwargs: Any) -> FakeProcessor:
        processor = FakeProcessor(**kwargs)
        harness.processors.append(processor)
        return processor

    async def forwarder(results) -> None:
        async for item in results:
            harness.forwarded.append(item)

    harness.session = LiveStreamSession(
        meeting_recorder=harness.recorder,
        audio_source="Microphone",
        input_format=input_format,
        send_json=send_json,
        engine_provider=engine_provider,
        processor_factory=factory,
        results_forwarder=forwarder,
    )
    return harness


def control(kind: str, **fields: Any) -> str:
    return json.dumps({"type": kind, **fields})


def test_record_only_writes_aligned_pcm_and_carries_the_odd_byte() -> None:
    async def run() -> None:
        harness = build()
        await harness.session.handle_audio(b"\x01\x02\x03")
        assert harness.recorder.written == b"\x01\x02"
        await harness.session.handle_audio(b"\x04")
        assert harness.recorder.written == b"\x01\x02\x03\x04"
        await harness.session.handle_audio(b"")
        assert harness.session.samples_received == 2
        assert harness.processors == []
    asyncio.run(run())


def test_offset_without_processor_anchors_clock_and_opens_recorder_range() -> None:
    async def run() -> None:
        harness = build()
        harness.recorder.timeline_offset_seconds = 5.0
        harness.session.set_native_stream_offset_seconds(2.0)
        assert harness.recorder.origins == [7.0]
        await harness.session.handle_audio(b"\x00" * 32000)
        assert harness.session.clock.timeline_seconds_for_sample(16000) == pytest.approx(3.0)
        with pytest.raises(ValueError):
            harness.session.set_native_stream_offset_seconds(float("nan"))
    asyncio.run(run())


def test_first_clock_marker_reanchors_a_delayed_capture_start() -> None:
    async def run() -> None:
        harness = build()
        harness.recorder.timeline_offset_seconds = 100.0
        harness.session.set_native_stream_offset_seconds(0.15)
        await harness.session.handle_control(control("native_stream_clock", elapsed_seconds=16.2))
        assert harness.recorder.origins == [pytest.approx(116.2)]
        await harness.session.handle_audio(b"\x00" * 32000)
        await harness.session.handle_control(control("native_stream_clock", elapsed_seconds=17.2))
        assert harness.recorder.origins == [pytest.approx(116.2)]
        assert harness.session.clock.timeline_seconds_for_sample(0) == pytest.approx(16.2)
    asyncio.run(run())


def test_start_live_maps_processor_samples_through_the_clock() -> None:
    async def run() -> None:
        harness = build()
        assert await harness.session.start_live() is True
        processor = harness.processors[0]
        assert processor.kwargs["input_format"] == "pcm"
        assert processor.kwargs["meeting_recorder"] is harness.recorder
        await harness.session.handle_control(control("native_stream_clock", elapsed_seconds=10.0))
        assert processor.timeline_seconds_for_sample(16000) == pytest.approx(11.0)
        await harness.session.cleanup()
        assert processor.cleaned is True
    asyncio.run(run())


def test_live_off_then_on_keeps_every_byte_and_maps_the_new_processor() -> None:
    async def run() -> None:
        harness = build()
        session = harness.session
        await session.start_live()
        await session.handle_control(control("native_stream_clock", elapsed_seconds=0.0))
        await session.handle_audio(b"\x00" * 3201)
        assert await session.handle_control(control("native_live_transcription", enabled=False)) == "native_live_transcription"
        await asyncio.gather(*list(session._retiring_tasks))
        first = harness.processors[0]
        assert first.stopped is True and first.cleaned is True
        assert session.is_live is False
        assert len(harness.recorder.written) == 3200
        await session.handle_audio(b"\x00" * 3200)
        assert len(harness.recorder.written) == 6400
        await session.handle_control(control("native_live_transcription", enabled=True))
        await session._enable_task
        second = harness.processors[1]
        assert session.processor is second
        assert bytes(second.pcm_buffer) == b"\x00"
        assert second.timeline_seconds_for_sample(16000) == pytest.approx((3200 + 16000) / 16000)
        await session.cleanup()
    asyncio.run(run())


def test_turning_live_off_while_enabling_abandons_without_a_processor_or_error() -> None:
    async def run() -> None:
        gate = asyncio.Event()
        harness = build(engine_gate=gate)
        harness.session.request_live()
        await asyncio.sleep(0)
        harness.session.disable_live()
        gate.set()
        await harness.session._enable_task
        assert harness.processors == []
        assert harness.session.is_live is False
        assert harness.sent == []
    asyncio.run(run())


def test_unavailable_engine_reports_once_and_clears_the_request() -> None:
    async def run() -> None:
        harness = build(engine=None)
        harness.session.request_live()
        await harness.session._enable_task
        assert harness.sent == [status_payload(LIVE_TRANSCRIPTION_UNAVAILABLE_STATUS)]
        assert harness.session.is_live is False
        assert harness.session._live_requested is False
    asyncio.run(run())


def test_pause_flushes_unhandled_audio_and_shifts_later_samples() -> None:
    async def run() -> None:
        harness = build()
        session = harness.session
        await session.start_live()
        await session.handle_control(control("native_stream_clock", elapsed_seconds=0.0))
        await session.handle_audio(b"\x00" * 1000)
        await session.handle_control(control("native_capture_state", paused=True))
        processor = harness.processors[0]
        assert processor.pause_calls == 1
        assert len(harness.recorder.written) == 1000
        assert processor.timeline_seconds_for_sample(16000) == pytest.approx((16000 + 500) / 16000)
        await session.handle_control(control("native_capture_state", paused=True))
        assert processor.pause_calls == 1
        await session.handle_control(control("native_capture_state", paused=False))
        assert session.is_capture_paused is False
        await session.cleanup()
    asyncio.run(run())


def test_live_toggle_is_ignored_for_browser_webm_streams() -> None:
    async def run() -> None:
        harness = build(input_format="webm")
        await harness.session.start_live()
        await harness.session.handle_control(control("native_live_transcription", enabled=False))
        assert harness.session.is_live is True
        await harness.session.handle_audio(b"")
        assert harness.recorder.written == b""
        await harness.session.cleanup()
    asyncio.run(run())


def test_cleanup_cancels_a_pending_enable() -> None:
    async def run() -> None:
        harness = build(engine_gate=asyncio.Event())
        harness.session.request_live()
        await asyncio.sleep(0)
        await harness.session.cleanup()
        assert harness.session._enable_task.cancelled() is True
        assert harness.processors == []
    asyncio.run(run())


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"type":"other"}',
        '{"type":"native_stream_clock","elapsed_seconds":true}',
        '{"type":"native_stream_clock","elapsed_seconds":NaN}',
        '{"type":"native_stream_clock","elapsed_seconds":-1}',
        '{"type":"native_stream_clock","elapsed_seconds":86400.5}',
        '{"type":"native_capture_state","paused":"yes"}',
        '{"type":"native_live_transcription","enabled":1}',
    ],
)
def test_malformed_controls_are_rejected(text: str) -> None:
    assert parse_live_stream_control(text) is None


def test_processor_sample_map_applies_skips_after_their_position() -> None:
    sample_map = ProcessorSampleMap(100)
    assert sample_map.session_sample_for_end(50) == 150
    sample_map.record_skip(50, 10)
    assert sample_map.session_sample_for_end(50) == 150
    assert sample_map.session_sample_for_end(60) == 170
    sample_map.record_skip(50, 5)
    assert sample_map.session_sample_for_end(60) == 175
    sample_map.record_skip(80, 0)
    assert sample_map.session_sample_for_end(90) == 205


def test_status_payload_has_the_fields_the_native_client_requires() -> None:
    payload = status_payload("recording_only")
    assert payload["status"] == "recording_only"
    assert payload["lines"] == []
    assert payload["remaining_time_transcription"] == 0.0
    assert payload["remaining_time_diarization"] == 0.0
