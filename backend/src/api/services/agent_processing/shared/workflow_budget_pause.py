"""Pause the active workflow's time budget while Basil waits on someone else."""

from __future__ import annotations

import contextlib
from typing import Any, Iterator, Optional

from .agent_runtime_context import get_current_agent_context


def current_pausable_deadline() -> Optional[Any]:
    """Return the current workflow deadline when it supports pausing.

    Duck-typed on purpose: ``shared`` must not import ``lifecycle.execution_graph`` (that package imports ``shared`` and would form an import cycle).
    """
    context = get_current_agent_context()
    candidate = context.get("_workflow_deadline") if isinstance(context, dict) else None
    if callable(getattr(candidate, "begin_pause", None)) and callable(getattr(candidate, "end_pause", None)):
        return candidate
    return None


@contextlib.contextmanager
def pause_workflow_budget(reason: str) -> Iterator[bool]:
    """Exclude the enclosed wait from the current workflow budget.

    Yields True when a pausable deadline was found, False outside agent execution.
    """
    deadline = current_pausable_deadline()
    if deadline is None:
        yield False
        return
    deadline.begin_pause(reason)
    try:
        yield True
    finally:
        deadline.end_pause(reason)


__all__ = ["current_pausable_deadline", "pause_workflow_budget"]
