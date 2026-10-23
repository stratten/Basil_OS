import pytest

from api.routes.websocket_routes.agent_task_streaming import (
    _broadcast_agent_task_capture_complete,
)
from api.services.websocket_connection_manager import active_connections


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


@pytest.mark.asyncio
async def test_agent_task_capture_complete_broadcasts_to_all_connections():
    active_connections.clear()
    first = FakeWebSocket()
    second = FakeWebSocket()
    active_connections.update({first, second})

    payload = {
        "event_type": "agent_task_capture_complete",
        "data": {
            "reason": "word_silence_detected",
        },
    }

    try:
        await _broadcast_agent_task_capture_complete(payload)
    finally:
        active_connections.clear()

    assert first.messages == [payload]
    assert second.messages == [payload]
