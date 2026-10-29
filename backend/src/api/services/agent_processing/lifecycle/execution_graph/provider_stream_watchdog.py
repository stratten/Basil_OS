"""Silence detection for provider token streams.

A provider stream can go quiet for minutes: the model may be thinking or searching, or the network may have stalled underneath an open connection. Neither produces an error, so without a watchdog the run just appears frozen.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Sequence, Tuple

# Seconds of silence after which the user is told Basil is still waiting. Each threshold fires at most once per silence, so a long stall adds a couple of timeline rows rather than one per second.
QUIET_NOTICE_AFTER_SECONDS: Tuple[float, ...] = (30.0, 90.0)

QuietNotice = Callable[[float], Awaitable[None]]


class ProviderStreamIdleTimeout(RuntimeError):
    """Raised when a provider stream delivers nothing for longer than its idle limit."""

    def __init__(self, idle_seconds: float) -> None:
        super().__init__(f"The model produced no data for {int(idle_seconds)} seconds")
        self.idle_seconds = idle_seconds


async def watch_provider_stream(
    stream: AsyncIterator[Any],
    *,
    on_quiet: Optional[QuietNotice] = None,
    notice_after_seconds: Sequence[float] = QUIET_NOTICE_AFTER_SECONDS,
    idle_timeout_seconds: Optional[float] = None,
    tick_seconds: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
) -> AsyncIterator[Any]:
    """Yield every event from ``stream`` while watching for silence.

    ``on_quiet`` is awaited with the current silence length each time a threshold in ``notice_after_seconds`` is crossed. When ``idle_timeout_seconds`` is set, silence that long cancels the stream and raises ``ProviderStreamIdleTimeout``. Any event, including a keepalive, resets the silence.
    """
    iterator = stream.__aiter__()

    async def _next_event() -> Tuple[bool, Any]:
        try:
            return True, await iterator.__anext__()
        except StopAsyncIteration:
            return False, None

    pending: Optional["asyncio.Future[Tuple[bool, Any]]"] = None
    thresholds = sorted(notice_after_seconds)
    last_event_at = clock()
    notices_sent = 0
    try:
        while True:
            pending = asyncio.ensure_future(_next_event())
            while True:
                done, _ = await asyncio.wait({pending}, timeout=tick_seconds)
                if done:
                    break
                idle = clock() - last_event_at
                if idle_timeout_seconds is not None and idle >= idle_timeout_seconds:
                    raise ProviderStreamIdleTimeout(idle)
                if on_quiet is not None:
                    while notices_sent < len(thresholds) and idle >= thresholds[notices_sent]:
                        notices_sent += 1
                        await on_quiet(idle)
            has_event, event = pending.result()
            pending = None
            if not has_event:
                return
            last_event_at = clock()
            notices_sent = 0
            yield event
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await pending
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            with suppress(Exception):
                await aclose()
