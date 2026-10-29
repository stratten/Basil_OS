"""Turn an outcome verdict of "work is still pending" into a durable follow-up check and a waiting result."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from api.services.agent_follow_ups.follow_up_events import notify_follow_ups_changed

from .evaluation import compose_outcome_intro

logger = logging.getLogger(__name__)

AUTO_FOLLOW_UP_REASON = "Scheduled automatically: the outcome check found work still pending."
MAX_AUTO_FOLLOW_UPS_PER_ROOT = 3
_ACTIVE_STATUSES = frozenset({"scheduled", "dispatching"})


def _default_repository() -> Any:
    from api.dependencies import get_sqlite_knowledge_service

    return get_sqlite_knowledge_service().agent_task_follow_up_repository


async def schedule_follow_up_for_pending_work(
    *,
    root_task_id: Optional[str],
    source_agent_task_id: Optional[str],
    pending_work: Dict[str, Any],
    repository_provider: Optional[Callable[[], Any]] = None,
    now_fn: Optional[Callable[[], datetime]] = None,
) -> Optional[Dict[str, Any]]:
    """Create the follow-up row for pending work and return it; ``None`` when nothing was scheduled.

    Nothing is scheduled when the chain already has an active follow-up, when the automatic
    limit for the chain is reached, or when the repository refuses or fails."""
    root_id = root_task_id or source_agent_task_id
    source_id = source_agent_task_id or root_task_id
    instructions = str(pending_work.get("instructions") or "").strip()
    if not root_id or not source_id or not instructions:
        return None
    from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.follow_up_repository import (
        FollowUpLimitExceeded,
    )

    try:
        repository = (repository_provider or _default_repository)()
        existing = await repository.list_for_root(str(root_id))
        if any(row.get("status") in _ACTIVE_STATUSES for row in existing):
            return None
        automatic = [row for row in existing if row.get("reason") == AUTO_FOLLOW_UP_REASON]
        if len(automatic) >= MAX_AUTO_FOLLOW_UPS_PER_ROOT:
            return None
        now = (now_fn or (lambda: datetime.now(timezone.utc)))()
        due_at = (now + timedelta(minutes=int(pending_work["delay_minutes"]))).isoformat(timespec="seconds")
        created = await repository.create_follow_up(
            root_task_id=str(root_id),
            source_agent_task_id=str(source_id),
            instructions=instructions,
            reason=AUTO_FOLLOW_UP_REASON,
            due_at=due_at,
        )
        await notify_follow_ups_changed([str(root_id)])
        return created
    except FollowUpLimitExceeded:
        return None
    except Exception:
        logger.exception("Could not schedule a follow-up for pending work on %s", root_id)
        return None


def apply_waiting_state(refined: Dict[str, Any], follow_up: Dict[str, Any]) -> None:
    """Rewrite a partial verdict as a waiting result once a follow-up check covers the pending work."""
    payload = refined.get("result_payload")
    reason = str(refined.get("outcome_reason") or "")
    summary = str(refined.get("summary_text") or "")
    intro = compose_outcome_intro("partial", reason)
    if intro and summary.startswith(intro):
        summary = summary[len(intro):].lstrip()
    note = (
        f"Waiting on work that is still running. Basil will check again automatically at {follow_up.get('due_at')}: "
        f"{follow_up.get('instructions')}"
    )
    refined["success"] = True
    refined["outcome"] = "success"
    refined["summary_text"] = f"{summary}\n\n{note}" if summary else note
    refined.pop("outcome_reason", None)
    if isinstance(payload, dict):
        payload["outcome"] = "success"
        payload["outcome_reason"] = ""
        payload["pending_follow_up_due_at"] = follow_up.get("due_at")
