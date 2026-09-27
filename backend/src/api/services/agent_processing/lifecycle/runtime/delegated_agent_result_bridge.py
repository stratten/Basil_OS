"""Executor-neutral terminal-event bridge for durable delegated children."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.events import AgentTaskEvent
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.delegated_agent_repository import (
    DelegatedAgentConflictError,
)

logger = logging.getLogger(__name__)
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


def _bounded_summary(event: AgentTaskEvent) -> str:
    result_data = (event.agent_task_data or {}).get("result_data")
    if isinstance(result_data, str):
        try:
            result_data = json.loads(result_data)
        except json.JSONDecodeError:
            result_data = {}
    if not isinstance(result_data, Mapping):
        result_data = {}
    value = result_data.get("message") or result_data.get("workflow_result") or (
        f"Delegated child finished with status {event.new_status}."
    )
    return str(value).encode("utf-8", errors="replace")[:2_000].decode("utf-8", errors="ignore")


class DelegatedAgentResultBridge:
    """Record generic evidence first; provider-target relations have no lifecycle role."""

    def __init__(
        self,
        *,
        delegated_agent_repository: Any,
        delegated_agent_controller: Any,
        routing_service: Any | None = None,
        **_unused: Any,
    ) -> None:
        self._runs = delegated_agent_repository
        self._controller = delegated_agent_controller
        self._routing = routing_service
        self._tasks: set[asyncio.Task[None]] = set()

    def handle_agent_task_event(self, event: AgentTaskEvent) -> None:
        if event.event_type != "status_changed" or event.new_status not in _TERMINAL_STATUSES:
            return
        try:
            task = asyncio.get_running_loop().create_task(
                self._record_terminal_child(event), name=f"delegated-agent-result:{event.agent_task_id}"
            )
        except RuntimeError:
            logger.warning("Delegated child terminal event arrived without a running event loop")
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _record_terminal_child(self, event: AgentTaskEvent) -> None:
        run = await self._runs.get_run_for_child(event.agent_task_id)
        if run is None or run["status"] in {"settled", "failed", "cancelled"}:
            return
        status = str(event.new_status)
        try:
            await self._controller.settle_run_and_maybe_resume_parent(
                delegated_agent_run=run,
                child_status=status,
                summary=_bounded_summary(event),
                evidence_state="provider_reported" if status == "completed" else "unavailable",
                receipt_references=[],
            )
        except DelegatedAgentConflictError:
            refreshed = await self._runs.get_run_for_child(event.agent_task_id)
            if refreshed is None or refreshed["status"] not in {"settled", "failed", "cancelled"}:
                raise
        if self._routing is not None and hasattr(self._routing, "publish_delegated_provider_state"):
            await self._routing.publish_delegated_provider_state(
                parent_agent_task_id=str(run["parent_agent_task_id"]),
                root_task_id=str(run["root_task_id"]),
                delegation_id=str(run["id"]),
                state=f"delegated_child_{status}",
                message=f"Delegated child {status}.",
            )

    async def request_parent_cancellation(self, parent_agent_task_id: str) -> str | None:
        cancelled = await self._controller.cancel_parent_runs(parent_agent_task_id=parent_agent_task_id)
        return str(cancelled[0]["child_agent_task_id"]) if cancelled else None

    async def reconcile_startup(self) -> int:
        """Truthfully mark ACP runs interrupted when their live session was lost."""

        count = 0
        for run in await self._runs.list_restart_reconciliation_candidates():
            if run["executor_kind"] != "acp_provider" or run["status"] in {"cancelling", "interrupted"}:
                continue
            interrupted = await self._runs.transition_run(
                delegated_agent_run_id=str(run["id"]),
                expected_revision=int(run["revision"]),
                next_status="interrupted",
            )
            await self._controller.settle_run_and_maybe_resume_parent(
                delegated_agent_run=interrupted,
                child_status="failed",
                summary="ACP delegated session was interrupted by process restart before settlement.",
                evidence_state="unavailable",
                receipt_references=[],
            )
            count += 1
        return count
