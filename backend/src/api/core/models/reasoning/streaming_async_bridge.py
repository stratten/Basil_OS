"""
Bridge blocking synchronous iterators into async generators without starving the event loop.

Each call creates its own asyncio.Queue and worker thread scope — no global queues or shared
buffers across concurrent agent/model streams.

Synchronization uses asyncio.run_coroutine_threadsafe(...).result() on puts so a bounded queue
provides backpressure when the async consumer is slower than the sync producer.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from typing import Any, AsyncIterator, Callable, Iterator, Optional, TypeVar

logger = logging.getLogger(__name__)

# How often a worker blocked on a full queue checks whether the async consumer has gone away.
CONSUMER_POLL_SECONDS = 0.1

T = TypeVar("T")


class _StreamCompleteSentinel:
    """Sentinel marking normal end of a synchronous iterator."""

    __slots__ = ()


_STREAM_COMPLETE = _StreamCompleteSentinel()


class _StreamFailure:
    """Carries an exception from the worker thread to the async consumer."""

    __slots__ = ("exc",)

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc


def max_queue_size(requested: int) -> int:
    """Clamp queue size so maxsize is always >= 1 (asyncio.Queue maxsize=0 is unbounded)."""
    if requested < 1:
        return 1
    return requested


async def async_iter_sync_stream(
    sync_iter_factory: Callable[[], Iterator[T]],
    *,
    queue_maxsize: int = 32,
    thread_name: Optional[str] = None,
) -> AsyncIterator[T]:
    """Yield items from a blocking synchronous iterator without blocking the event loop.

    The factory is invoked once in a worker thread; each item is forwarded through a bounded
    queue. Ordering matches the source iterator. Worker exceptions are re-raised on the async
    caller. Normal completion is signaled with a sentinel.

    Cancellation: when the async consumer stops (normal end, an error, ``aclose()``, or task
    cancellation) the worker is told. It stops after the item it is producing, closes the sync
    iterator so anything the iterator holds (for a local model, the native execution lock) is
    released, and never waits on a queue nobody drains. A sync read already blocked inside the
    iterator is not interrupted; the worker stops as soon as that read returns. The thread is a
    daemon so process exit is not blocked.

    Args:
        sync_iter_factory: Zero-argument callable returning a fresh synchronous iterator (e.g.
            ``lambda: http_streamer.stream_responses_api(...)``).
        queue_maxsize: Maximum queued items before the worker blocks on put (backpressure).
        thread_name: Optional label for debugging concurrent streams.

    Yields:
        Items from the synchronous iterator in order.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=max_queue_size(queue_maxsize))

    consumer_gone = threading.Event()

    def put(payload: Any) -> bool:
        """Hand one payload to the async consumer. False once the consumer has gone away, so the worker stops instead of waiting on a full queue nobody drains."""
        pending = asyncio.run_coroutine_threadsafe(queue.put(payload), loop)
        while True:
            try:
                pending.result(timeout=CONSUMER_POLL_SECONDS)
                return True
            except concurrent.futures.TimeoutError:
                if consumer_gone.is_set() or loop.is_closed():
                    pending.cancel()
                    return False

    def worker() -> None:
        iterator: Optional[Iterator[T]] = None
        try:
            iterator = iter(sync_iter_factory())
            for item in iterator:
                if consumer_gone.is_set() or not put(item):
                    break
            else:
                put(_STREAM_COMPLETE)
        except BaseException as exc:
            # Propagate to async side; log at debug to avoid duplicate error noise with callers.
            logger.debug("async_iter_sync_stream worker failed: %s", exc, exc_info=True)
            try:
                put(_StreamFailure(exc))
            except Exception:
                logger.exception("Failed to deliver stream failure to async queue")
        finally:
            if iterator is not None and hasattr(iterator, "close"):
                try:
                    iterator.close()
                except Exception:
                    logger.debug("Iterator close() raised", exc_info=True)

    name = thread_name or "sync-stream-bridge"
    threading.Thread(target=worker, name=name, daemon=True).start()

    try:
        while True:
            payload = await queue.get()
            if isinstance(payload, _StreamFailure):
                raise payload.exc
            if payload is _STREAM_COMPLETE:
                break
            yield payload
    finally:
        # Runs on a normal end, an error, aclose(), and task cancellation. Without it a worker blocked on a full queue never wakes, and the sync iterator it drives is never closed, which for a local model leaves the native execution lock held forever.
        consumer_gone.set()
