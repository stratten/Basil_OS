"""Context variables for the currently executing agent task."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Dict, Optional


_current_agent_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "current_agent_context",
    default=None,
)


def set_current_agent_context(context: Optional[Dict[str, Any]]):
    """Set current agent context for tools invoked inside the agent run."""
    return _current_agent_context.set(context or {})


def reset_current_agent_context(token) -> None:
    """Reset current agent context to its previous value."""
    _current_agent_context.reset(token)


def get_current_agent_context() -> Dict[str, Any]:
    """Return current agent context, or an empty dict outside agent execution."""
    return _current_agent_context.get() or {}
