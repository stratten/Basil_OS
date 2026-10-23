"""Process-wide freeze gate for the Skill Reconciliation Workspace.

While a reconciliation workspace window is open, the app must not let background
producers (the post-task evaluator, the daily sweep) or manual mutation routes
change the pending skill-candidate queue or saved skills out from under the
snapshot the session is reconciling. This module is that gate.

It is a deliberately tiny, single-process, in-memory flag. FastAPI runs on one
event loop and the post-task evaluators are scheduled with ``asyncio.create_task``
on that same loop (see ``finalization.execution_result_processing.maybe_run_post_task_evaluators``), so a
plain module-level variable is sufficient - there is no cross-process or thread
contention to guard against. Because it lives only in memory, an abnormal exit or
a backend restart can never leave a stuck lock: the gate simply starts inactive.

The lock's lifetime tracks the workspace window's presence. It is activated when
a session starts and released when the window closes (``POST .../session/discard``),
regardless of whether the user committed.
"""

from __future__ import annotations

import logging
from typing import Optional


logger = logging.getLogger(__name__)


# Shared user-facing message for the HTTP 409 responses raised by the memory
# routes while a reconciliation session owns the skill state. Kept here so the
# routes stay consistent and there is a single place to reword it.
RECONCILIATION_ACTIVE_MESSAGE = (
    "A skill reconciliation workspace is currently open. Close it (commit or "
    "discard your review) before changing skills or running skill intelligence."
)


_active_session_id: Optional[str] = None


def is_active() -> bool:
    """Return True when a reconciliation session currently owns the skill state."""
    return _active_session_id is not None


def active_session_id() -> Optional[str]:
    """Return the id of the active reconciliation session, or None."""
    return _active_session_id


def activate(session_id: str) -> None:
    """Mark a reconciliation session as active, freezing background skill capture.

    Raises ValueError if a different session is already active so callers never
    silently clobber an in-flight session.
    """
    global _active_session_id
    if _active_session_id is not None and _active_session_id != session_id:
        raise ValueError(
            f"Reconciliation session '{_active_session_id}' is already active."
        )
    _active_session_id = session_id
    logger.info("Reconciliation gate activated for session %s", session_id)


def deactivate() -> None:
    """Release the gate, unfreezing background skill capture. Idempotent."""
    global _active_session_id
    previous = _active_session_id
    _active_session_id = None
    if previous is not None:
        logger.info("Reconciliation gate deactivated (was session %s)", previous)
