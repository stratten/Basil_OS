"""Daily scheduler for opt-in memory and skill intelligence passes."""

from __future__ import annotations

import logging
from typing import Optional

from api.services.memory.post_task_evaluator_orchestrator import (
    PostTaskEvaluatorResult,
    get_post_task_evaluator_orchestrator,
)
from api.services.zettel.daily_loop import DailyLoopScheduler, LoopStatus, next_daily_run


logger = logging.getLogger(__name__)


MemoryIntelligenceSchedulerStatus = LoopStatus


class MemoryIntelligenceScheduler:
    """Run the model-driven daily sweep at the user's configured local time."""

    def __init__(self) -> None:
        self._last_result: Optional[PostTaskEvaluatorResult] = None
        self._loop = DailyLoopScheduler(
            name="memory-intelligence-scheduler",
            run_once=self._run_sweep_for_loop,
            next_run_at=lambda: next_daily_run(self._configured_daily_time()),
        )

    async def start(self) -> None:
        await self._loop.start()

    async def stop(self) -> None:
        await self._loop.stop()

    def kick(self) -> None:
        self._loop.kick()

    def get_status(self) -> LoopStatus:
        return self._loop.get_status()

    async def run_now(self) -> PostTaskEvaluatorResult:
        # Cleared first so a rejected or crashed run cannot return the previous
        # sweep's counts as though it had just succeeded.
        self._last_result = None
        outcome = await self._loop.run_now()
        if self._last_result is None:
            return PostTaskEvaluatorResult(
                errors=[outcome or "Memory intelligence sweep did not run."]
            )
        return self._last_result

    async def _run_sweep_for_loop(self) -> Optional[str]:
        if self._is_reconciliation_active():
            logger.info("Skipping memory intelligence sweep: reconciliation workspace is open")
            self._last_result = PostTaskEvaluatorResult(
                errors=[
                    "Skipped: a skill reconciliation workspace is open. "
                    "Close it before running skill intelligence."
                ]
            )
            # None so an expected skip is not reported as a scheduler error by
            # the health check; run_now still surfaces the reason to the caller.
            return None

        result = await get_post_task_evaluator_orchestrator().run_daily_sweep()
        self._last_result = result
        return "; ".join(result.errors) if result.errors else None

    def _is_reconciliation_active(self) -> bool:
        try:
            from api.services.skills.reconciliation import reconciliation_gate

            return reconciliation_gate.is_active()
        except Exception:
            logger.exception("Failed to read reconciliation gate state")
            return False

    def _configured_daily_time(self) -> str:
        try:
            from api.core.preferences.preferences_io import load_preferences

            memory_settings = getattr(load_preferences(), "memory_intelligence", None)
            return (
                getattr(memory_settings, "memory_daily_time_local", None)
                or getattr(memory_settings, "skill_daily_time_local", None)
                or "03:00"
            )
        except Exception:
            logger.exception("Failed to read memory intelligence daily time")
            return "03:00"


_memory_intelligence_scheduler_singleton: Optional[MemoryIntelligenceScheduler] = None


def get_memory_intelligence_scheduler() -> MemoryIntelligenceScheduler:
    global _memory_intelligence_scheduler_singleton
    if _memory_intelligence_scheduler_singleton is None:
        _memory_intelligence_scheduler_singleton = MemoryIntelligenceScheduler()
    return _memory_intelligence_scheduler_singleton
