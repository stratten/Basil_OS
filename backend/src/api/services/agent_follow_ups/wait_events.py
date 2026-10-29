"""Tell connected UIs that a running Agent Task is waiting before it checks again, and when that wait ends."""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

WAIT_STARTED_EVENT = "agent_wait_started"
WAIT_FINISHED_EVENT = "agent_wait_finished"


async def notify_wait_started(agent_task_id: Optional[str], *, resume_at_epoch_ms: int, reason: str = "") -> None:
    """Broadcast ``agent_wait_started`` with the absolute resume time so every client counts down to the same instant.

    The event carries ``wait_task_id`` instead of ``agent_task_id`` so the Agent Task store ignores it; the wait notice store listens for it directly. Never raises.
    """
    await _broadcast({"event_type": WAIT_STARTED_EVENT, "wait_task_id": agent_task_id, "resume_at_epoch_ms": int(resume_at_epoch_ms), "reason": reason or ""}, agent_task_id)


async def notify_wait_finished(agent_task_id: Optional[str]) -> None:
    """Broadcast ``agent_wait_finished`` so clients drop the countdown, whether the wait elapsed or was interrupted. Never raises."""
    await _broadcast({"event_type": WAIT_FINISHED_EVENT, "wait_task_id": agent_task_id}, agent_task_id)


async def _broadcast(payload: dict, agent_task_id: Optional[str]) -> None:
    if not agent_task_id:
        return
    try:
        from api.services.websocket_connection_manager import broadcast_json_text

        await broadcast_json_text(payload, log=logger)
    except Exception:
        logger.debug("Could not broadcast wait event", exc_info=True)
