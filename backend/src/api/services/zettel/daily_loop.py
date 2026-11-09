"""Reusable interval loop for background passes.

Extracted from MemoryIntelligenceScheduler so the zettel materializer does
not become a second copy of the same start/stop/kick/next-run machinery.
Local naive datetimes are deliberate: configured times are local HH:MM.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# The loop never sleeps longer than this in one go, so it re-reads the wall clock often enough to notice that a Mac slept through a scheduled time. asyncio timeouts use a clock that stops while the Mac sleeps, so a single long wait would fire hours late after waking.
WAKE_POLL_SECONDS = 30.0
# While a catch-up run keeps ending without completing, for example because the model is not loaded yet, another attempt waits at least this long.
CATCH_UP_RETRY_SECONDS = 900.0


@dataclass
class LoopStatus:
    is_running: bool = False
    is_running_now: bool = False
    last_run_at: Optional[str] = None
    last_error: Optional[str] = None
    next_run_at: Optional[str] = None


class DailyLoopScheduler:
    """Runs *run_once* at a configured local time, with kick and stop support.

    *catch_up_due*, when given, says whether a scheduled run was missed. The loop runs immediately when it starts and finds a missed run, and again after a wake or an incomplete attempt (at most once per *catch_up_retry_seconds*), so a backend that was not running at the scheduled time does not wait a whole day.
    """

    def __init__(
        self,
        *,
        name: str,
        run_once: Callable[[], Awaitable[Optional[str]]],
        next_run_at: Callable[[], datetime],
        catch_up_due: Optional[Callable[[], bool]] = None,
        wake_poll_seconds: float = WAKE_POLL_SECONDS,
        catch_up_retry_seconds: float = CATCH_UP_RETRY_SECONDS,
        clock: Callable[[], datetime] = datetime.now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._name = name
        self._run_once = run_once
        self._next_run_at = next_run_at
        self._catch_up_due = catch_up_due
        self._wake_poll_seconds = wake_poll_seconds
        self._catch_up_retry_seconds = catch_up_retry_seconds
        self._clock = clock
        self._monotonic = monotonic
        self._last_catch_up_attempt: Optional[float] = None
        self._last_wait_serviced_kick = False
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._kick = asyncio.Event()
        self._status = LoopStatus()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._kick.clear()
        self._status.is_running = True
        self._task = asyncio.create_task(self._loop(), name=self._name)
        logger.info("%s started", self._name)

    async def stop(self) -> None:
        self._stop.set()
        self._kick.set()
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        self._status.is_running = False
        logger.info("%s stopped", self._name)

    def kick(self) -> None:
        self._kick.set()

    def get_status(self) -> LoopStatus:
        return self._status

    async def run_now(self) -> Optional[str]:
        return await self._guarded_run()

    async def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                next_run = self._next_run_at()
                self._status.next_run_at = next_run.isoformat()
                if await self._wait_until(next_run):
                    return
                await self._guarded_run()
        except asyncio.CancelledError:
            logger.info("%s loop canceled", self._name)
            raise
        finally:
            self._status.is_running = False

    async def _wait_until(self, next_run: datetime) -> bool:
        """Wait in short slices until *next_run*, catching up a missed run first; returns True when stopped."""
        while True:
            await self._maybe_catch_up()
            remaining = (next_run - self._clock()).total_seconds()
            if remaining <= 0:
                return self._stop.is_set()
            if await self._wait(min(remaining, self._wake_poll_seconds)):
                return True
            if self._last_wait_serviced_kick:
                return False

    async def _maybe_catch_up(self) -> None:
        if self._catch_up_due is None or self._stop.is_set():
            return
        now = self._monotonic()
        if self._last_catch_up_attempt is not None and now - self._last_catch_up_attempt < self._catch_up_retry_seconds:
            return
        try:
            due = bool(self._catch_up_due())
        except Exception:
            # Throttled like a real attempt so a persistently failing check logs once per retry interval, not once per poll.
            self._last_catch_up_attempt = now
            logger.exception("%s could not check for a missed run", self._name)
            return
        if not due:
            return
        self._last_catch_up_attempt = now
        logger.info("%s missed a scheduled run; running it now", self._name)
        await self._guarded_run()

    async def _wait(self, seconds: float) -> bool:
        self._last_wait_serviced_kick = False
        stop_task = asyncio.create_task(self._stop.wait())
        kick_task = asyncio.create_task(self._kick.wait())
        try:
            done, pending = await asyncio.wait(
                {stop_task, kick_task},
                timeout=seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if kick_task in done:
                self._kick.clear()
                self._last_wait_serviced_kick = True
                if not self._stop.is_set():
                    await self._guarded_run()
            return self._stop.is_set()
        except asyncio.CancelledError:
            for task in (stop_task, kick_task):
                if not task.done():
                    task.cancel()
            raise

    async def _guarded_run(self) -> Optional[str]:
        if self._status.is_running_now:
            return f"{self._name} is already running."
        self._status.is_running_now = True
        try:
            error = await self._run_once()
            self._status.last_run_at = datetime.now().isoformat()
            self._status.last_error = error
            return error
        except Exception as exc:
            logger.exception("%s run failed", self._name)
            self._status.last_error = str(exc)
            return str(exc)
        finally:
            self._status.is_running_now = False


def previous_daily_run(configured_time: str, now: Optional[datetime] = None) -> datetime:
    """Latest local occurrence of an HH:MM string that is not in the future."""
    hour, minute = _parse_time(configured_time)
    moment = now or datetime.now()
    candidate = moment.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate > moment:
        candidate = candidate - timedelta(days=1)
    return candidate


def next_daily_run(configured_time: str) -> datetime:
    """Next local occurrence of an HH:MM string, defaulting to 03:00."""
    hour, minute = _parse_time(configured_time)
    now = datetime.now()
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    return candidate


def next_interval_run(minutes: int) -> datetime:
    """Next run *minutes* from now, floored at one minute."""
    return datetime.now() + timedelta(minutes=max(1, minutes))


def _parse_time(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except Exception:
        pass
    return 3, 0
