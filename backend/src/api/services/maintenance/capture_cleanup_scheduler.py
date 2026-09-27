"""Asyncio scheduler for reasoning-capture cleanup.

Replaces the former Huey reasoning-capture cleanup task.
Behavior preserved from the prior implementation:

  * Reads `reasoning_settings.json` each iteration.
  * If `capture_auto_cleanup_enabled` is False, sleeps `_DISABLED_POLL_SECONDS`
    and re-checks (lets users toggle the setting and have it apply quickly).
  * If enabled, sleeps until the next configured `capture_cleanup_hour:minute`
    local-time slot, then runs `CaptureManagementService.run_automatic_cleanup`.

Cooperative shutdown is via `asyncio.Event` (no daemon threads, no `pkill`).
External callers (e.g. the capture-management service when settings change)
can call `kick()` to wake the loop immediately so settings changes apply
without waiting out the current sleep.

Modeled on `AsyncScheduledAgentTaskRunner`
(`backend/src/api/services/scheduled_agent_tasks/async_scheduled_agent_task_runner.py`):
single asyncio task, single event-loop assumption, no threading locks.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from api.core.logging.api_logger import api_logger

# Re-check the enabled flag every 5 minutes when cleanup is disabled. Short
# enough that toggling the setting on feels responsive; long enough that we
# don't spam the JSON read path.
_DISABLED_POLL_SECONDS: float = 300.0

# Once a cleanup tick completes, sleep at least this long before recomputing
# the next-run time. Prevents same-minute re-trigger if the cleanup itself
# finished in under a second.
_POST_RUN_COOLDOWN_SECONDS: float = 60.0

# Defaults match `reasoning_capture_cleanup_task.get_capture_cleanup_settings_from_json`.
_DEFAULT_SETTINGS = {
    "capture_auto_cleanup_enabled": False,
    "capture_retention_days": 30,
    "capture_cleanup_hour": 2,
    "capture_cleanup_minute": 0,
}


class CaptureCleanupScheduler:
    """Single-task asyncio scheduler for daily capture cleanup."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._kick = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._kick.clear()
        self._task = asyncio.create_task(self._loop(), name="capture-cleanup-scheduler")
        api_logger.info("[CAPTURE_CLEANUP] scheduler started")

    async def stop(self) -> None:
        self._stop.set()
        self._kick.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await asyncio.gather(self._task, return_exceptions=True)
            finally:
                self._task = None
        api_logger.info("[CAPTURE_CLEANUP] scheduler stopped")

    def kick(self) -> None:
        """Wake the loop so settings changes apply without waiting out the sleep."""
        self._kick.set()

    async def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                settings = self._read_settings()

                if not settings.get("capture_auto_cleanup_enabled", False):
                    api_logger.debug(
                        "[CAPTURE_CLEANUP] auto cleanup disabled; rechecking in %ds",
                        int(_DISABLED_POLL_SECONDS),
                    )
                    if await self._wait(_DISABLED_POLL_SECONDS):
                        return
                    continue

                cleanup_hour = int(settings.get("capture_cleanup_hour", 2))
                cleanup_minute = int(settings.get("capture_cleanup_minute", 0))
                next_run = self._compute_next_run(cleanup_hour, cleanup_minute)
                delay = max(0.0, (next_run - datetime.now()).total_seconds())
                api_logger.info(
                    "[CAPTURE_CLEANUP] next cleanup at %s (in %.0fs)",
                    next_run.strftime("%Y-%m-%d %H:%M:%S"),
                    delay,
                )

                if await self._wait(delay):
                    return

                if self._kick.is_set():
                    self._kick.clear()
                    continue

                try:
                    await self._run_once()
                except Exception:
                    api_logger.exception("[CAPTURE_CLEANUP] cleanup tick failed")

                if await self._wait(_POST_RUN_COOLDOWN_SECONDS):
                    return
        except asyncio.CancelledError:
            api_logger.info("[CAPTURE_CLEANUP] loop cancelled")
            raise

    async def _wait(self, seconds: float) -> bool:
        """Sleep up to `seconds` or until stop/kick fires.

        Returns True iff stop was requested (caller should exit the loop).
        """
        if seconds <= 0:
            return self._stop.is_set()
        stop_task = asyncio.create_task(self._stop.wait())
        kick_task = asyncio.create_task(self._kick.wait())
        try:
            done, pending = await asyncio.wait(
                {stop_task, kick_task},
                timeout=seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
        except asyncio.CancelledError:
            for t in (stop_task, kick_task):
                if not t.done():
                    t.cancel()
            raise
        return self._stop.is_set()

    @staticmethod
    def _compute_next_run(hour: int, minute: int) -> datetime:
        now = datetime.now()
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    @staticmethod
    def _read_settings() -> dict:
        """Read `reasoning_settings.json` from disk; fall back to defaults on any error."""
        try:
            from api.core.services.file_storage_service import StorageService
            from api.settings import get_settings as _get_app_settings
        except Exception:
            api_logger.exception("[CAPTURE_CLEANUP] could not import settings deps")
            return dict(_DEFAULT_SETTINGS)

        try:
            app_settings = _get_app_settings()
            storage_service = StorageService(development_mode=app_settings.debug)
            settings_path: Path = storage_service.base_path / "config" / "reasoning_settings.json"
            if not settings_path.exists():
                return dict(_DEFAULT_SETTINGS)
            with open(settings_path, "r") as fh:
                data = json.load(fh)
            return {key: data.get(key, default) for key, default in _DEFAULT_SETTINGS.items()}
        except Exception:
            api_logger.exception("[CAPTURE_CLEANUP] failed reading reasoning_settings.json")
            return dict(_DEFAULT_SETTINGS)

    @staticmethod
    async def _run_once() -> None:
        """Run a single cleanup pass via CaptureManagementService."""
        from api.core.services.capture_management_service import CaptureManagementService
        from api.core.services.file_storage_service import StorageService
        from api.settings import get_settings as _get_app_settings

        api_logger.info("[CAPTURE_CLEANUP] starting cleanup tick")
        app_settings = _get_app_settings()
        storage_service = StorageService(development_mode=app_settings.debug)
        capture_service = CaptureManagementService(storage_service=storage_service)
        await capture_service.run_automatic_cleanup()
        api_logger.info("[CAPTURE_CLEANUP] cleanup tick complete")
