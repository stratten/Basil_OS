"""Authoritative backend lifecycle phase events."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

from .agent_timeline_contract import normalize_timeline_entry
from .workflow_status_notifier import WorkflowStatusNotifier


async def emit_activity_phase(
    state: Any,
    *,
    phase: str,
    lifecycle_state: str,
    title: str,
    source: str,
    error: Any = None,
) -> None:
    """Persist and broadcast one phase transition for the active graph run."""
    context = getattr(state, "context", None) or {}
    correlation_id = context.setdefault("activity_correlation_id", f"agent_run_{uuid4().hex}")
    coordinator = context.get("_workflow_coordinator")
    websocket_manager = getattr(coordinator, "_websocket_manager", None) or context.get("websocket_manager")
    notifier = WorkflowStatusNotifier(
        websocket_manager=websocket_manager,
        agent_task_id=context.get("agent_task_id"),
        root_task_id=context.get("root_task_id"),
        previous_task_id=context.get("previous_task_id"),
    )
    entry = normalize_timeline_entry(
        {
            "id": f"{correlation_id}_{phase}_{lifecycle_state}",
            "type": "phase",
            "detail_kind": "phase_transition",
            "content": title,
            "body": str(error)[:2000] if error else title,
            "metadata": {"error": str(error)[:500] if error else None},
            "streaming": False,
        },
        phase=phase,
        state=lifecycle_state,
        source=source,
        title=title,
        correlation_id=correlation_id,
    )
    await notifier.send_step_detail_update(entry=entry)
