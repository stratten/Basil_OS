"""Race an awaiting future against an optional timeout and cancellation event.

Consolidates the "wait for X, but bail out cleanly on a cancel_event or a
deadline" pattern so callers (e.g. the Swift MCP token bridge) do not each
reimplement the asyncio.wait bookkeeping. This mirrors the cancel_event race
already used by the inner agent loop runner (``drive_agent_loop``) and
final-answer synthesis, but returns a structured outcome instead of raising so
callers can degrade gracefully rather than tearing down the whole run.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional, Tuple


async def await_future_with_cancellation(
    future: "asyncio.Future",
    *,
    timeout_s: Optional[float],
    cancel_event: Optional[Any],
) -> Tuple[str, Any]:
    """Wait for ``future`` while honoring a timeout and a cancellation event.

    The caller retains ownership of ``future``; this helper never cancels it,
    so a late resolver simply finds the waiter already unregistered by the
    caller. Only the internal cancel-event waiter task is cleaned up here.

    Args:
        future: The awaitable the caller is waiting on (typically an
            ``asyncio.Future`` registered in a waiter map).
        timeout_s: Maximum seconds to wait, or ``None`` for no deadline.
        cancel_event: An object exposing ``is_set()`` and ``wait()`` (an
            ``asyncio.Event``), or ``None`` when cancellation is not tracked.

    Returns:
        A ``(kind, value)`` tuple:
          * ``("canceled", None)`` if ``cancel_event`` fires first (or is
            already set when called). Cancellation is checked first so a user
            cancel always wins a simultaneous resolution.
          * ``("timeout", None)`` if ``timeout_s`` elapses first.
          * ``("resolved", result)`` carrying the future's result otherwise.
    """
    has_cancel = cancel_event is not None and hasattr(cancel_event, "wait")

    if not has_cancel:
        if timeout_s is None:
            return ("resolved", await future)
        try:
            return ("resolved", await asyncio.wait_for(future, timeout=timeout_s))
        except asyncio.TimeoutError:
            return ("timeout", None)

    if hasattr(cancel_event, "is_set") and cancel_event.is_set():
        return ("canceled", None)

    cancel_task = asyncio.ensure_future(cancel_event.wait())
    try:
        done, _pending = await asyncio.wait(
            {future, cancel_task},
            timeout=timeout_s,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancel_task in done and not cancel_task.cancelled():
            return ("canceled", None)
        if future in done:
            return ("resolved", future.result())
        return ("timeout", None)
    finally:
        if not cancel_task.done():
            cancel_task.cancel()
