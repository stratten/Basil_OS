"""Per-call reasoning-effort override for OpenAI reasoning models.

The registry holds one default effort per model, and that default also serves agent chat, where deliberate reasoning is wanted.
Bulk background work such as memory summaries wants far less, so the caller scopes an override around its own model call instead of changing the registry.
The override lives in a context variable, so concurrent tasks each see only their own value.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

_override: ContextVar[Optional[str]] = ContextVar("openai_reasoning_effort_override", default=None)


def current_reasoning_effort_override() -> Optional[str]:
    return _override.get()


@contextmanager
def reasoning_effort_override(effort: Optional[str]) -> Iterator[None]:
    """Use *effort* for OpenAI reasoning calls made inside this block; None leaves the registry default in force."""
    token = _override.set(effort or None)
    try:
        yield
    finally:
        _override.reset(token)
