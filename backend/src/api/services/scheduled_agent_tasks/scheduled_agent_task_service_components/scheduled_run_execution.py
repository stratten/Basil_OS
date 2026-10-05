"""Execute a single queued scheduled run end-to-end.

Drives one ``scheduled_agent_task_runs`` row from ``scheduled`` to a terminal
status by submitting the agent task through the voice listener service,
waiting on the resulting agent_task's terminal-status event via an
``asyncio.Future``, and finalizing the run row (including chaining the
parent schedule's next occurrence).

Owns the process-singleton state that bridges
``SqliteKnowledgeService.register_agent_task_callback`` (a synchronous
callback fired when any agent tasks row changes status) to the
``asyncio.Future`` an in-flight ``execute_scheduled_run`` is awaiting.

Module-level state (intentionally not on any class):
    _PENDING_AGENT_TASK_COMPLETIONS  -- agent_task_id -> Future awaiting terminal status.
    _callback_registered          -- idempotency guard for callback registration.

Layering: depends on ``schedule_time_math`` and ``scheduled_run_lifecycle``
plus the ``SqliteKnowledgeService`` accessor; must NOT import the runtime
or facade modules.
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import logging
import sys
import uuid
from typing import Any, Dict, Iterator, Optional, TYPE_CHECKING

from api.dependencies import get_sqlite_knowledge_service

from . import scheduled_run_lifecycle
from .schedule_time_math import utc_now

if TYPE_CHECKING:
    from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
    from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.scheduling.repository import (
        ScheduledAgentTaskRepository,
    )
    from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.events import (
        AgentTaskEvent,
    )

logger = logging.getLogger(__name__)


# Agent-task statuses that signal the orchestrator is done with this
# agent task -- one of these landing on the row is what tells a scheduled run
# that its underlying agent has actually finished, as opposed to merely
# being submitted. Anything not in this set is an in-flight intermediate
# state (``routing``, ``processing``, ``needs_clarification``, etc.) that
# we want to keep waiting through.
_TERMINAL_MINION_STATUSES = frozenset({"completed", "failed", "canceled"})


# Upper bound on how long ``execute_scheduled_run`` will wait for an agent
# task's terminal status event before giving up and finalizing the run
# as failed. Sized for genuinely long agentic workflows -- the goal is not
# to interrupt real work, only to guarantee that a permanently-stuck
# agent_task_id (e.g. orchestrator crashed before persisting the final
# status, or a callback dispatch dropped the event) does not pin the
# scheduled_agent_task_runs row in ``running`` indefinitely. Recovery on the
# next process restart will sweep anything that survives this.
_SCHEDULED_RUN_COMPLETION_TIMEOUT_SECONDS = 60 * 60  # 60 minutes


# Per-process map from agent_task.id (the agent_task_id minted by
# ``execute_scheduled_run`` for a scheduled run) to an asyncio.Future that
# the run is awaiting. Resolved by ``handle_agent_task_event`` when the
# matching agent tasks row reaches a terminal status. Module-level
# (rather than on a class) because the callback registration is process-
# singleton -- the dispatcher needs a stable place to find the waiter
# regardless of which ``ScheduledAgentTaskService`` instance enqueued it.
_PENDING_AGENT_TASK_COMPLETIONS: Dict[str, "asyncio.Future[Dict[str, Any]]"] = {}


# Idempotency guard for ``ensure_agent_task_callback_registered``.
# The runtime initializer runs at FastAPI startup; in test fixtures it can
# run more than once per process, and we never want two copies of
# ``handle_agent_task_event`` registered against the same event manager
# (would resolve every future twice and leak callbacks).
_callback_registered: bool = False


def handle_agent_task_event(event: "AgentTaskEvent") -> None:
    """Resolve any pending scheduled-run future when its agent_task terminates.

    Wired into ``SqliteKnowledgeService.register_agent_task_callback``
    once at process startup by ``ensure_agent_task_callback_registered``.
    The callback is synchronous (the event manager will dispatch it inline
    on whatever loop owns the ``update_agent_task_status`` call), so we
    just flip the future directly -- no thread bridging needed because the
    future was created on the same FastAPI event loop.

    Filters:
      * Only ``status_changed`` events matter -- we don't care about
        ``created`` (the row was just inserted, agent hasn't even started)
        or ``updated`` (intermediate metadata changes).
      * Only terminal new statuses count -- intermediate transitions
        (``routing`` -> ``processing`` -> ...) keep the run waiting.

    If no run is waiting on this scheduled agent task_id (the common case -- most
    agent tasks are not scheduled), this is a cheap no-op.
    """
    if event.event_type != "status_changed":
        return
    if event.new_status not in _TERMINAL_MINION_STATUSES:
        return
    future = _PENDING_AGENT_TASK_COMPLETIONS.get(event.agent_task_id)
    if future is None or future.done():
        return
    try:
        future.set_result(
            {
                "status": event.new_status,
                "agent_task_data": event.agent_task_data or {},
            }
        )
    except Exception as exc:
        # Future may have been bound to a loop that's already closed
        # during shutdown. Nothing actionable for the dispatcher beyond
        # logging.
        logger.warning(
            "scheduled_run_execution: failed to resolve completion future "
            "for agent_task_id=%s: %s",
            event.agent_task_id,
            exc,
        )


# ---------------------------------------------------------------------------
# macOS power assertion: prevent idle system sleep while a scheduled run is
# in flight.
#
# Why this exists: on May 22 2026 the 8 PM scheduled task ran for 957 s
# (~16 min) -- exactly the duration the laptop spent in Maintenance Sleep
# on battery, confirmed via ``pmset -g log``. The ``osascript`` subprocess
# the agent had launched 26 s before sleep was suspended at the kernel
# level along with the rest of user-space, and Python's monotonic-clock
# timeouts (the 90 s ``email_read_applescript_timeout`` in
# ``execute_applescript``) did not fire because monotonic clocks do not
# advance through OS sleep. This made the scheduled task's wall clock
# inflate by the sleep duration and crowded out the rest of the run.
#
# Fix: hold a ``PreventUserIdleSystemSleep`` IOPM assertion (the same one
# ``caffeinate -i`` holds) for the exact window a scheduled run is in
# ``running`` status. This blocks idle / maintenance sleep, but it does NOT
# block user-initiated lid-close / power-button sleep -- the user can still
# deliberately put the machine to sleep.
#
# Implementation uses ``ctypes`` directly against IOKit + CoreFoundation
# (two symbols total) so we don't add a pyobjc dependency. The non-macOS
# path is a silent no-op so unit tests on Linux CI behave correctly.


_IOPM_ASSERTION_LEVEL_ON = 255
_KCF_STRING_ENCODING_UTF8 = 0x08000100
_IO_RETURN_SUCCESS = 0


def _load_power_assertion_frameworks() -> Optional[Dict[str, Any]]:
    """Load IOKit + CoreFoundation lazily; return None when unavailable."""
    if sys.platform != "darwin":
        return None
    try:
        iokit = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    except OSError:
        return None

    cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    cf.CFRelease.restype = None

    iokit.IOPMAssertionCreateWithName.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    iokit.IOPMAssertionCreateWithName.restype = ctypes.c_int
    iokit.IOPMAssertionRelease.argtypes = [ctypes.c_uint32]
    iokit.IOPMAssertionRelease.restype = ctypes.c_int

    return {"iokit": iokit, "cf": cf}


# Loaded once at import time. ``None`` on non-macOS hosts and on any
# darwin host where the frameworks somehow fail to dlopen.
_POWER_ASSERTION_LIBS = _load_power_assertion_frameworks()


def _acquire_prevent_idle_system_sleep(name: str) -> Optional[int]:
    """Create a ``PreventUserIdleSystemSleep`` assertion; return its id or None.

    Returns ``None`` (and logs at WARN, once per call) on:
      - non-macOS / framework-missing hosts,
      - any IOKit return code that isn't ``kIOReturnSuccess``.

    Callers MUST treat ``None`` as "no assertion was held" and continue
    -- power policy is best-effort, never a hard requirement for the
    scheduled run itself.
    """
    if _POWER_ASSERTION_LIBS is None:
        logger.debug(
            "scheduled_run_execution: skipping idle-sleep assertion "
            "(platform=%s, frameworks_available=False)",
            sys.platform,
        )
        return None
    cf = _POWER_ASSERTION_LIBS["cf"]
    iokit = _POWER_ASSERTION_LIBS["iokit"]

    assertion_type_cf = cf.CFStringCreateWithCString(
        None, b"PreventUserIdleSystemSleep", _KCF_STRING_ENCODING_UTF8
    )
    assertion_name_cf = cf.CFStringCreateWithCString(
        None, name.encode("utf-8"), _KCF_STRING_ENCODING_UTF8
    )
    if not assertion_type_cf or not assertion_name_cf:
        # CFStringCreateWithCString returned NULL; nothing to release on
        # the NULL slot but free whichever one did succeed to be safe.
        if assertion_type_cf:
            cf.CFRelease(assertion_type_cf)
        if assertion_name_cf:
            cf.CFRelease(assertion_name_cf)
        logger.warning(
            "⚠️ scheduled_run_execution: CFStringCreateWithCString returned NULL "
            "while building idle-sleep assertion for %s",
            name,
        )
        return None

    assertion_id = ctypes.c_uint32(0)
    rc = iokit.IOPMAssertionCreateWithName(
        assertion_type_cf,
        _IOPM_ASSERTION_LEVEL_ON,
        assertion_name_cf,
        ctypes.byref(assertion_id),
    )
    # Assertion APIs retain their own copies of the CFStrings, so we
    # release ours immediately. Leaking these would slowly bloat the
    # process.
    cf.CFRelease(assertion_type_cf)
    cf.CFRelease(assertion_name_cf)

    if rc != _IO_RETURN_SUCCESS:
        logger.warning(
            "⚠️ scheduled_run_execution: IOPMAssertionCreateWithName(%s) "
            "returned rc=%s; running without idle-sleep assertion",
            name,
            rc,
        )
        return None

    logger.info(
        "scheduled_run_execution: acquired PreventUserIdleSystemSleep "
        "assertion id=%s name=%s",
        assertion_id.value,
        name,
    )
    return int(assertion_id.value)


def _release_prevent_idle_system_sleep(assertion_id: Optional[int], name: str) -> None:
    """Release the previously-acquired assertion. No-op on ``None``."""
    if assertion_id is None or _POWER_ASSERTION_LIBS is None:
        return
    iokit = _POWER_ASSERTION_LIBS["iokit"]
    rc = iokit.IOPMAssertionRelease(ctypes.c_uint32(assertion_id))
    if rc != _IO_RETURN_SUCCESS:
        logger.warning(
            "⚠️ scheduled_run_execution: IOPMAssertionRelease(id=%s, name=%s) "
            "returned rc=%s",
            assertion_id,
            name,
            rc,
        )
        return
    logger.info(
        "scheduled_run_execution: released PreventUserIdleSystemSleep "
        "assertion id=%s name=%s",
        assertion_id,
        name,
    )


@contextlib.contextmanager
def _prevent_idle_system_sleep_for_scheduled_run(
    scheduled_agent_task_id: str, run_id: str
) -> Iterator[Optional[int]]:
    """Hold an idle-sleep-preventing assertion for the duration of the block.

    The assertion is scoped per-run so concurrent scheduled runs each get
    their own assertion id (the runner is unbounded across distinct
    ``scheduled_agent_task_id``s). Yields the assertion id (or ``None`` on
    skip paths) for callers that want to log / assert on it.
    """
    name = f"basil.scheduled_run:{scheduled_agent_task_id}:{run_id}"
    assertion_id = _acquire_prevent_idle_system_sleep(name)
    try:
        yield assertion_id
    finally:
        _release_prevent_idle_system_sleep(assertion_id, name)


def ensure_agent_task_callback_registered() -> None:
    """Register the agent_task status callback exactly once per process.

    Called from ``initialize_scheduled_agent_task_runtime`` during FastAPI
    startup, before any scheduled runs can be dispatched. Idempotent so
    re-running the initializer (test fixtures, hot-reload scenarios) is
    safe.
    """
    global _callback_registered
    if _callback_registered:
        return
    db = get_sqlite_knowledge_service()
    db.register_agent_task_callback(handle_agent_task_event)
    _callback_registered = True
    logger.info(
        "scheduled_run_execution: registered agent_task status callback "
        "for scheduled-run completion tracking"
    )


async def execute_scheduled_run(
    repo: "ScheduledAgentTaskRepository",
    db: "SQLiteKnowledgeService",
    scheduled_agent_task_id: str,
    run_id: str,
) -> Dict[str, Any]:
    """Execute a queued scheduled run and persist completion status."""
    # Defensive idempotency: a run can reach this method via the
    # in-process runner's timer after the run row was already
    # canceled, missed, or finalized by another path (e.g. user
    # toggled the schedule inactive while we were sleeping, or the
    # row was marked missed by recover_missed_runs on an earlier
    # crash that we somehow survived). Refusing to execute anything
    # that isn't still in 'scheduled' status prevents a stale timer
    # from clobbering a row that already has a terminal state.
    run_row = await repo.get_scheduled_run(run_id)
    if run_row is None:
        logger.warning(
            "execute_scheduled_run: run %s not found; skipping",
            run_id,
        )
        return {"success": False, "error": "Run not found"}
    if run_row["status"] != "scheduled":
        logger.info(
            "execute_scheduled_run: run %s no longer scheduled (status=%s); skipping",
            run_id,
            run_row["status"],
        )
        return {"success": False, "error": f"Run status is {run_row['status']}"}

    scheduled_agent_task = await repo.get_scheduled_agent_task(scheduled_agent_task_id)
    if not scheduled_agent_task:
        await repo.update_scheduled_run(
            run_id,
            status="failed",
            completed_at=utc_now().isoformat(),
            error_message="Scheduled task not found",
        )
        return {"success": False, "error": "Scheduled task not found"}

    if not scheduled_agent_task["is_active"]:
        await repo.update_scheduled_run(
            run_id,
            status="skipped",
            completed_at=utc_now().isoformat(),
            error_message="Scheduled task is inactive",
        )
        return {"success": False, "error": "Scheduled task is inactive"}

    started_at = utc_now().isoformat()
    agent_task_id = str(uuid.uuid4())
    # NOTE: scheduled_agent_task_runs.agent_task_id is a FK into
    # agent tasks(id). The matching agent tasks row is not created
    # until process_agent_task_direct() runs below, so we deliberately
    # do NOT set agent_task_id here - doing so would trip a SQLite
    # FOREIGN KEY constraint and abort the run before execution. The
    # link is established later in finalize_run_after_execution(), which
    # is invoked after the agent tasks row has been inserted.
    #
    # The ``with`` block holds a PreventUserIdleSystemSleep IOPM
    # assertion for the entire duration the row is in ``running``
    # status. See the module-level helper docstring for why -- the
    # short version is "macOS Maintenance Sleep on battery suspended
    # an in-flight osascript subprocess for 957 s on 2026-05-22, and
    # Python's monotonic timeouts can't catch that because monotonic
    # clocks freeze through sleep". Acquiring the assertion here is
    # best-effort; the helper logs a WARN and returns ``None`` on any
    # failure path so the run still proceeds without sleep protection
    # rather than aborting outright.
    with _prevent_idle_system_sleep_for_scheduled_run(
        scheduled_agent_task_id=scheduled_agent_task_id,
        run_id=run_id,
    ):
        await repo.update_scheduled_run(
            run_id,
            status="running",
            started_at=started_at,
        )

        agent_task_submission_service = None
        try:
            from api.main import app

            agent_task_submission_service = getattr(app.state, "agent_task_submission_service", None)
        except Exception:
            agent_task_submission_service = None

        if agent_task_submission_service and hasattr(agent_task_submission_service, "broadcast"):
            await agent_task_submission_service.broadcast(
                {
                    "event_type": "scheduled_agent_task_run_started",
                    "scheduled_agent_task_id": scheduled_agent_task_id,
                    "run_id": run_id,
                    "agent_task_id": agent_task_id,
                    "title": scheduled_agent_task["title"],
                }
            )

        # Register the completion future BEFORE submitting the agent task. If we
        # registered after, the orchestrator could conceivably race past the
        # terminal status_changed event for very short agent tasks, leaving the
        # future unresolved and the run stuck waiting on its timeout.
        loop = asyncio.get_running_loop()
        completion_future: asyncio.Future = loop.create_future()
        _PENDING_AGENT_TASK_COMPLETIONS[agent_task_id] = completion_future

        try:
            if not agent_task_submission_service:
                raise RuntimeError("Task submission service unavailable")

            # Submission. ``process_agent_task_direct`` returns once the
            # agent tasks row has been inserted and the event-driven
            # orchestrator has taken over -- it does NOT block until the
            # agent finishes. Completion arrives later via the
            # agent_task status callback wired in
            # ``ensure_agent_task_callback_registered``.
            # ``reference_paths`` is the list of absolute filesystem paths the
            # user attached to the schedule via the editor. Stored on
            # ``scheduled_agent_tasks`` as a JSON array; the repository decodes
            # to a list of strings (or [] when nothing is attached). We pass
            # ``None`` rather than an empty list so the voice listener treats
            # "no attachments" identically to interactive captures that omit
            # the field entirely.
            attached_paths = scheduled_agent_task.get("reference_paths") or None
            submission_result = await agent_task_submission_service.process_agent_task_direct(
                agent_task=scheduled_agent_task["agent_task_text"],
                agent_task_id=agent_task_id,
                reference_paths=attached_paths,
                origin_type="scheduled_task",
                origin_id=scheduled_agent_task_id,
            )

            # Hard synchronous failures (cancellation gate, exception path,
            # any pre-flight rejection that surfaces success=False before the
            # agent tasks row is even ready) won't ever produce a
            # terminal status_changed event for this scheduled agent task_id -- the
            # callback would never fire and we'd just sit on the timeout.
            # Detect those and finalize immediately with the submission
            # error.
            submission_success = (submission_result or {}).get("success")
            if submission_success is False:
                success = False
                error_message = (
                    (submission_result or {}).get("error")
                    or (submission_result or {}).get("message")
                    or (submission_result or {}).get("reasoning")
                    or "Task submission failed"
                )
                logger.warning(
                    "execute_scheduled_run: synchronous submission failure for "
                    "scheduled_agent_task_id=%s run_id=%s: %s",
                    scheduled_agent_task_id,
                    run_id,
                    error_message,
                )
            else:
                # process_agent_task_direct returned success, which means the
                # agent_tasks row backing this run has been inserted -- the FK
                # constraint that forced us to leave
                # scheduled_agent_task_runs.agent_task_id NULL at status=running
                # time (see the long comment above where agent_task_id is
                # minted) is now satisfied. Write the link NOW so that
                # /agent-task-runs/active -- the mini panel's hydration source
                # -- returns the real agent_task_id for the rest of the run,
                # instead of NULL until finalize_run_after_execution finally
                # writes it. Without this, every panel that opens after
                # run_started fires (i.e. the dominant case, because the
                # NSPanel is created lazily on that event so its WKWebView's
                # WS isn't connected yet) hydrates rows with agentTaskId
                # undefined and every match-by-agent_task_id handler in
                # App.tsx silently no-ops -- broken row click, no streaming
                # updates. finalize_run_after_execution still writes the same
                # column on success and failure paths; this earlier write is
                # idempotent and harmless.
                await repo.update_scheduled_run(
                    run_id,
                    agent_task_id=agent_task_id,
                )

                # Wait for the orchestrator to drive the agent_task to a
                # terminal state. Long-running agentic tasks are normal.
                # The timeout is a safety valve so a never-resolving future
                # cannot pin the run row in 'running' forever.
                try:
                    payload = await asyncio.wait_for(
                        completion_future,
                        timeout=_SCHEDULED_RUN_COMPLETION_TIMEOUT_SECONDS,
                    )
                    completion_status = payload["status"]
                    success = completion_status == "completed"
                    if success:
                        error_message = None
                    else:
                        # Pull a useful failure message from the
                        # agent_task's result_data when the orchestrator
                        # stored one; otherwise synthesize a generic message
                        # mentioning the terminal status.
                        agent_task_data = payload.get("agent_task_data") or {}
                        result_data = agent_task_data.get("result_data") or {}
                        candidate_msg: Optional[str] = None
                        if isinstance(result_data, dict):
                            candidate_msg = result_data.get("error") or result_data.get("message")
                        error_message = (
                            candidate_msg
                            or f"Task ended with status '{completion_status}'"
                        )
                except asyncio.TimeoutError:
                    success = False
                    error_message = (
                        f"Scheduled task timed out waiting for the task to finish "
                        f"after {_SCHEDULED_RUN_COMPLETION_TIMEOUT_SECONDS}s"
                    )
                    logger.warning(
                        "execute_scheduled_run: timeout waiting for agent_task %s "
                        "to reach a terminal status",
                        agent_task_id,
                    )

            final = await scheduled_run_lifecycle.finalize_run_after_execution(
                repo,
                db,
                scheduled_agent_task_id=scheduled_agent_task_id,
                run_id=run_id,
                success=success,
                agent_task_id=agent_task_id,
                error_message=error_message,
            )
            if agent_task_submission_service and hasattr(agent_task_submission_service, "broadcast"):
                await agent_task_submission_service.broadcast(
                    {
                        "event_type": "scheduled_agent_task_run_completed",
                        "scheduled_agent_task_id": scheduled_agent_task_id,
                        "run_id": run_id,
                        "agent_task_id": agent_task_id,
                        "status": final["status"],
                        "next_run_at": final["next_run_at"],
                    }
                )
            return {"success": success, "agent_task_id": agent_task_id, "status": final["status"]}
        except Exception as exc:
            # Catch-all for genuinely exceptional submission paths (raises out
            # of ``process_agent_task_direct``, attribute errors, etc.).
            # The wait branch above does NOT raise on agent failure -- the
            # future resolves with status='failed' and we go through the
            # normal finalize path. So reaching here means the submission
            # itself blew up in a way the synchronous-failure check above
            # didn't catch.
            final = await scheduled_run_lifecycle.finalize_run_after_execution(
                repo,
                db,
                scheduled_agent_task_id=scheduled_agent_task_id,
                run_id=run_id,
                success=False,
                agent_task_id=agent_task_id,
                error_message=str(exc),
            )
            if agent_task_submission_service and hasattr(agent_task_submission_service, "broadcast"):
                await agent_task_submission_service.broadcast(
                    {
                        "event_type": "scheduled_agent_task_run_completed",
                        "scheduled_agent_task_id": scheduled_agent_task_id,
                        "run_id": run_id,
                        "agent_task_id": agent_task_id,
                        "status": final["status"],
                        "error": str(exc),
                        "next_run_at": final["next_run_at"],
                    }
                )
            raise
        finally:
            # Always release the future slot, whether we resolved it via the
            # callback, hit the timeout, or raised out of submission. Leaking
            # entries here would slowly fill the module-level dict with stale
            # agent_task_ids and (more importantly) prevent a future run that
            # somehow reused the same agent_task_id from binding its own
            # waiter.
            _PENDING_AGENT_TASK_COMPLETIONS.pop(agent_task_id, None)
