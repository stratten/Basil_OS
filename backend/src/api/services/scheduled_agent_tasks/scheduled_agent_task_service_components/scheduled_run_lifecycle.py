"""Scheduled-agent-task + scheduled-run lifecycle workflows.

Owns every transition between persistent rows and the in-process runner:
creation/update of ``scheduled_agent_tasks`` rows, idempotent enqueue of
pending runs into the asyncio runner, recovery of orphaned runs after a
restart, on-demand "run now", and post-execution finalization that
chains into the next occurrence (or deactivates one-time schedules).

Layering: depends on ``schedule_time_math`` for next-run math, on the
``async_scheduled_agent_task_runner`` for in-memory dispatch, and on the
caller-supplied ``ScheduledAgentTaskRepository`` instance for persistence.
Does NOT depend on the higher-layer execution / runtime / facade modules
-- those import from here.

All functions take an explicit ``repo`` (and where needed, the broader
``SqliteKnowledgeService`` for non-scheduled-agent-task tables like
``agent_tasks``) so this module has no global service references and
can be unit-tested in isolation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .schedule_time_math import compute_next_run_at, utc_now

if TYPE_CHECKING:
    from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
    from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.scheduling.repository import (
        ScheduledAgentTaskRepository,
    )

logger = logging.getLogger(__name__)


async def create_scheduled_agent_task(
    repo: "ScheduledAgentTaskRepository",
    *,
    title: str,
    agent_task_text: str,
    schedule_type: str,
    schedule_config: Dict[str, Any],
    timezone_name: str,
    source_type: str = "manual",
    is_active: bool = True,
    reference_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    next_run_at = compute_next_run_at(schedule_type, schedule_config, timezone_name)
    created = await repo.create_scheduled_agent_task(
        title=title,
        agent_task_text=agent_task_text,
        schedule_type=schedule_type,
        schedule_config=schedule_config,
        timezone=timezone_name,
        next_run_at=next_run_at,
        source_type=source_type,
        is_active=is_active,
        reference_paths=reference_paths,
    )
    if is_active and next_run_at:
        await enqueue_scheduled_agent_task(repo, created["id"], next_run_at)
    return created


async def update_scheduled_agent_task(
    repo: "ScheduledAgentTaskRepository",
    scheduled_agent_task_id: str,
    updates: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    existing = await repo.get_scheduled_agent_task(scheduled_agent_task_id)
    if not existing:
        return None

    schedule_type = updates.get("schedule_type", existing["schedule_type"])
    schedule_config = updates.get("schedule_config", existing["schedule_config"])
    timezone_name = updates.get("timezone", existing["timezone"])
    is_active = updates.get("is_active", existing["is_active"])

    if "schedule_type" in updates or "schedule_config" in updates or "timezone" in updates or "is_active" in updates:
        updates["next_run_at"] = (
            compute_next_run_at(schedule_type, schedule_config, timezone_name)
            if is_active
            else None
        )

    updated = await repo.update_scheduled_agent_task(
        scheduled_agent_task_id,
        title=updates.get("title"),
        agent_task_text=updates.get("agent_task_text"),
        schedule_type=updates.get("schedule_type"),
        schedule_config=updates.get("schedule_config"),
        timezone=updates.get("timezone"),
        is_active=updates.get("is_active"),
        next_run_at=updates.get("next_run_at"),
        last_status=updates.get("last_status"),
        last_run_at=updates.get("last_run_at"),
        reference_paths=updates.get("reference_paths"),
    )
    if updated and updated.get("is_active") and updated.get("next_run_at"):
        await enqueue_scheduled_agent_task(repo, updated["id"], updated["next_run_at"])
    return updated


async def enqueue_scheduled_agent_task(
    repo: "ScheduledAgentTaskRepository",
    scheduled_agent_task_id: str,
    scheduled_for_iso: str,
) -> str:
    """Ensure a single pending run exists for this scheduled agent task at the requested time, dispatched to the in-process runner.

    Enforces "one pending run per scheduled agent task" at both the DB and in-memory
    levels, and is idempotent with respect to the requested time:

    * If there is already a ``scheduled`` run row for this scheduled agent task with
      the same ``scheduled_for`` (within a one-second tolerance to
      absorb ISO serialization round-trip noise), we *do not* touch
      the DB at all. We just (re-)install the in-memory asyncio timer
      on top of that existing row and return its id. This is the path
      every cold-start hits for an unchanged future schedule -- the
      runner is in-memory only, so startup must re-arm it from DB
      state, but it should leave the audit trail alone.
    * Otherwise (no pending row, or the time has changed), any prior
      ``scheduled`` run is marked ``cancelled`` ("Superseded by
      reschedule"), the corresponding asyncio.Task is cancelled, and
      a fresh run row is created and timer-armed. This is what
      prevents duplicate firings when a scheduled agent task is genuinely
      rescheduled (edited to a new time, finalized into its next
      occurrence, recovered after a real miss, etc.).

    Without the idempotency check, every cold start (and every edit
    that didn't actually change the time) would write a phantom
    ``cancelled - Superseded by reschedule`` row plus a new
    ``scheduled`` row, polluting the user-visible run history with
    churn that doesn't reflect any real change.
    """
    from ..async_scheduled_agent_task_runner import get_async_scheduled_agent_task_runner

    scheduled_for_dt = datetime.fromisoformat(scheduled_for_iso.replace("Z", "+00:00"))
    target_utc = scheduled_for_dt.astimezone(timezone.utc)

    existing_runs = await repo.list_runs_for_agent_task(scheduled_agent_task_id, limit=50)
    pending_existing = [r for r in existing_runs if r.get("status") == "scheduled"]

    if len(pending_existing) == 1:
        only_pending = pending_existing[0]
        try:
            existing_dt = datetime.fromisoformat(
                str(only_pending["scheduled_for"]).replace("Z", "+00:00")
            )
            if existing_dt.tzinfo is None:
                existing_dt = existing_dt.replace(tzinfo=timezone.utc)
            existing_utc = existing_dt.astimezone(timezone.utc)
            if abs((existing_utc - target_utc).total_seconds()) < 1.0:
                runner = get_async_scheduled_agent_task_runner()
                # quiet=True: this branch is hit on every wall-clock
                # reconciler tick (60s cadence) for every active
                # schedule whose timer is already armed correctly. The
                # cancel+schedule pair is doing real work -- the new
                # asyncio.Task recomputes its sleep delay from a fresh
                # wall-clock reading of ``now``, which is what
                # re-anchors timers that drifted while the macOS host
                # was asleep -- but the (run_id, eta) pair is
                # unchanged, so logging INFO on every tick would
                # produce ~2880 duplicate lines per active schedule
                # per day with no audit value. The recreate branch
                # below (genuine reschedule, run-now, etc.) still logs
                # at INFO.
                runner.cancel(scheduled_agent_task_id, quiet=True)
                runner.schedule(
                    scheduled_agent_task_id,
                    only_pending["id"],
                    existing_utc,
                    quiet=True,
                )
                logger.debug(
                    "enqueue_scheduled_agent_task: reused pending run %s for scheduled agent task %s at %s (no DB churn)",
                    only_pending["id"],
                    scheduled_agent_task_id,
                    existing_utc.isoformat(),
                )
                return str(only_pending["id"])
        except Exception as exc:
            logger.warning(
                "enqueue_scheduled_agent_task: failed to reuse pending run %s; falling back to recreate (%s)",
                only_pending.get("id"),
                exc,
            )

    await repo.cancel_pending_runs_for_agent_task(scheduled_agent_task_id)
    get_async_scheduled_agent_task_runner().cancel(scheduled_agent_task_id)

    run = await repo.create_scheduled_run(
        scheduled_agent_task_id=scheduled_agent_task_id,
        scheduled_for=target_utc.isoformat(),
        status="scheduled",
    )
    get_async_scheduled_agent_task_runner().schedule(
        scheduled_agent_task_id,
        run["id"],
        target_utc,
    )
    return run["id"]


async def run_scheduled_agent_task_now(
    repo: "ScheduledAgentTaskRepository",
    scheduled_agent_task_id: str,
) -> str:
    from ..async_scheduled_agent_task_runner import get_async_scheduled_agent_task_runner

    now = utc_now()
    await repo.cancel_pending_runs_for_agent_task(scheduled_agent_task_id)
    get_async_scheduled_agent_task_runner().cancel(scheduled_agent_task_id)

    run = await repo.create_scheduled_run(
        scheduled_agent_task_id=scheduled_agent_task_id,
        scheduled_for=now.isoformat(),
        status="scheduled",
    )
    get_async_scheduled_agent_task_runner().schedule(
        scheduled_agent_task_id,
        run["id"],
        now,
    )
    return run["id"]


async def recover_missed_runs(repo: "ScheduledAgentTaskRepository") -> Dict[str, Any]:
    """Mark stale queued runs as missed and requeue due active scheduled agent tasks."""
    now_iso = utc_now().isoformat()
    missed_count = await repo.mark_missed_runs_before(now_iso)
    due = await repo.list_due_agent_tasks(now_iso)
    requeued = 0
    for scheduled_agent_task in due:
        next_run = compute_next_run_at(
            scheduled_agent_task["schedule_type"],
            scheduled_agent_task["schedule_config"],
            scheduled_agent_task["timezone"],
            from_time=utc_now(),
        )
        await repo.update_scheduled_agent_task(
            scheduled_agent_task["id"],
            last_status="missed" if missed_count > 0 else scheduled_agent_task.get("last_status"),
            next_run_at=next_run,
        )
        if next_run:
            await enqueue_scheduled_agent_task(repo, scheduled_agent_task["id"], next_run)
            requeued += 1
    return {"missed_runs": missed_count, "requeued_agent_tasks": requeued}


async def ensure_active_schedules_enqueued(repo: "ScheduledAgentTaskRepository") -> int:
    """Ensure active scheduled agent tasks with future next_run_at are enqueued once on startup."""
    scheduled_agent_tasks = await repo.list_active_scheduled_agent_tasks()
    now = utc_now()
    enqueued = 0
    for scheduled_agent_task in scheduled_agent_tasks:
        next_run_raw = scheduled_agent_task.get("next_run_at")
        if not next_run_raw:
            continue
        try:
            next_run = datetime.fromisoformat(str(next_run_raw).replace("Z", "+00:00"))
        except Exception:
            continue
        if next_run <= now:
            continue
        await enqueue_scheduled_agent_task(
            repo, scheduled_agent_task["id"], next_run.astimezone(timezone.utc).isoformat()
        )
        enqueued += 1
    return enqueued


async def finalize_run_after_execution(
    repo: "ScheduledAgentTaskRepository",
    db: "SQLiteKnowledgeService",
    *,
    scheduled_agent_task_id: str,
    run_id: str,
    success: bool,
    agent_task_id: Optional[str] = None,
    error_message: Optional[str] = None,
) -> Dict[str, Any]:
    now_iso = utc_now().isoformat()
    status = "completed" if success else "failed"

    # Defensive FK guard: scheduled_agent_task_runs.agent_task_id is a
    # foreign key into agent_tasks(id). Callers (notably the failure
    # branch in execute_scheduled_run) may pass a agent_task_id that was
    # minted by the scheduled-agent-tasks service but never actually
    # persisted into agent_tasks - for example when the orchestrator
    # raised before store_agent_task() ran, or when
    # process_agent_task_direct returned a structured error from its
    # cancellation/exception path. In those cases linking the run to a
    # nonexistent agent_tasks row would trip a SQLite FOREIGN KEY
    # constraint and abort the finalize, leaving the run stuck in
    # 'running'. The column is nullable (FK is ON DELETE SET NULL), so
    # storing NULL preserves the invariant and lets the run record its
    # final status with the error_message intact.
    if agent_task_id is not None:
        existing_agent_task = await db.get_agent_task(agent_task_id)
        if existing_agent_task is None:
            logger.warning(
                "Finalizing scheduled run %s without agent_task link: "
                "agent_tasks row %s does not exist (likely orchestrator "
                "failed before persisting the agent task).",
                run_id,
                agent_task_id,
            )
            agent_task_id = None

    await repo.update_scheduled_run(
        run_id,
        status=status,
        agent_task_id=agent_task_id,
        completed_at=now_iso,
        error_message=error_message,
    )
    scheduled_agent_task = await repo.get_scheduled_agent_task(scheduled_agent_task_id)
    if not scheduled_agent_task:
        return {"status": status, "next_run_at": None}

    # One-time schedules are, by definition, one-time. Without explicit
    # deactivation here ``compute_next_run_at`` would return the same
    # past ``run_at`` instant on every call, and re-enqueueing a past
    # eta would fire the runner immediately - i.e. a one-time scheduled agent task
    # would silently re-execute forever. Deactivate on success so the
    # row stops driving new runs; on failure leave ``is_active`` true
    # so the user can edit/retry the schedule from the UI.
    is_one_time = scheduled_agent_task["schedule_type"] == "one_time"
    if is_one_time and success:
        await repo.update_scheduled_agent_task(
            scheduled_agent_task_id,
            last_status=status,
            last_run_at=now_iso,
            clear_next_run_at=True,
            is_active=False,
        )
        return {"status": status, "next_run_at": None}

    next_run_at = None
    if scheduled_agent_task["is_active"] and not is_one_time:
        next_run_at = compute_next_run_at(
            scheduled_agent_task["schedule_type"],
            scheduled_agent_task["schedule_config"],
            scheduled_agent_task["timezone"],
            from_time=utc_now(),
        )
    await repo.update_scheduled_agent_task(
        scheduled_agent_task_id,
        last_status=status,
        last_run_at=now_iso,
        next_run_at=next_run_at,
    )
    if next_run_at and scheduled_agent_task["is_active"] and not is_one_time:
        await enqueue_scheduled_agent_task(repo, scheduled_agent_task_id, next_run_at)
    return {"status": status, "next_run_at": next_run_at}
