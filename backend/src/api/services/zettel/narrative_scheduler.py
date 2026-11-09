"""Schedules the model-driven narrative finalizing pass.

A separate scheduler from ZettelScheduler on purpose: expensive model work at a
configured hour must not be coupled to the cheap, frequent carding cadence.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from api.services.zettel.daily_loop import (
    DailyLoopScheduler,
    next_daily_run,
    next_interval_run,
    previous_daily_run,
)
from api.core.models.reasoning.effort_override import reasoning_effort_override
from api.services.zettel.schedule_ledger import read_last_completed, record_completed

logger = logging.getLogger(__name__)

DEFAULT_SCHEDULED_TIME = "02:00"
DEFAULT_INTERVAL_MINUTES = 30
LEDGER_NAME = "zettel-narrative"
SUPPORTED_REASONING_EFFORTS = ("none", "low", "medium", "high")


class ZettelNarrativeScheduler:
    """Runs the enricher daily (scheduled) or on an interval (continuous)."""

    def __init__(self) -> None:
        self._loop = DailyLoopScheduler(
            name="zettel-narrative",
            run_once=self._run_once,
            next_run_at=self._next_run_at,
            catch_up_due=self._missed_scheduled_run,
        )
        # Held so a fire-and-forget manual run is not garbage-collected mid-flight.
        self._manual_task: Optional[asyncio.Task] = None
        # run_now marks only its own guarded invocation as user initiated. The flag is cleared in run_now's finally block so an already-running pass cannot leak manual API parallelism into the next scheduled pass.
        self._pending_trigger_is_manual = False

    async def start(self) -> None:
        if not self._enabled():
            logger.info("ZettelNarrativeScheduler disabled by preferences; not starting")
            return
        await self._loop.start()

    async def stop(self) -> None:
        await self._loop.stop()

    def kick(self) -> None:
        self._loop.kick()

    def get_status(self):
        return self._loop.get_status()

    async def run_now(self) -> Optional[str]:
        self._pending_trigger_is_manual = True
        try:
            return await self._loop.run_now()
        finally:
            self._pending_trigger_is_manual = False

    def run_now_background(self) -> None:
        """Kick a finalizing pass without blocking the caller.

        The drain runs to completion and can be long, so the HTTP request that
        triggers it must return immediately; progress is observed via
        get_progress(). run_now is guarded against overlap, so a manual kick
        during a scheduled run simply reports "already running".
        """
        if self._manual_task and not self._manual_task.done():
            return
        self._manual_task = asyncio.create_task(self.run_now())

    def get_progress(self):
        from api.services.zettel.narrative.enricher import get_zettel_enricher

        return get_zettel_enricher().get_progress()

    async def _run_once(self) -> Optional[str]:
        from api.services.zettel.narrative.enricher import (
            DEFAULT_BATCH_SIZE,
            DEFAULT_MAX_ATTEMPTS,
            get_zettel_enricher,
        )
        from api.services.zettel.narrative.narrative_processing_run_policy import (
            resolve_narrative_processing_run_policy,
        )

        is_manual_backlog_run = self._pending_trigger_is_manual
        settings = self._settings()
        enricher = get_zettel_enricher()
        batch = int(getattr(settings, "narrative_batch_size", DEFAULT_BATCH_SIZE) or DEFAULT_BATCH_SIZE)
        attempts = int(
            getattr(settings, "narrative_max_attempts", DEFAULT_MAX_ATTEMPTS) or DEFAULT_MAX_ATTEMPTS
        )
        configured_model = (getattr(settings, "narrative_model", "") or "").strip()
        max_records = int(getattr(settings, "narrative_max_records", 0) or 0)
        run_policy = resolve_narrative_processing_run_policy(
            configured_model,
            is_manual_backlog_run=is_manual_backlog_run,
        )
        # The override is scoped to this run; the tasks run_pass spawns inherit it, and agent chat keeps the registry default.
        with reasoning_effort_override(self._configured_reasoning_effort(settings)):
            result = await enricher.run_pass(
                batch_size=batch,
                max_attempts=attempts,
                max_records=max_records,
                run_policy=run_policy,
            )
        logger.info(
            "Zettel narrative pass: %s finalized, %s still open, %s failed, %s discarded",
            result.finalized, result.still_open, result.failed, result.discarded,
        )
        if result.completed:
            record_completed(LEDGER_NAME)
        if result.finalized:
            from api.services.retrieval.index_runtime import get_retrieval_index_runtime

            await get_retrieval_index_runtime().reconcile_after_narrative_pass()
        return "; ".join(result.errors) if result.errors else None

    @staticmethod
    def _configured_reasoning_effort(settings) -> Optional[str]:
        """The narrative reasoning effort, or None (registry default) when unset or not one of the supported levels."""
        raw = getattr(settings, "narrative_reasoning_effort", None)
        effort = raw.strip().lower() if isinstance(raw, str) else ""
        return effort if effort in SUPPORTED_REASONING_EFFORTS else None

    def _missed_scheduled_run(self) -> bool:
        """True in scheduled mode when the latest scheduled slot has passed without a completed pass.

        This is what makes a backend that was off, or a Mac that was asleep, at the scheduled time run the pass as soon as it is active again instead of waiting for tomorrow's slot. A pass that never completed, including one stopped because the model was unavailable, keeps this true.
        """
        settings = self._settings()
        if not self._enabled():
            return False
        mode = (getattr(settings, "narrative_mode", "scheduled") or "scheduled").lower()
        if mode == "continuous":
            return False
        slot = previous_daily_run(
            getattr(settings, "narrative_scheduled_time", DEFAULT_SCHEDULED_TIME) or DEFAULT_SCHEDULED_TIME
        )
        last_completed = read_last_completed(LEDGER_NAME)
        return last_completed is None or last_completed < slot

    def _next_run_at(self) -> datetime:
        settings = self._settings()
        mode = (getattr(settings, "narrative_mode", "scheduled") or "scheduled").lower()
        if mode == "continuous":
            minutes = int(
                getattr(settings, "narrative_interval_minutes", DEFAULT_INTERVAL_MINUTES)
                or DEFAULT_INTERVAL_MINUTES
            )
            return next_interval_run(minutes)
        return next_daily_run(
            getattr(settings, "narrative_scheduled_time", DEFAULT_SCHEDULED_TIME)
            or DEFAULT_SCHEDULED_TIME
        )

    def _settings(self):
        try:
            from api.core.preferences.preferences_io import load_preferences

            return getattr(load_preferences(), "zettel", None)
        except Exception:
            logger.exception("Failed to load zettel settings")
            return None

    def _enabled(self) -> bool:
        return bool(getattr(self._settings(), "narrative_enabled", True))


_narrative_scheduler_singleton: Optional[ZettelNarrativeScheduler] = None


def get_zettel_narrative_scheduler() -> ZettelNarrativeScheduler:
    global _narrative_scheduler_singleton
    if _narrative_scheduler_singleton is None:
        _narrative_scheduler_singleton = ZettelNarrativeScheduler()
    return _narrative_scheduler_singleton
