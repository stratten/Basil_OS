"""Wall-clock reconciler for scheduled-agent-task timers.

Background
----------
The primary dispatcher for scheduled runs is the per-task in-process timer
held by ``AsyncScheduledAgentTaskRunner`` (one ``asyncio.Task`` per active
``scheduled_agent_tasks`` row). That timer uses ``asyncio.sleep(delay)``
under the hood, which is driven by the event loop's monotonic clock. On
macOS that clock effectively pauses while the host system is asleep
(lid closed, deep idle), so a timer armed at 6 PM to fire at 8 PM can
silently fire much later than 8 PM wall-clock if the laptop slept in
between. SQLite keeps the canonical ``next_run_at`` instant on every
row, but nothing today re-anchors the in-memory timer against it after
the process has been running for a while.

This module is that re-anchor. It runs a single ``asyncio.Task`` that
wakes once per minute and calls
``scheduled_run_lifecycle.enqueue_scheduled_agent_task`` for every active
schedule. ``enqueue_scheduled_agent_task`` is idempotent with respect
to the requested time:

* If a pending ``scheduled`` run row already exists for the same instant
  (within a one-second tolerance), the call re-arms the in-memory
  asyncio timer on top of that existing row and writes nothing to SQLite.
* If no matching pending row exists, the call cancels any stale pending
  row, creates a fresh one, and arms the timer.

That makes the reconciler safe to call every tick: schedules that are
already armed correctly cost a few row reads; schedules whose timer has
drifted (or never existed because the process restarted) get re-armed
the next time the reconciler ticks.

Skipping in-flight runs
-----------------------
``enqueue_scheduled_agent_task`` only reuses the pending row when its
``status`` is ``'scheduled'``. If the row is currently ``'running'`` the
reuse branch does not match and the function falls through to creating
a *new* ``scheduled`` row for the same ``scheduled_for`` instant -- which
would then fire alongside the still-running execution, double-firing
the schedule. To prevent that, the reconciler explicitly skips any
schedule that currently has a ``running`` run row. Once the in-flight
run finalizes (via ``finalize_run_after_execution``), it computes the
next ``next_run_at`` and the reconciler picks it up on the next tick.

Cadence
-------
60 seconds. The reconciler does one
``list_active_scheduled_agent_tasks`` query plus one
``list_runs_for_agent_task(limit=10)`` per active schedule per tick.
Typical row counts are <10 active schedules, so each tick is well under
a millisecond of SQLite work and has no measurable CPU or battery
impact relative to the existing asyncio timer overhead.

Lifecycle
---------
``start_scheduler_reconciler`` is invoked once at FastAPI startup by
``initialize_scheduled_agent_task_runtime``; the returned
``asyncio.Task`` handle is stashed at module scope so a paired
``stop_scheduler_reconciler`` call (from app shutdown) can cancel it.
Both functions are idempotent so duplicate calls during test fixture
setup/teardown are safe.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from . import scheduled_run_lifecycle

if TYPE_CHECKING:
    from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.scheduling.repository import (
        ScheduledAgentTaskRepository,
    )

logger = logging.getLogger(__name__)


# How long the reconciler sleeps between ticks. 60s is small enough to
# bound the perceived lateness after a macOS wake (worst-case ~60s
# beyond the actual wake instant), and large enough that the SQLite
# work is amortized to essentially nothing.
_RECONCILE_INTERVAL_SECONDS = 60


# Single in-process handle for the reconciler task. Module-level (not
# on a class) because the runtime initializer is itself process-
# singleton and there is no situation in which two reconcilers should
# coexist within one FastAPI process.
_reconciler_task: Optional[asyncio.Task] = None


async def _reconcile_once(repo: "ScheduledAgentTaskRepository") -> None:
    """Walk every active schedule and re-arm its in-memory timer.

    Defensive against any single schedule's reconciliation raising:
    we log and continue to the next row rather than letting one bad
    schedule starve the others. The outer loop also wraps this whole
    call in its own try/except so a torn-down DB connection won't kill
    the reconciler.
    """
    scheduled_agent_tasks = await repo.list_active_scheduled_agent_tasks()
    for scheduled_agent_task in scheduled_agent_tasks:
        scheduled_agent_task_id = scheduled_agent_task.get("id")
        next_run_at = scheduled_agent_task.get("next_run_at")
        if not scheduled_agent_task_id or not next_run_at:
            continue
        try:
            # A run currently in 'running' status is mid-execution.
            # Re-enqueueing here would fall through enqueue's reuse
            # branch (which only matches 'scheduled' rows) and create
            # a duplicate scheduled row alongside the running one,
            # double-firing the schedule. Let the running execution
            # finalize on its own; finalize_run_after_execution will
            # advance next_run_at and the next tick will arm it.
            runs = await repo.list_runs_for_agent_task(scheduled_agent_task_id, limit=10)
            if any(r.get("status") == "running" for r in runs):
                continue
            await scheduled_run_lifecycle.enqueue_scheduled_agent_task(
                repo, scheduled_agent_task_id, next_run_at
            )
        except Exception:
            logger.exception(
                "scheduler_reconciler: failed to reconcile scheduled_agent_task_id=%s",
                scheduled_agent_task_id,
            )


async def _reconciler_loop(repo: "ScheduledAgentTaskRepository") -> None:
    """Forever-loop that ticks once per ``_RECONCILE_INTERVAL_SECONDS``.

    The loop swallows non-cancellation exceptions on every tick so a
    transient SQLite hiccup (or any other one-off failure) cannot tear
    down the reconciler for the lifetime of the process. ``CancelledError``
    is allowed to propagate so ``stop_scheduler_reconciler`` actually
    terminates the task.
    """
    logger.info(
        "scheduler_reconciler: started, interval=%ss",
        _RECONCILE_INTERVAL_SECONDS,
    )
    try:
        while True:
            try:
                await _reconcile_once(repo)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler_reconciler: tick failed")
            await asyncio.sleep(_RECONCILE_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("scheduler_reconciler: cancelled")
        raise


def start_scheduler_reconciler(repo: "ScheduledAgentTaskRepository") -> asyncio.Task:
    """Start (or return the existing) reconciler task.

    Idempotent: if a task is already running, the existing handle is
    returned unchanged so duplicate startup invocations during test
    fixtures or hot-reload are safe.
    """
    global _reconciler_task
    if _reconciler_task is not None and not _reconciler_task.done():
        return _reconciler_task
    _reconciler_task = asyncio.create_task(
        _reconciler_loop(repo),
        name="scheduled-agent-task-reconciler",
    )
    return _reconciler_task


async def stop_scheduler_reconciler() -> None:
    """Cancel the reconciler task on shutdown.

    Safe to call when no task is running (no-op). The await on
    ``task`` swallows the expected ``CancelledError`` so the caller
    does not have to special-case it.
    """
    global _reconciler_task
    task = _reconciler_task
    _reconciler_task = None
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("scheduler_reconciler: error during shutdown")
