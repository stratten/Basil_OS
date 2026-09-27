"""Periodic materialization of the zettel stream."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from api.services.zettel.daily_loop import DailyLoopScheduler, next_interval_run

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_MINUTES = 15


class ZettelScheduler:
    """Runs the materializer on an interval, off the event loop thread."""

    def __init__(self) -> None:
        self._loop = DailyLoopScheduler(
            name="zettel-materializer",
            run_once=self._run_once,
            next_run_at=lambda: next_interval_run(self._interval_minutes()),
        )

    async def start(self) -> None:
        if not self._enabled():
            logger.info("ZettelScheduler disabled by preferences; not starting")
            return
        await self._loop.start()

    async def stop(self) -> None:
        await self._loop.stop()

    def kick(self) -> None:
        self._loop.kick()

    def get_status(self):
        return self._loop.get_status()

    async def run_now(self) -> Optional[str]:
        return await self._loop.run_now()

    async def _run_once(self) -> Optional[str]:
        from api.services.zettel.materializer import (
            DEFAULT_LIMIT_PER_SOURCE,
            get_zettel_materializer,
            since_iso_for_days,
        )

        settings = self._settings()
        materializer = get_zettel_materializer()
        limit = int(
            getattr(settings, "limit_per_source_per_pass", DEFAULT_LIMIT_PER_SOURCE)
            or DEFAULT_LIMIT_PER_SOURCE
        )
        since_iso = since_iso_for_days(int(getattr(settings, "history_days", 30) or 0))
        enabled_sources = getattr(settings, "enabled_sources", None)
        enabled_kinds = set(enabled_sources) if enabled_sources else None
        result = await asyncio.to_thread(
            materializer.run_pass,
            limit_per_source=limit,
            since_iso=since_iso,
            enabled_kinds=enabled_kinds,
        )
        logger.info(
            "Zettel carding pass: %s carded, %s already present, %s stamped",
            result.carded, result.existing, result.stamped,
        )
        return "; ".join(result.errors) if result.errors else None

    def _settings(self):
        try:
            from api.core.preferences.preferences_io import load_preferences

            return getattr(load_preferences(), "zettel", None)
        except Exception:
            logger.exception("Failed to load zettel settings")
            return None

    def _enabled(self) -> bool:
        return bool(getattr(self._settings(), "carding_enabled", True))

    def _interval_minutes(self) -> int:
        return int(
            getattr(self._settings(), "carding_interval_minutes", DEFAULT_INTERVAL_MINUTES)
            or DEFAULT_INTERVAL_MINUTES
        )


_zettel_scheduler_singleton: Optional[ZettelScheduler] = None


def get_zettel_scheduler() -> ZettelScheduler:
    global _zettel_scheduler_singleton
    if _zettel_scheduler_singleton is None:
        _zettel_scheduler_singleton = ZettelScheduler()
    return _zettel_scheduler_singleton
