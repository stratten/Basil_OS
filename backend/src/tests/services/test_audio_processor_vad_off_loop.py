"""Voice-activity detection runs torch inference, so it must not run on the event loop thread."""

import asyncio
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from api.services.whisper_live_core.audio_processor import AudioProcessor


def _fake_processor(vac) -> SimpleNamespace:
    enqueued: list[int] = []

    async def enqueue_active_audio(pcm_array, sample_end) -> None:
        enqueued.append(len(pcm_array))

    bytes_per_sample = 2
    sample_rate = 16000
    return SimpleNamespace(
        args=SimpleNamespace(vac=True, transcription=True, diarization=False),
        vac=vac,
        _vad_lock=asyncio.Lock(),
        pcm_buffer=bytearray(b"\x00\x01" * sample_rate),
        bytes_per_sec=sample_rate * bytes_per_sample,
        max_bytes_per_sec=sample_rate * bytes_per_sample,
        bytes_per_sample=bytes_per_sample,
        meeting_recorder=None,
        _commit_watchdog=SimpleNamespace(
            note_audio_received=lambda now: None,
            should_warn=lambda now: None,
            commit_count=0,
        ),
        audio_source_name="test",
        handled_pcm_chunk_count=0,
        enqueued_active_audio_count=0,
        total_pcm_samples=0,
        current_silence=None,
        convert_pcm_to_float=lambda raw: np.zeros(len(raw) // bytes_per_sample, dtype=np.float32),
        _calculate_pcm_stats=lambda pcm_array: (0.0, 0.0),
        _enqueue_active_audio=enqueue_active_audio,
        _should_log_pcm_diagnostic=lambda count: False,
        _describe_vad_result=lambda res: "none",
        enqueued=enqueued,
    )


@pytest.mark.asyncio
async def test_vad_inference_runs_on_a_worker_thread_and_the_loop_keeps_ticking() -> None:
    loop_thread = threading.current_thread()
    seen_threads: list[threading.Thread] = []
    release = threading.Event()

    def slow_vad(pcm_array):
        seen_threads.append(threading.current_thread())
        # A blocked loop would never get to run the ticker below, so this wait would only end when the loop thread itself is released by the timeout.
        release.wait(timeout=5)
        return None

    fake = _fake_processor(slow_vad)
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1
            if ticks >= 5:
                release.set()

    ticker_task = asyncio.create_task(ticker())
    try:
        await asyncio.wait_for(AudioProcessor.handle_pcm_data(fake), timeout=10)
    finally:
        ticker_task.cancel()

    assert seen_threads and seen_threads[0] is not loop_thread
    assert ticks >= 5
    assert fake.enqueued == [16000]


@pytest.mark.asyncio
async def test_overlapping_chunks_never_run_the_vad_concurrently() -> None:
    active = 0
    max_active = 0
    guard = threading.Lock()

    def tracking_vad(pcm_array):
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        threading.Event().wait(0.05)
        with guard:
            active -= 1
        return None

    fake = _fake_processor(tracking_vad)

    async def one_chunk() -> None:
        fake.pcm_buffer = bytearray(b"\x00\x01" * 16000)
        await AudioProcessor.handle_pcm_data(fake)

    await asyncio.gather(one_chunk(), one_chunk(), one_chunk())

    assert max_active == 1
