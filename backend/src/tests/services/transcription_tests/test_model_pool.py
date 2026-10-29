"""Tests for the live-transcription pre-warmed model pool."""
import asyncio
import threading
import time

from api.services.whisper_live_core.simul_whisper.model_pool import ModelPool


def test_pop_returns_preloaded_instance_without_loading_again():
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return f"model-{calls}"

    pool = ModelPool(loader=loader, initial_count=1)

    assert pool.pop() == "model-1"
    assert calls == 1


def test_pop_loads_when_pool_is_empty():
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return f"model-{calls}"

    pool = ModelPool(loader=loader)

    assert pool.pop() == "model-1"
    assert calls == 1


def test_ensure_ready_does_not_load_when_an_instance_is_available():
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return f"model-{calls}"

    pool = ModelPool(loader=loader, initial_count=1)
    pool.ensure_ready()

    assert calls == 1
    assert pool.pop() == "model-1"


def test_ensure_ready_loads_once_for_an_empty_pool():
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return f"model-{calls}"

    pool = ModelPool(loader=loader)
    pool.ensure_ready()

    assert calls == 1
    assert pool.pop() == "model-1"
    assert calls == 1


def test_each_ensure_ready_call_reserves_a_distinct_instance():
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return f"model-{calls}"

    pool = ModelPool(loader=loader, initial_count=1)
    pool.ensure_ready()
    pool.ensure_ready()

    assert calls == 2
    assert {pool.pop(), pool.pop()} == {"model-1", "model-2"}


def test_refill_one_appends_a_model_without_consuming_existing_instance():
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return f"model-{calls}"

    pool = ModelPool(loader=loader, initial_count=1)
    pool.refill_one()

    assert pool.pop() == "model-2"
    assert pool.pop() == "model-1"
    assert calls == 2


def test_ensure_ready_runs_in_a_worker_without_blocking_event_loop():
    load_started = threading.Event()

    def loader():
        load_started.set()
        time.sleep(0.1)
        return "model"

    async def ensure_ready_while_event_loop_runs() -> int:
        pool = ModelPool(loader=loader)
        task = asyncio.create_task(asyncio.to_thread(pool.ensure_ready))
        ticks = 0
        while not task.done():
            ticks += 1
            await asyncio.sleep(0)
        await task
        return ticks

    ticks = asyncio.run(ensure_ready_while_event_loop_runs())

    assert load_started.is_set()
    assert ticks > 1
