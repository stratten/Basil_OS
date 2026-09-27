"""Scheduled agent tasks orchestration service.

This is the application-layer service for the scheduled-agent-tasks feature. It
sits above the SQLite ``ScheduledAgentTaskRepository`` and below the route
handlers and agent tool. Responsibilities:

  * Translate natural-language scheduling requests into a strict structured
    schedule definition via an LLM (``interpret_schedule_prompt``). This
    supports a multi-turn clarification loop when the request is genuinely
    ambiguous about the *what* (the agent task itself, recurrence mode, etc.).
  * Compute the next UTC run instant from a structured schedule definition
    (``compute_next_run_at``), supporting one-time, daily, weekly, and
    interval recurrences in any IANA timezone.
  * Schedule due runs through the in-process
    ``AsyncScheduledAgentTaskRunner`` (``enqueue_scheduled_agent_task``,
    ``run_scheduled_agent_task_now``).
  * Recover gracefully on app startup: mark stale queued runs as missed and
    re-enqueue active scheduled agent tasks whose next run is in the future
    (``recover_missed_runs``, ``ensure_active_schedules_enqueued``).
  * Drive a queued run to completion via the voice listener service
    (``execute_scheduled_run``) and finalize result + next run
    (``finalize_run_after_execution``).

Naming history: this module was previously at
``api.services.scheduled_agent_tasks.scheduled_agent_task_service``. It lives here
because only one of its three consumers (the voice listener) has anything
to do with the voice listener subsystem -- the other two (the REST routes
and the LangChain agent tool) are independent of voice. The public method
that interprets natural-language scheduling prompts is named
``interpret_schedule_prompt`` because this is an LLM structured-generation
flow, not a string-manipulation step.

Architecture history: previously delegated execution to a Huey task in a
separate process, which round-tripped back through an internal HTTP
endpoint to reach the voice listener (which lives in the FastAPI process).
That layer was removed in favor of the in-process
``AsyncScheduledAgentTaskRunner``: SQLite remains the single source of truth
for what should run and when, the runner is just an ephemeral asyncio
timer rebuilt on every cold start from the database.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from api.dependencies import get_sqlite_knowledge_service

from .scheduled_agent_task_service_components import (
    schedule_interpretation,
    scheduled_run_execution,
    scheduled_run_lifecycle,
)
from .scheduled_agent_task_service_components.schedule_interpretation import (
    InterpretedScheduleContract,
)
from .scheduled_agent_task_service_components.scheduled_agent_task_runtime import (
    initialize_scheduled_agent_task_runtime,
    shutdown_scheduled_agent_task_runtime,
)
from .scheduled_agent_task_service_components.schedule_time_math import (
    compute_next_run_at,
    detect_local_timezone_name,
    utc_now,
)

__all__ = [
    "ScheduledAgentTaskService",
    # Re-exported from component modules so the historical import sites
    # (``from .scheduled_agent_task_service import X``) continue to resolve.
    "InterpretedScheduleContract",
    "initialize_scheduled_agent_task_runtime",
    "shutdown_scheduled_agent_task_runtime",
    "_detect_local_timezone_name",
]

# Module-level aliases preserve the historical underscore-prefixed names that
# both this module's own code and the package's ``__init__.py`` re-export
# (``_detect_local_timezone_name``). The implementations live in
# ``schedule_time_math``; keep these bindings in lockstep with the import
# above so any future rename of the underlying functions stays a single-edit
# change.
_utc_now = utc_now
_detect_local_timezone_name = detect_local_timezone_name

logger = logging.getLogger(__name__)


class ScheduledAgentTaskService:
    """Coordinates schedule persistence, next-run calculation, and task enqueueing."""

    def __init__(self) -> None:
        self.db = get_sqlite_knowledge_service()
        # Cached for the lifetime of this instance so the dozen-plus
        # delegate methods don't each have to re-traverse ``self.db``.
        self._repo = self.db.scheduled_agent_task_repository

    def compute_next_run_at(
        self,
        schedule_type: str,
        schedule_config: Dict[str, Any],
        timezone_name: str,
        *,
        from_time: Optional[datetime] = None,
    ) -> Optional[str]:
        """Compute next UTC ISO timestamp from schedule definition.

        Thin facade over the free-function implementation in
        ``schedule_time_math``; preserved as an instance method because
        consumers (REST handlers, the schedule interpreter, recovery code)
        already call it via the service. New callers inside this package
        should prefer the free function directly.
        """
        return compute_next_run_at(
            schedule_type, schedule_config, timezone_name, from_time=from_time
        )

    async def create_scheduled_agent_task(
        self,
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
        return await scheduled_run_lifecycle.create_scheduled_agent_task(
            self._repo,
            title=title,
            agent_task_text=agent_task_text,
            schedule_type=schedule_type,
            schedule_config=schedule_config,
            timezone_name=timezone_name,
            source_type=source_type,
            is_active=is_active,
            reference_paths=reference_paths,
        )

    async def list_scheduled_agent_tasks(self, include_inactive: bool = True) -> List[Dict[str, Any]]:
        return await self._repo.list_scheduled_agent_tasks(include_inactive=include_inactive)

    async def get_scheduled_agent_task(self, scheduled_agent_task_id: str) -> Optional[Dict[str, Any]]:
        return await self._repo.get_scheduled_agent_task(scheduled_agent_task_id)

    async def update_scheduled_agent_task(self, scheduled_agent_task_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await scheduled_run_lifecycle.update_scheduled_agent_task(
            self._repo, scheduled_agent_task_id, updates
        )

    async def delete_scheduled_agent_task(self, scheduled_agent_task_id: str) -> bool:
        return await self._repo.delete_scheduled_agent_task(scheduled_agent_task_id)

    async def list_runs_for_agent_task(self, scheduled_agent_task_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        return await self._repo.list_runs_for_agent_task(scheduled_agent_task_id, limit=limit)

    async def enqueue_scheduled_agent_task(self, scheduled_agent_task_id: str, scheduled_for_iso: str) -> str:
        """Delegate to ``scheduled_run_lifecycle.enqueue_scheduled_agent_task``.

        See that module for the full idempotency-and-cancellation contract.
        """
        return await scheduled_run_lifecycle.enqueue_scheduled_agent_task(
            self._repo, scheduled_agent_task_id, scheduled_for_iso
        )

    async def run_scheduled_agent_task_now(self, scheduled_agent_task_id: str) -> str:
        return await scheduled_run_lifecycle.run_scheduled_agent_task_now(
            self._repo, scheduled_agent_task_id
        )

    async def recover_missed_runs(self) -> Dict[str, Any]:
        return await scheduled_run_lifecycle.recover_missed_runs(self._repo)

    async def ensure_active_schedules_enqueued(self) -> int:
        return await scheduled_run_lifecycle.ensure_active_schedules_enqueued(self._repo)

    async def finalize_run_after_execution(
        self,
        *,
        scheduled_agent_task_id: str,
        run_id: str,
        success: bool,
        agent_task_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await scheduled_run_lifecycle.finalize_run_after_execution(
            self._repo,
            self.db,
            scheduled_agent_task_id=scheduled_agent_task_id,
            run_id=run_id,
            success=success,
            agent_task_id=agent_task_id,
            error_message=error_message,
        )

    async def interpret_schedule_prompt(
        self,
        user_prompt: str,
        context_id: Optional[str] = None,
        *,
        user_timezone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Delegate to ``schedule_interpretation.interpret_schedule_prompt``.

        See that module for full semantics (timezone resolution, model
        selection, validation/retry, clarification threading via the
        process-singleton ``_INTERPRETATION_CONTEXTS`` store).
        """
        return await schedule_interpretation.interpret_schedule_prompt(
            user_prompt,
            context_id,
            user_timezone=user_timezone,
        )

    async def execute_scheduled_run(self, scheduled_agent_task_id: str, run_id: str) -> Dict[str, Any]:
        """Delegate to ``scheduled_run_execution.execute_scheduled_run``.

        See that module for the full submission/await/finalize contract,
        including the process-singleton ``_PENDING_AGENT_TASK_COMPLETIONS``
        map that bridges agent_task terminal events back to the
        awaiting run.
        """
        return await scheduled_run_execution.execute_scheduled_run(
            self._repo, self.db, scheduled_agent_task_id, run_id
        )


