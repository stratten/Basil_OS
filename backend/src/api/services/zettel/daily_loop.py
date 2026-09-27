"""Reusable interval loop for background passes.

Extracted from MemoryIntelligenceScheduler so the zettel materializer does
not become a second copy of the same start/stop/kick/next-run machinery.
Local naive datetimes are deliberate: configured times are local HH:MM.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class LoopStatus:
    is_running: bool = False
    is_running_now: bool = False
    last_run_at: Optional[str] = None
    last_error: Optional[str] = None
    next_run_at: Optional[str] = None


class DailyLoopScheduler:
    """Runs *run_once* at a configured local time, with kick and stop support."""

    def __init__(
        self,
        *,
        name: str,
        run_once: Callable[[], Awaitable[Optional[str]]],
        next_run_at: Callable[[], datetime],
    ) -> None:
        self._name = name
        self._run_once = run_once
        self._next_run_at = next_run_at
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
                wait_seconds = max((next_run - datetime.now()).total_seconds(), 0.0)
                if await self._wait(wait_seconds):
                    return
                await self._guarded_run()
        except asyncio.CancelledError:
            logger.info("%s loop cancelled", self._name)
            raise
        finally:
            self._status.is_running = False

    async def _wait(self, seconds: float) -> bool:
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
