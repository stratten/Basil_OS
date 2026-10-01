"""FastAPI-startup wiring for the scheduled-agent-tasks feature.

Single entry point invoked once during the FastAPI lifespan startup, after
``app.state.agent_task_submission_service`` is populated. Stitches together the
three things that must happen exactly once per process before any
scheduled run can be dispatched:

  1. Register the agent_task status callback (process-singleton bridge
     between agent_task terminal events and the asyncio.Future that
     ``execute_scheduled_run`` is awaiting).
  2. Mark stale ``scheduled``/``running`` runs left over from a previous
     session as ``missed`` and advance each parent scheduled agent task's
     ``next_run_at`` to its next future occurrence.
  3. Walk every active scheduled agent task with a future ``next_run_at``
     and install an in-memory timer for it via the runner.

Layering: the highest layer of the component package -- imports from
``scheduled_run_execution`` (callback registration) and
``scheduled_run_lifecycle`` (recovery + enqueue). Imported only by the
facade and (transitively, via the package ``__init__``) by ``basil_api.py``.
"""

from __future__ import annotations

import logging
from typing import Dict

from api.dependencies import get_sqlite_knowledge_service

from . import scheduled_run_execution, scheduled_run_lifecycle, scheduler_reconciler

logger = logging.getLogger(__name__)


async def initialize_scheduled_agent_task_runtime() -> Dict[str, int]:
    """Startup helper: recover missed runs and enqueue future active runs.

    Called once during FastAPI lifespan startup, after
    ``app.state.agent_task_submission_service`` is populated. Recovers any runs
    left in ``scheduled``/``running`` from a previous session by marking
    them missed (advancing the parent scheduled agent task's ``next_run_at`` to the
    next future occurrence rather than replaying the missed one), then
    walks every active scheduled agent task with a future ``next_run_at``
    and installs an in-memory timer for it via the runner.

    After the initial install, also starts the wall-clock reconciler
    that ticks once per minute and re-anchors the in-memory asyncio
    timers against SQLite's canonical ``next_run_at`` values. This is
    the catch-up mechanism for the case where ``asyncio.sleep`` drifts
    past its planned wall-clock target (typically because the macOS
    host slept while the FastAPI process was running). The reconciler
    is paired with ``shutdown_scheduled_agent_task_runtime`` so the
    task is canceled cleanly on app shutdown.
    """
    repo = get_sqlite_knowledge_service().scheduled_agent_task_repository
    # Wire the agent_task status callback before any runs can fire so the
    # very first scheduled run after startup will already have a working
    # completion-tracking path.
    scheduled_run_execution.ensure_agent_task_callback_registered()
    recovery = await scheduled_run_lifecycle.recover_missed_runs(repo)
    enqueued = await scheduled_run_lifecycle.ensure_active_schedules_enqueued(repo)
    # Start the once-per-minute reconciler AFTER initial recovery + enqueue
    # so the first tick (which arrives 60s later) sees a stable timer
    # population to reconcile against, rather than racing the cold-start
    # install above.
    scheduler_reconciler.start_scheduler_reconciler(repo)
    logger.info(
        "Scheduled agent task runtime initialized: missed_runs=%s requeued=%s enqueued=%s",
        recovery.get("missed_runs", 0),
        recovery.get("requeued_agent_tasks", 0),
        enqueued,
    )
    return {
        "missed_runs": int(recovery.get("missed_runs", 0)),
        "requeued_agent_tasks": int(recovery.get("requeued_agent_tasks", 0)),
        "enqueued_agent_tasks": int(enqueued),
    }


async def shutdown_scheduled_agent_task_runtime() -> None:
    """Shutdown helper: stop the wall-clock reconciler task.

    Paired with ``initialize_scheduled_agent_task_runtime``. Called once
    during FastAPI lifespan shutdown alongside the existing
    ``AsyncScheduledAgentTaskRunner.cancel_all`` invocation so the
    reconciler's per-minute loop doesn't log spurious CancelledError
    noise (or, worse, keep ticking against a torn-down DB connection)
    after the rest of the runtime has been brought down.

    Safe to call when the reconciler was never started (no-op).
    """
    await scheduler_reconciler.stop_scheduler_reconciler()
