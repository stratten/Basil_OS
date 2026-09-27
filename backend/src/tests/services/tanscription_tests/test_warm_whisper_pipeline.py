"""
Unit tests for the shared single-slot Whisper warm cache.

These prove the behaviors retranscription relies on: the model loads once per
key (no per-source reload), a key change evicts + reloads, and the delayed
unload can be cancelled (including implicitly by a cache hit).
"""
import asyncio
import threading

import pytest

from api.services.transcription.local_model.warm_whisper_pipeline import (
    WarmWhisperPipeline,
)


class _Counter:
    def __init__(self):
        self.calls = 0

    def make(self, value):
        def loader():
            self.calls += 1
            return value
        return loader


@pytest.fixture(autouse=True)
def _clean_cache():
    """Start and end each test with an empty, unscheduled cache."""
    WarmWhisperPipeline.cancel_unload()
    WarmWhisperPipeline.unload()
    yield
    WarmWhisperPipeline.cancel_unload()
    WarmWhisperPipeline.unload()


def test_same_key_loads_once_and_reuses():
    counter = _Counter()
    obj = object()

    first = WarmWhisperPipeline.get_or_load("k1", "huggingface", "cpu", counter.make(obj))
    second = WarmWhisperPipeline.get_or_load("k1", "huggingface", "cpu", counter.make(object()))

    assert first is obj
    assert second is obj  # reused, loader for second call never ran
    assert counter.calls == 1
    assert WarmWhisperPipeline.matches("k1")
    assert WarmWhisperPipeline.current() == (obj, "huggingface", "cpu")


def test_key_change_evicts_and_reloads():
    counter = _Counter()
    a = object()
    b = object()

    WarmWhisperPipeline.get_or_load("k1", "huggingface", "cpu", counter.make(a))
    second = WarmWhisperPipeline.get_or_load("k2", "faster_whisper", "cpu", counter.make(b))

    assert second is b
    assert counter.calls == 2
    assert WarmWhisperPipeline.matches("k2")
    assert not WarmWhisperPipeline.matches("k1")
    assert WarmWhisperPipeline.current()[1] == "faster_whisper"


def test_unload_clears_state():
    WarmWhisperPipeline.get_or_load("k1", "huggingface", "cpu", lambda: object())
    assert WarmWhisperPipeline.is_loaded()

    WarmWhisperPipeline.unload()

    assert not WarmWhisperPipeline.is_loaded()
    assert WarmWhisperPipeline.current() == (None, None, None)
    assert WarmWhisperPipeline.current_key() is None


def test_loader_returning_none_raises():
    with pytest.raises(RuntimeError):
        WarmWhisperPipeline.get_or_load("k1", "huggingface", "cpu", lambda: None)
    assert not WarmWhisperPipeline.is_loaded()


def test_schedule_unload_zero_is_immediate():
    WarmWhisperPipeline.get_or_load("k1", "huggingface", "cpu", lambda: object())
    WarmWhisperPipeline.schedule_unload(0)
    assert not WarmWhisperPipeline.is_loaded()


def test_scheduled_unload_can_be_cancelled():
    async def scenario():
        WarmWhisperPipeline.get_or_load("k1", "huggingface", "cpu", lambda: object())
        WarmWhisperPipeline.schedule_unload(1)
        WarmWhisperPipeline.cancel_unload()
        await asyncio.sleep(1.2)
        return WarmWhisperPipeline.is_loaded()

    assert asyncio.run(scenario()) is True


def test_cache_hit_cancels_pending_unload():
    obj = object()

    async def scenario():
        WarmWhisperPipeline.get_or_load("k1", "huggingface", "cpu", lambda: obj)
        WarmWhisperPipeline.schedule_unload(1)
        # A hit for the same key must cancel the pending unload.
        again = WarmWhisperPipeline.get_or_load("k1", "huggingface", "cpu", lambda: object())
        await asyncio.sleep(1.2)
        return again, WarmWhisperPipeline.is_loaded()

    again, loaded = asyncio.run(scenario())
    assert again is obj
    assert loaded is True


def test_unload_waits_for_an_active_inference_lease():
    obj = object()
    lease_acquired = threading.Event()
    release_lease = threading.Event()
    unload_finished = threading.Event()

    def run_inference():
        with WarmWhisperPipeline.acquire_inference_lease(
            "k1",
            "huggingface",
            "cpu",
            lambda: obj,
            priority="live",
        ) as leased:
            assert leased is obj
            lease_acquired.set()
            release_lease.wait(timeout=2)

    def unload():
        WarmWhisperPipeline.unload()
        unload_finished.set()

    inference_thread = threading.Thread(target=run_inference)
    inference_thread.start()
    assert lease_acquired.wait(timeout=1)

    unload_thread = threading.Thread(target=unload)
    unload_thread.start()
    assert not unload_finished.wait(timeout=0.1)
    assert WarmWhisperPipeline.current_object() is obj

    release_lease.set()
    inference_thread.join(timeout=2)
    unload_thread.join(timeout=2)
    assert unload_finished.is_set()
    assert WarmWhisperPipeline.current_object() is None


def test_waiting_live_lease_runs_before_background_lease():
    lease_acquired = threading.Event()
    release_lease = threading.Event()
    execution_order = []

    def initial_background():
        with WarmWhisperPipeline.acquire_inference_lease(
            "k1",
            "huggingface",
            "cpu",
            object,
            priority="background",
        ):
            lease_acquired.set()
            release_lease.wait(timeout=2)

    def queued(priority):
        with WarmWhisperPipeline.acquire_inference_lease(
            "k1",
            "huggingface",
            "cpu",
            object,
            priority=priority,
        ):
            execution_order.append(priority)

    initial_thread = threading.Thread(target=initial_background)
    initial_thread.start()
    assert lease_acquired.wait(timeout=1)

    background_thread = threading.Thread(target=queued, args=("background",))
    live_thread = threading.Thread(target=queued, args=("live",))
    background_thread.start()
    live_thread.start()
    with WarmWhisperPipeline._condition:
        while (
            WarmWhisperPipeline._waiting_live_leases
            + WarmWhisperPipeline._waiting_background_leases
            < 2
        ):
            WarmWhisperPipeline._condition.wait(timeout=1)
    release_lease.set()

    initial_thread.join(timeout=2)
    background_thread.join(timeout=2)
    live_thread.join(timeout=2)
    assert execution_order == ["live", "background"]
