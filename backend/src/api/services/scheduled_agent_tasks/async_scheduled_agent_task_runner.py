"""In-process asyncio scheduler for scheduled agent_tasks.

Replaces the previous Huey-based execution path. The runner lives inside
the FastAPI process so scheduled runs can call directly into
``app.state.agent_task_submission_service.process_agent_task_direct`` without
any cross-process IPC or HTTP self-loop.

Design points worth keeping in mind when modifying this:

  * Persistence is NOT here. SQLite (``scheduled_agent_tasks.next_run_at`` and
    ``scheduled_agent_task_runs``) is the single source of truth for what
    should fire and when. The in-memory ``self._tasks`` map is purely an
    ephemeral execution timer that is rebuilt on every cold start by
    ``initialize_scheduled_agent_task_runtime`` (which calls
    ``recover_missed_runs`` then ``ensure_active_schedules_enqueued`` on
    the orchestrator service).
  * "One pending run per scheduled agent task" is enforced by ``schedule()`` cancelling
    any existing in-memory task for that ``scheduled_agent_task_id`` BEFORE
    creating a new one. The DB-side counterpart
    (``cancel_pending_runs_for_agent_task`` on the repository) is invoked by
    the orchestrator service before this runner ever sees the new run.
  * No threading primitives are used. The runner assumes the standard
    single-event-loop model the rest of the FastAPI app runs under, and
    matches the pattern already used by
    ``AutomaticActivityCaptureService._activity_capture_loop`` and
    ``AutomaticActivityProcessingService._scheduled_processing_loop`` for
    other periodic work.
  * If the API process crashes mid-sleep, the in-flight task dies with it
    and the run row will be marked ``missed`` on next startup by
    ``recover_missed_runs``. This matches the existing semantics for any
    longer outage and is intentional (no catch-up replay).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class AsyncScheduledAgentTaskRunner:
    """Singleton holding ``scheduled_agent_task_id -> asyncio.Task`` for in-flight timers."""

    def __init__(self) -> None:
        self._tasks: Dict[str, asyncio.Task] = {}

    def schedule(
        self,
        scheduled_agent_task_id: str,
        run_id: str,
        eta_utc: datetime,
        quiet: bool = False,
    ) -> None:
        """Schedule (or reschedule) a run for execution at ``eta_utc``.

        Cancels any existing in-memory task for the same
        ``scheduled_agent_task_id`` before installing the new one. The DB-side
        cancellation of any prior ``scheduled_agent_task_runs`` rows is the
        caller's responsibility (see
        ``ScheduledAgentTaskService.enqueue_scheduled_agent_task``).

        ``quiet=True`` demotes the final "scheduled run X..." line to
        DEBUG. Intended for the wall-clock reconciler's reuse branch,
        which re-arms the timer against the same (run_id, eta) every
        minute purely to recompute the asyncio.sleep delay against
        wall-clock -- no audit-worthy state change happens, and
        logging INFO on every tick would produce thousands of
        duplicate lines per active schedule per day. Genuine
        reschedules (recreate branch, run-now, schedule edits) leave
        ``quiet`` at its default so the INFO line still appears.
        """
        if eta_utc.tzinfo is None:
            eta_utc = eta_utc.replace(tzinfo=timezone.utc)

        existing = self._tasks.pop(scheduled_agent_task_id, None)
        if existing is not None and not existing.done():
            existing.cancel()
            logger.debug(
                "AsyncScheduledAgentTaskRunner: replaced in-flight task for scheduled_agent_task_id=%s",
                scheduled_agent_task_id,
            )

        task = asyncio.create_task(
            self._sleep_then_execute(scheduled_agent_task_id, run_id, eta_utc),
            name=f"scheduled-run:{scheduled_agent_task_id}:{run_id}",
        )
        self._tasks[scheduled_agent_task_id] = task
        log_method = logger.debug if quiet else logger.info
        log_method(
            "AsyncScheduledAgentTaskRunner: scheduled run %s for scheduled agent task %s at %s",
            run_id,
            scheduled_agent_task_id,
            eta_utc.isoformat(),
        )

    def cancel(self, scheduled_agent_task_id: str, quiet: bool = False) -> bool:
        """Cancel any in-flight task for ``scheduled_agent_task_id``.

        Returns ``True`` if a task was found and cancelled, ``False`` if
        there was nothing scheduled for that scheduled agent task. Safe to call from any
        async context; the cancellation propagates via the task's own
        ``CancelledError`` handler.

        ``quiet=True`` demotes the "cancelled in-flight task..." line
        to DEBUG. Used by the reconciler's reuse path (see ``schedule``
        for the same rationale) so the same-eta re-anchoring does not
        spam INFO every minute. Genuine cancellations (run-now,
        schedule deactivation, shutdown) leave ``quiet`` at its
        default so the INFO line still appears.
        """
        task = self._tasks.pop(scheduled_agent_task_id, None)
        if task is None:
            return False
        if not task.done():
            task.cancel()
            log_method = logger.debug if quiet else logger.info
            log_method(
                "AsyncScheduledAgentTaskRunner: cancelled in-flight task for scheduled_agent_task_id=%s",
                scheduled_agent_task_id,
            )
        return True

    def cancel_all(self) -> None:
        """Cancel every in-flight task. Intended for clean FastAPI shutdown."""
        if not self._tasks:
            return
        ids = list(self._tasks.keys())
        for scheduled_agent_task_id in ids:
            self.cancel(scheduled_agent_task_id)
        logger.info(
            "AsyncScheduledAgentTaskRunner: cancelled %d in-flight task(s) on shutdown",
            len(ids),
        )

    def has_pending(self, scheduled_agent_task_id: str) -> bool:
        task = self._tasks.get(scheduled_agent_task_id)
        return task is not None and not task.done()

    async def _sleep_then_execute(
        self,
        scheduled_agent_task_id: str,
        run_id: str,
        eta_utc: datetime,
    ) -> None:
        try:
            now = datetime.now(timezone.utc)
            delay_seconds = max(0.0, (eta_utc - now).total_seconds())
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)

            # Imported lazily to avoid a circular import: the service module
            # imports this runner module to schedule work, and would cycle
            # if we imported the service at module load time.
            from .scheduled_agent_task_service import ScheduledAgentTaskService

            service = ScheduledAgentTaskService()
            await service.execute_scheduled_run(scheduled_agent_task_id, run_id)
        except asyncio.CancelledError:
            logger.debug(
                "AsyncScheduledAgentTaskRunner: task for scheduled_agent_task_id=%s run_id=%s cancelled",
                scheduled_agent_task_id,
                run_id,
            )
            raise
        except Exception as exc:
            # ``execute_scheduled_run`` already finalizes the run row on
            # exception, so nothing to do here besides surface the failure.
            logger.error(
                "AsyncScheduledAgentTaskRunner: task for scheduled_agent_task_id=%s run_id=%s failed: %s",
                scheduled_agent_task_id,
                run_id,
                exc,
                exc_info=True,
            )
        finally:
            current = self._tasks.get(scheduled_agent_task_id)
            if current is not None and current.get_name() == f"scheduled-run:{scheduled_agent_task_id}:{run_id}":
                self._tasks.pop(scheduled_agent_task_id, None)


_runner_singleton: Optional[AsyncScheduledAgentTaskRunner] = None


def get_async_scheduled_agent_task_runner() -> AsyncScheduledAgentTaskRunner:
    global _runner_singleton
    if _runner_singleton is None:
        _runner_singleton = AsyncScheduledAgentTaskRunner()
    return _runner_singleton
