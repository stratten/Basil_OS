import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

from api.services.live_transcription.live_stream_session import (
    LIVE_TRANSCRIPTION_UNAVAILABLE_STATUS,
    LiveStreamSession,
)

from .fakes import settle


class Recorder:
    def __init__(self) -> None:
        self.chunks: List[bytes] = []
        self.timeline_offset_seconds = 0.0

    def write_audio_chunk(self, pcm: bytes) -> None:
        self.chunks.append(bytes(pcm))

    def set_stream_timeline_origin_seconds(self, origin: float) -> None:
        pass

    @property
    def written(self) -> bytes:
        return b"".join(self.chunks)


class Processor:
    def __init__(self, **kwargs: Any) -> None:
        self.pcm_buffer = bytearray()
        self.total_pcm_samples = 0
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
            await self._results.put(None)
            return
        self.pcm_buffer.extend(data)

    def take_unhandled_pcm(self, include_partial_sample: bool = False) -> bytes:
        pcm = bytes(self.pcm_buffer)
        self.pcm_buffer.clear()
        return pcm

    def set_native_stream_offset_seconds(self, offset: float) -> None:
        pass

    async def begin_capture_pause(self) -> None:
        pass

    async def cleanup(self) -> None:
        pass


class Cloud:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.fed: List[bytes] = []
        self.started = False
        self.stopped = 0

    def start(self) -> None:
        self.started = True

    def feed(self, pcm: bytes) -> None:
        self.fed.append(bytes(pcm))

    async def stop(self) -> None:
        self.stopped += 1

    def fail(self, reason: str) -> None:
        self.kwargs["on_failure"](reason)


def build(*, input_format: str = "pcm", cloud_returns: str = "cloud", engine: Any = SimpleNamespace(asr=None)) -> SimpleNamespace:
    harness = SimpleNamespace(recorder=Recorder(), sent=[], processors=[], clouds=[], engine_calls=0, factory_calls=0)

    async def send_json(payload: Dict[str, Any]) -> None:
        harness.sent.append(payload)

    async def engine_provider() -> Any:
        harness.engine_calls += 1
        return engine

    def processor_factory(**kwargs: Any) -> Processor:
        processor = Processor(**kwargs)
        harness.processors.append(processor)
        return processor

    def cloud_factory(**kwargs: Any) -> Any:
        harness.factory_calls += 1
        if cloud_returns == "none":
            return None
        if cloud_returns == "raise":
            raise RuntimeError("cannot plan")
        cloud = Cloud(**kwargs)
        harness.clouds.append(cloud)
        return cloud

    async def forwarder(results) -> None:
        async for _ in results:
            pass

    harness.session = LiveStreamSession(
        meeting_recorder=harness.recorder,
        audio_source="Microphone",
        input_format=input_format,
        send_json=send_json,
        engine_provider=engine_provider,
        processor_factory=processor_factory,
        results_forwarder=forwarder,
        cloud_factory=cloud_factory,
    )
    return harness


def test_a_cloud_session_replaces_the_local_engine_and_receives_every_aligned_sample() -> None:
    async def run() -> None:
        harness = build()
        assert await harness.session.start_live() is True
        cloud = harness.clouds[0]
        assert cloud.started is True and harness.engine_calls == 0 and harness.processors == []
        assert harness.session.is_cloud_live is True and harness.session.uses_live_engine is False
        await harness.session.handle_audio(b"\x01\x02\x03")
        await harness.session.handle_audio(b"\x04\x05")
        assert harness.recorder.written == b"\x01\x02\x03\x04"
        assert b"".join(cloud.fed) == b"\x01\x02\x03\x04"
        assert cloud.kwargs["base_sample"] == 0 and cloud.kwargs["meeting_recorder"] is harness.recorder
        await harness.session.cleanup()

    asyncio.run(run())


def test_a_mid_recording_start_reports_the_samples_already_recorded_as_its_base() -> None:
    async def run() -> None:
        harness = build()
        await harness.session.handle_audio(b"\x00\x00" * 1600 + b"\x07")
        harness.session.request_live()
        await settle()
        assert harness.clouds[0].kwargs["base_sample"] == 1600
        await harness.session.handle_audio(b"\x08")
        assert harness.clouds[0].fed == [b"\x07\x08"]
        await harness.session.cleanup()

    asyncio.run(run())


def test_no_plan_or_a_planning_error_uses_the_local_engine() -> None:
    async def run(mode: str) -> SimpleNamespace:
        harness = build(cloud_returns=mode)
        assert await harness.session.start_live() is True
        assert harness.session.is_cloud_live is False and len(harness.processors) == 1
        await harness.session.cleanup()
        return harness

    assert asyncio.run(run("none")).factory_calls == 1
    assert asyncio.run(run("raise")).factory_calls == 1


def test_browser_streams_never_use_cloud_transcription() -> None:
    async def run() -> None:
        harness = build(input_format="webm")
        assert await harness.session.start_live() is True
        assert harness.factory_calls == 0 and len(harness.processors) == 1
        await harness.session.cleanup()

    asyncio.run(run())


def test_a_cloud_failure_hands_live_transcription_to_the_local_engine_without_retrying_the_cloud() -> None:
    async def run() -> None:
        harness = build()
        await harness.session.start_live()
        await harness.session.handle_audio(b"\x01\x00" * 100)
        harness.clouds[0].fail("Deepgram closed the connection.")
        await settle(12)
        assert harness.session.is_cloud_live is False and harness.session.is_live is True
        assert harness.engine_calls == 1 and len(harness.processors) == 1
        await harness.session.handle_audio(b"\x02\x00" * 100)
        assert bytes(harness.processors[0].pcm_buffer) == b"\x02\x00" * 100
        assert len(harness.clouds[0].fed) == 1
        harness.session.disable_live()
        harness.session.request_live()
        await settle(12)
        assert harness.factory_calls == 1
        await harness.session.cleanup()
        assert harness.clouds[0].stopped == 1

    asyncio.run(run())


def test_a_late_failure_from_a_replaced_cloud_session_is_ignored() -> None:
    async def run() -> None:
        harness = build()
        await harness.session.start_live()
        first = harness.clouds[0]
        harness.session.disable_live()
        await settle()
        harness.session.request_live()
        await settle()
        second = harness.clouds[1]
        first.fail("old session died")
        await settle(12)
        assert harness.session.is_cloud_live is True and harness.processors == []
        await harness.session.cleanup()
        assert second.stopped == 1

    asyncio.run(run())


def test_turning_live_transcription_off_stops_the_cloud_but_keeps_recording_and_turning_it_on_starts_a_new_one() -> None:
    async def run() -> None:
        harness = build()
        await harness.session.start_live()
        await harness.session.handle_audio(b"\x01\x00" * 50)
        harness.session.disable_live()
        await settle()
        assert harness.clouds[0].stopped == 1 and harness.session.is_cloud_live is False
        await harness.session.handle_audio(b"\x02\x00" * 50)
        assert harness.recorder.written == b"\x01\x00" * 50 + b"\x02\x00" * 50
        assert len(harness.clouds[0].fed) == 1
        harness.session.request_live()
        await settle()
        assert len(harness.clouds) == 2 and harness.clouds[1].kwargs["base_sample"] == 100
        await harness.session.cleanup()

    asyncio.run(run())


def test_drain_cloud_stops_each_session_once_and_cleanup_is_then_a_no_op() -> None:
    async def run() -> None:
        harness = build()
        await harness.session.start_live()
        await harness.session.drain_cloud()
        await harness.session.drain_cloud()
        await harness.session.cleanup()
        assert harness.clouds[0].stopped == 1 and harness.session.is_cloud_live is False

    asyncio.run(run())


def test_when_the_cloud_fails_and_no_local_engine_exists_the_unavailable_status_is_sent() -> None:
    async def run() -> None:
        harness = build(engine=None)
        await harness.session.start_live()
        harness.clouds[0].fail("Deepgram closed the connection.")
        await settle(12)
        assert [payload["status"] for payload in harness.sent] == [LIVE_TRANSCRIPTION_UNAVAILABLE_STATUS]
        await harness.session.cleanup()

    asyncio.run(run())
