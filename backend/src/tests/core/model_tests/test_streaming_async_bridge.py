"""Tests for bridging blocking synchronous iterators into async iteration."""

from __future__ import annotations

import asyncio
import time

import pytest

from api.core.models.reasoning.streaming_async_bridge import (
    async_iter_sync_stream,
    max_queue_size,
)


def test_max_queue_size_clamps_below_one():
    assert max_queue_size(0) == 1
    assert max_queue_size(-3) == 1


@pytest.mark.asyncio
async def test_async_iter_sync_stream_preserves_order():
    def factory():
        yield from ["a", "b", "c"]

    items: list[str] = []
    async for item in async_iter_sync_stream(factory, queue_maxsize=8):
        items.append(item)
    assert items == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_async_iter_sync_stream_propagates_worker_exception():
    def factory():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        async for _ in async_iter_sync_stream(factory):
            pass


@pytest.mark.asyncio
async def test_async_iter_sync_stream_large_sequence_with_small_queue():
    def factory():
        yield from (str(i) for i in range(50))

    items: list[str] = []
    async for item in async_iter_sync_stream(factory, queue_maxsize=2):
        items.append(item)
    assert items == [str(i) for i in range(50)]


@pytest.mark.asyncio
async def test_async_iter_sync_stream_worker_sleep_does_not_starve_loop():
    """Blocking sleeps run only in the worker thread; the event loop should stay responsive."""

    def factory():
        for i in range(4):
            time.sleep(0.04)
            yield str(i)

    ticker_ticks = 0

    async def ticker():
        nonlocal ticker_ticks
        try:
            while True:
                ticker_ticks += 1
                await asyncio.sleep(0.015)
        except asyncio.CancelledError:
            raise

    tick_task = asyncio.create_task(ticker())
    received: list[str] = []
    try:
        async for chunk in async_iter_sync_stream(factory, queue_maxsize=3):
            received.append(chunk)
    finally:
        tick_task.cancel()
        try:
            await tick_task
        except asyncio.CancelledError:
            pass

    assert received == ["0", "1", "2", "3"]
    assert ticker_ticks >= 8


async def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


def _acquire_and_release(lock, timeout: float = 2.0) -> bool:
    """Take the lock from this thread and give it back, so a lock another thread still owns reports False."""
    if not lock.acquire(True, timeout):
        return False
    lock.release()
    return True


def _lock_holding_stream(lock, closed):
    """The shape of a local model's native stream: it holds the model lock for as long as the generator is alive."""

    def factory():
        with lock:
            try:
                index = 0
                while True:
                    yield index
                    index += 1
            finally:
                closed.set()

    return factory


@pytest.mark.asyncio
async def test_a_consumer_that_closes_early_releases_the_lock_the_stream_holds():
    import threading

    lock = threading.RLock()
    closed = threading.Event()
    stream = async_iter_sync_stream(_lock_holding_stream(lock, closed), queue_maxsize=2)

    assert await stream.__anext__() == 0
    await stream.aclose()

    assert await _wait_until(closed.is_set), "the sync iterator was never closed"
    assert await asyncio.to_thread(_acquire_and_release, lock), "the stream still holds the lock after its consumer left"


@pytest.mark.asyncio
async def test_canceling_the_consumer_task_releases_the_lock_the_stream_holds():
    import threading

    lock = threading.RLock()
    closed = threading.Event()
    reached = asyncio.Event()

    async def consume():
        async for item in async_iter_sync_stream(_lock_holding_stream(lock, closed), queue_maxsize=2):
            if item >= 1:
                reached.set()
                await asyncio.sleep(30)

    task = asyncio.create_task(consume())
    await asyncio.wait_for(reached.wait(), timeout=3.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await _wait_until(closed.is_set), "the sync iterator was never closed"
    assert await asyncio.to_thread(_acquire_and_release, lock), "the stream still holds the lock after its consumer was canceled"


@pytest.mark.asyncio
async def test_a_worker_blocked_on_a_full_queue_wakes_when_the_consumer_goes_away(monkeypatch):
    import threading

    from api.core.models.reasoning import streaming_async_bridge

    monkeypatch.setattr(streaming_async_bridge, "CONSUMER_POLL_SECONDS", 0.02)
    closed = threading.Event()

    def endless():
        try:
            while True:
                yield "x"
        finally:
            closed.set()

    stream = async_iter_sync_stream(endless, queue_maxsize=1)
    assert await stream.__anext__() == "x"
    await asyncio.sleep(0.2)
    await stream.aclose()

    assert await _wait_until(closed.is_set), "the worker stayed blocked on a queue nobody drains"


@pytest.mark.asyncio
async def test_normal_completion_closes_the_iterator_and_loses_no_items():
    import threading

    closed = threading.Event()

    def finite():
        try:
            yield from range(100)
        finally:
            closed.set()

    items = [item async for item in async_iter_sync_stream(finite, queue_maxsize=2)]

    assert items == list(range(100))
    assert await _wait_until(closed.is_set)


@pytest.mark.asyncio
async def test_a_worker_error_after_the_consumer_left_is_dropped_quietly():
    import threading

    finished = threading.Event()

    def fails_after_the_consumer_leaves():
        try:
            yield 1
            time.sleep(0.2)
            raise RuntimeError("late failure")
        finally:
            finished.set()

    stream = async_iter_sync_stream(fails_after_the_consumer_leaves, queue_maxsize=1)
    assert await stream.__anext__() == 1
    await stream.aclose()

    assert await _wait_until(finished.is_set)
