"""Tests for AudioProcessor sample-indexed timelines, capture pause, and unhandled PCM handoff."""

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from api.services.whisper_live_core.audio_processor import AudioProcessor, PcmSpan, get_all_from_queue


def test_queue_drain_merges_pcm_spans_and_keeps_the_last_end() -> None:
    async def run():
        queue: asyncio.Queue = asyncio.Queue()
        await queue.put(PcmSpan(np.ones(3, dtype=np.float32), 3))
        await queue.put(PcmSpan(np.zeros(2, dtype=np.float32), 5))
        return await get_all_from_queue(queue)
    merged = asyncio.run(run())
    assert isinstance(merged, PcmSpan)
    assert merged.sample_end == 5
    assert merged.samples.tolist() == [1.0, 1.0, 1.0, 0.0, 0.0]


def test_timeline_end_prefers_the_clock_mapping_then_falls_back() -> None:
    fake = SimpleNamespace(
        timeline_seconds_for_sample=lambda sample: 42.0 + sample / 16000,
        native_stream_offset_seconds=7.0,
        sample_rate=16000,
    )
    assert AudioProcessor._timeline_end_for_sample(fake, 16000) == pytest.approx(43.0)
    fake.timeline_seconds_for_sample = lambda sample: None
    assert AudioProcessor._timeline_end_for_sample(fake, 16000) == pytest.approx(8.0)
    fake.timeline_seconds_for_sample = None
    assert AudioProcessor._timeline_end_for_sample(fake, 16000) == pytest.approx(8.0)


def test_take_unhandled_pcm_is_sample_aligned_unless_partial_requested() -> None:
    fake = SimpleNamespace(pcm_buffer=bytearray(b"\x01\x02\x03"), bytes_per_sample=2)
    assert AudioProcessor.take_unhandled_pcm(fake) == b"\x01\x02"
    assert fake.pcm_buffer == bytearray(b"\x03")
    assert AudioProcessor.take_unhandled_pcm(fake, include_partial_sample=True) == b"\x03"
    assert fake.pcm_buffer == bytearray()
    assert AudioProcessor.take_unhandled_pcm(fake) == b""


def test_begin_capture_pause_resets_vad_and_starts_silence_only_when_running() -> None:
    calls = []

    async def begin_silence() -> None:
        calls.append("silence")

    running = SimpleNamespace(beg_loop=1.0, vac=SimpleNamespace(triggered=True, temp_end=5), _begin_silence=begin_silence)
    asyncio.run(AudioProcessor.begin_capture_pause(running))
    assert calls == ["silence"]
    assert running.vac.triggered is False
    assert running.vac.temp_end == 0

    not_started = SimpleNamespace(beg_loop=None, vac=SimpleNamespace(triggered=True, temp_end=5), _begin_silence=begin_silence)
    asyncio.run(AudioProcessor.begin_capture_pause(not_started))
    no_vad = SimpleNamespace(beg_loop=1.0, vac=None, _begin_silence=begin_silence)
    asyncio.run(AudioProcessor.begin_capture_pause(no_vad))
    assert calls == ["silence"]


def test_enqueue_tags_transcription_audio_with_its_sample_end() -> None:
    async def run():
        fake = SimpleNamespace(
            transcription_queue=asyncio.Queue(),
            diarization_queue=None,
            enqueued_active_audio_count=0,
            args=SimpleNamespace(diarization=False),
            _should_log_pcm_diagnostic=lambda count: False,
        )
        await AudioProcessor._enqueue_active_audio(fake, np.ones(4, dtype=np.float32), 1234)
        return await fake.transcription_queue.get()
    item = asyncio.run(run())
    assert isinstance(item, PcmSpan)
    assert item.sample_end == 1234
    assert item.samples.size == 4
