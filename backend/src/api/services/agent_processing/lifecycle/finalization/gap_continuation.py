"""Turn an outcome verdict that names one closable gap into an immediate automatic continuation turn."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from api.services.agent_follow_ups.follow_up_events import notify_follow_ups_changed
from api.services.agent_follow_ups.follow_up_scheduler import GAP_CONTINUATION_REASON

logger = logging.getLogger(__name__)

MAX_GAP_CONTINUATIONS_PER_CHAIN = 2
_ACTIVE_STATUSES = frozenset({"scheduled", "dispatching"})


def _default_repository() -> Any:
    from api.dependencies import get_sqlite_knowledge_service

    return get_sqlite_knowledge_service().agent_task_follow_up_repository


async def schedule_gap_continuation(
    *,
    root_task_id: Optional[str],
    source_agent_task_id: Optional[str],
    instructions: str,
    repository_provider: Optional[Callable[[], Any]] = None,
    now_fn: Optional[Callable[[], datetime]] = None,
) -> Optional[Dict[str, Any]]:
    """Create the due-now follow-up row for a closable gap and return it; ``None`` when nothing was scheduled.

    Nothing is scheduled when the chain already has an active follow-up, when the chain already used its automatic continuations, or when the repository refuses or fails.
    The scheduler dispatches the row on its next poll, on the chain's own model, and cancels it if the user continued the conversation first."""
    root_id = root_task_id or source_agent_task_id
    source_id = source_agent_task_id or root_task_id
    text = str(instructions or "").strip()
    if not root_id or not source_id or not text:
        return None
    from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.follow_up_repository import (
        FollowUpLimitExceeded,
    )

    try:
        repository = (repository_provider or _default_repository)()
        existing = await repository.list_for_root(str(root_id))
        if any(row.get("status") in _ACTIVE_STATUSES for row in existing):
            return None
        automatic = [row for row in existing if row.get("reason") == GAP_CONTINUATION_REASON]
        if len(automatic) >= MAX_GAP_CONTINUATIONS_PER_CHAIN:
            return None
        now = (now_fn or (lambda: datetime.now(timezone.utc)))()
        created = await repository.create_follow_up(
            root_task_id=str(root_id),
            source_agent_task_id=str(source_id),
            instructions=text,
            reason=GAP_CONTINUATION_REASON,
            due_at=now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        )
        await notify_follow_ups_changed([str(root_id)])
        return created
    except FollowUpLimitExceeded:
        return None
    except Exception:
        logger.exception("Could not schedule a gap continuation for %s", root_id)
        return None


def apply_continuation_note(refined: Dict[str, Any], follow_up: Dict[str, Any]) -> None:
    """Keep the verdict honestly partial and tell the user that Basil is continuing automatically."""
    payload = refined.get("result_payload")
    summary = str(refined.get("summary_text") or "")
    note = f"Basil is continuing automatically to close this gap: {follow_up.get('instructions')}"
    refined["summary_text"] = f"{summary}\n\n{note}" if summary else note
    if isinstance(payload, dict):
        payload["continuation_scheduled"] = True
        payload["continuation_follow_up_id"] = follow_up.get("id")


__all__ = ["MAX_GAP_CONTINUATIONS_PER_CHAIN", "apply_continuation_note", "schedule_gap_continuation"]
