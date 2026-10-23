"""Publish Agent Task events and project progress into conversation state."""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class AgentTaskEventBroadcaster:
    """Own the shared WebSocket publication behavior for submitted Agent Tasks."""

    async def broadcast(self, message_data: Dict[str, Any]) -> None:
        """Publish one event to connected clients without failing submission work."""
        try:
            from api.services.websocket_connection_manager import active_connections

            event_type = message_data.get("event_type", message_data.get("type", "unknown"))
            await self._project_conversation_progress(event_type, message_data)
            logger.info(
                "Broadcasting %s to %s WebSocket connection(s)",
                event_type,
                len(active_connections),
            )
            successful_sends = 0
            for connection in active_connections:
                try:
                    await connection.send_json(message_data)
                    successful_sends += 1
                except Exception as exc:
                    logger.error(
                        "Failed to send WebSocket message: %s",
                        exc,
                        exc_info=True,
                    )
            logger.info(
                "Broadcasted %s to %s/%s clients",
                event_type,
                successful_sends,
                len(active_connections),
            )
        except Exception as exc:
            logger.error("Error broadcasting WebSocket message: %s", exc, exc_info=True)

    @staticmethod
    async def _project_conversation_progress(
        event_type: object,
        message_data: Dict[str, Any],
    ) -> None:
        if event_type != "agent_task_progress":
            return
        agent_task_id = message_data.get("agent_task_id")
        timeline_entry = message_data.get("timeline_entry")
        status_text = message_data.get("step")
        if not isinstance(status_text, str) or not status_text.strip():
            status_text = (
                timeline_entry.get("title")
                or timeline_entry.get("summary")
                or timeline_entry.get("content")
                if isinstance(timeline_entry, dict)
                else None
            )
        if not (
            isinstance(agent_task_id, str)
            and agent_task_id.strip()
            and isinstance(status_text, str)
        ):
            return
        try:
            from api.services.conversation.conversation_agent_turn_lifecycle import (
                project_conversation_agent_task_progress,
            )

            await project_conversation_agent_task_progress(agent_task_id, status_text)
        except Exception:
            logger.warning(
                "Conversation progress projection failed for Agent Task %s",
                agent_task_id,
                exc_info=True,
            )
