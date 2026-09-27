from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.agent_processing.lifecycle.runtime import (
    conversation_progress_projection,
)


@pytest.mark.asyncio
async def test_workflow_agent_progress_is_projected_before_websocket_broadcast(
    monkeypatch,
) -> None:
    projected = AsyncMock()
    websocket_manager = SimpleNamespace(broadcast=AsyncMock())
    monkeypatch.setattr(
        conversation_progress_projection,
        "_project_conversation_agent_task_progress",
        projected,
    )

    payload = {
        "event_type": "agent_progress_update",
        "agent_task_id": "task-1",
        "message": "Searching available information",
    }

    await conversation_progress_projection.broadcast_workflow_notification(
        websocket_manager,
        payload,
    )

    projected.assert_awaited_once_with(
        "task-1",
        "Searching available information",
    )
    websocket_manager.broadcast.assert_awaited_once_with(payload)
