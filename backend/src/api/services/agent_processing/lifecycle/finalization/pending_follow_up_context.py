"""Describe durable follow-up checks already arranged for the chain, for the outcome evaluator."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context

logger = logging.getLogger(__name__)

PENDING_FOLLOW_UP_STATUS = "scheduled"
MAX_LISTED_FOLLOW_UPS = 5
MAX_INSTRUCTIONS_CHARS = 400


def _default_repository() -> Any:
    from api.dependencies import get_sqlite_knowledge_service

    return get_sqlite_knowledge_service().agent_task_follow_up_repository


def render_pending_follow_up_context(rows: List[Dict[str, Any]]) -> Optional[str]:
    """Render still-scheduled follow-up rows as an evaluator block; ``None`` when none are pending."""
    pending = [row for row in rows if row.get("status") == PENDING_FOLLOW_UP_STATUS]
    if not pending:
        return None
    lines = []
    for row in pending[:MAX_LISTED_FOLLOW_UPS]:
        instructions = str(row.get("instructions") or "").strip()[:MAX_INSTRUCTIONS_CHARS]
        lines.append(f"- due {row.get('due_at')}: {instructions}")
    return (
        "FOLLOW-UP CHECKS ALREADY SCHEDULED FOR THIS TASK (durable; each will resume this task automatically at its due time):\n"
        + "\n".join(lines)
        + "\nWork that one of these checks will complete is in progress, not a residual gap; "
        "do not classify the outcome as partial solely because that work is still pending."
    )


async def pending_follow_up_context(
    agent_task_id: Optional[str],
    *,
    repository_provider: Optional[Callable[[], Any]] = None,
) -> Optional[str]:
    """Return the pending follow-up block for the running chain; never raises."""
    root_task_id = get_current_agent_context().get("root_task_id") or agent_task_id
    if not root_task_id:
        return None
    try:
        repository = (repository_provider or _default_repository)()
        rows = await repository.list_for_root(str(root_task_id))
    except Exception:
        logger.exception("Could not load pending follow-ups for %s", root_task_id)
        return None
    return render_pending_follow_up_context(rows)
