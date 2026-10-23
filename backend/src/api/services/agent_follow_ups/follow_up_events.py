"""Tell connected UIs that the scheduled follow-ups for an Agent Task chain changed."""

from __future__ import annotations

import logging
from typing import Iterable

logger = logging.getLogger(__name__)

FOLLOW_UPS_CHANGED_EVENT = "agent_task_follow_up_changed"


async def notify_follow_ups_changed(root_task_ids: Iterable[str]) -> None:
    """Broadcast one ``agent_task_follow_up_changed`` event per distinct root task id.

    The event deliberately carries no ``agent_task_id`` so the Agent Task store ignores it; the UI refetches the durable pending-follow-up list instead of trusting the event payload. Never raises.
    """
    try:
        from api.services.websocket_connection_manager import broadcast_json_text

        for root_task_id in sorted({str(item).strip() for item in root_task_ids if str(item or "").strip()}):
            await broadcast_json_text(
                {"event_type": FOLLOW_UPS_CHANGED_EVENT, "root_task_id": root_task_id},
                log=logger,
            )
    except Exception:
        logger.warning("Could not broadcast follow-up change", exc_info=True)
