"""Backend liveness heartbeats reach only the connections that subscribed to them."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.routes.websocket import websocket_endpoint
from api.services import websocket_connection_manager as manager


@pytest.fixture(autouse=True)
def clean_registry():
    manager.active_connections.clear()
    manager.heartbeat_subscribers.clear()
    yield
    manager.active_connections.clear()
    manager.heartbeat_subscribers.clear()


@pytest.mark.asyncio
async def test_subscribe_message_registers_the_connection_and_disconnect_removes_it():
    websocket = AsyncMock()
    seen_while_connected = {}

    async def receive():
        if not seen_while_connected:
            seen_while_connected["subscribed"] = None
            return {"type": "websocket.receive", "text": json.dumps({"type": "subscribe_backend_heartbeat"})}
        seen_while_connected["subscribed"] = websocket in manager.heartbeat_subscribers
        return {"type": "websocket.disconnect"}

    websocket.receive.side_effect = receive

    await websocket_endpoint(
        websocket=websocket,
        agent_task_submission_service=MagicMock(),
        wake_word_service=MagicMock(),
        transcription_service=MagicMock(),
        conversation_turn_router=MagicMock(),
        todo_workspace_turn_manager=MagicMock(),
    )

    assert seen_while_connected["subscribed"] is True
    assert websocket not in manager.heartbeat_subscribers
    assert websocket not in manager.active_connections


@pytest.mark.asyncio
async def test_heartbeat_goes_only_to_subscribers():
    subscriber = AsyncMock()
    bystander = AsyncMock()
    manager.add_connection(subscriber)
    manager.add_connection(bystander)
    manager.subscribe_heartbeat(subscriber)

    sent = await manager.broadcast_heartbeat({"event_type": "backend_heartbeat", "sent_at": 1.0, "loop_lag_ms": 0})

    assert sent == 1
    subscriber.send_text.assert_awaited_once()
    assert json.loads(subscriber.send_text.await_args.args[0])["event_type"] == "backend_heartbeat"
    bystander.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_dead_subscriber_is_dropped_without_failing_the_broadcast():
    dead = AsyncMock()
    dead.send_text.side_effect = RuntimeError("closed")
    alive = AsyncMock()
    for websocket in (dead, alive):
        manager.add_connection(websocket)
        manager.subscribe_heartbeat(websocket)

    sent = await manager.broadcast_heartbeat({"event_type": "backend_heartbeat"})

    assert sent == 1
    assert dead not in manager.heartbeat_subscribers
    assert alive in manager.heartbeat_subscribers


def test_subscribing_an_unregistered_socket_is_ignored():
    manager.subscribe_heartbeat(AsyncMock())

    assert manager.heartbeat_subscribers == set()
