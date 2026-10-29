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
