"""Process-wide access to the agent-task cancellation registry for code outside the orchestrator."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

_registry: Any = None


def set_process_cancellation_registry(registry: Any) -> None:
    global _registry
    _registry = registry


def process_cancellation_registry() -> Any:
    return _registry


def resolve_run_cancel_event(context: Any) -> Optional[Any]:
    """Return the run's cancel signal, falling back to the registry when a resumed state lost it."""
    if not isinstance(context, Mapping):
        return None
    cancel_event = context.get("cancel_event")
    if cancel_event is not None and hasattr(cancel_event, "is_set"):
        return cancel_event
    agent_task_id = str(context.get("agent_task_id") or "").strip()
    registry = _registry
    if registry is None or not agent_task_id:
        return None
    return registry.get_cancellation_event(agent_task_id)
