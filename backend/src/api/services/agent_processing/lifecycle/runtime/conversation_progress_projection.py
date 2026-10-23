"""Project readable workflow progress into Conversation-linked Agent Tasks."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

_PROGRESS_TEXT_FIELDS = {
    "agent_task_progress": "step",
    "agent_progress_update": "message",
    "dynamic_step_added": "description",
    "dynamic_step_updated": "completion_message",
}


def _persisted_artifact_id(notification_data: Mapping[str, Any]) -> str | None:
    artifact = notification_data.get("agent_task_artifact")
    timeline_entry = notification_data.get("timeline_entry")
    if not isinstance(artifact, Mapping) or not isinstance(timeline_entry, Mapping):
        return None
    timeline_metadata = timeline_entry.get("metadata")
    timeline_artifact = (
        timeline_metadata.get("artifact")
        if isinstance(timeline_metadata, Mapping)
        else None
    )
    artifact_id = artifact.get("artifact_id")
    if (
        not isinstance(artifact_id, str)
        or not artifact_id.strip()
        or not isinstance(timeline_artifact, Mapping)
        or timeline_artifact.get("artifact_id") != artifact_id
        or timeline_entry.get("id") != f"artifact_{artifact_id}"
    ):
        return None
    return artifact_id


async def broadcast_workflow_notification(
    websocket_manager: Any,
    notification_data: dict[str, Any],
) -> None:
    """Project eligible progress before publishing the original WebSocket payload."""
    await project_workflow_notification_to_conversation(notification_data)
    await websocket_manager.broadcast(notification_data)


async def project_workflow_notification_to_conversation(
    notification_data: dict[str, Any],
) -> None:
    """Project selected progress or durable direct-write evidence without widening status."""
    event_type = notification_data.get("event_type")
    agent_task_id = notification_data.get("agent_task_id")
    if not isinstance(agent_task_id, str) or not agent_task_id.strip():
        return

    if event_type == "agent_task_artifact":
        artifact_id = _persisted_artifact_id(notification_data)
        if artifact_id is None:
            return
        try:
            await _project_conversation_agent_task_artifact(agent_task_id, artifact_id)
        except Exception:
            logger.warning(
                "Conversation artifact projection failed for Agent Task %s",
                agent_task_id,
                exc_info=True,
            )
        return

    text_field = _PROGRESS_TEXT_FIELDS.get(event_type)
    if not text_field:
        return
    status_text = notification_data.get(text_field)
    if event_type == "dynamic_step_updated" and (
        not isinstance(status_text, str) or not status_text.strip()
    ):
        status_text = notification_data.get("description")

    if not isinstance(status_text, str) or not status_text.strip():
        return

    try:
        await _project_conversation_agent_task_progress(agent_task_id, status_text)
    except Exception:
        logger.warning(
            "Conversation progress projection failed for Agent Task %s",
            agent_task_id,
            exc_info=True,
        )


async def _project_conversation_agent_task_progress(
    agent_task_id: str,
    status_text: str,
) -> None:
    """Resolve the Conversation dependency after runtime initialization."""
    from api.services.conversation.conversation_agent_turn_lifecycle import (
        project_conversation_agent_task_progress,
    )

    await project_conversation_agent_task_progress(agent_task_id, status_text)


async def _project_conversation_agent_task_artifact(
    agent_task_id: str,
    artifact_id: str,
) -> None:
    """Resolve the durable Conversation artifact projection after runtime initialization."""
    from api.services.conversation.conversation_agent_turn_lifecycle import (
        project_conversation_agent_task_artifact,
    )

    await project_conversation_agent_task_artifact(agent_task_id, artifact_id)
