import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocket
import json
import websockets
from unittest.mock import AsyncMock, MagicMock

from api.routes.websocket import websocket_endpoint
from api.services.websocket_events import active_connections, send_transcription_status
from api.main import app

@pytest.mark.asyncio
async def test_websocket_connection():
    """Test the WebSocket ping/pong contract without resolving live dependencies."""
    websocket = AsyncMock()
    websocket.receive.side_effect = [
        {"type": "websocket.receive", "text": "ping"},
        {"type": "websocket.disconnect"},
    ]

    await websocket_endpoint(
        websocket=websocket,
        query_intent_handler=MagicMock(),
        model_service=MagicMock(),
        model_usage_service=MagicMock(),
        agent_task_submission_service=MagicMock(),
        wake_word_service=MagicMock(),
        transcription_service=MagicMock(),
        conversation_turn_router=MagicMock(),
    )

    websocket.accept.assert_awaited_once()
    websocket.send_text.assert_awaited_once_with("pong")

@pytest.mark.asyncio
async def test_transcription_status_updates(api_base_url, ws_base_url, live_base_url):
    """Test status updates over WS.

    Live mode: trigger via binary payload (no internal function access).
    In-process: use internal send_transcription_status for precision.
    """
    if live_base_url:
        async with websockets.connect(f"{ws_base_url}/ws") as websocket:
            sample_rate = 16000
            audio_data = bytes([0] * (sample_rate * 2))
            await websocket.send(audio_data)
            msg1 = await websocket.recv()
            assert json.loads(msg1)["event"] == "transcription_started"
            msg2 = await websocket.recv()
            data = json.loads(msg2)
            assert data["event"] == "transcription_completed"
            assert "data" in data
    else:
        connection = AsyncMock()
        active_connections.add(connection)
        try:
            await send_transcription_status("started")
            await send_transcription_status("completed", "Test transcription")
        finally:
            active_connections.remove(connection)

        assert connection.send_json.await_args_list[0].args[0] == {
            "event": "started",
            "data": None,
        }
        assert connection.send_json.await_args_list[1].args[0] == {
            "event": "completed",
            "data": "Test transcription",
        }

@pytest.mark.asyncio
async def test_multiple_clients(api_base_url, ws_base_url, live_base_url):
    """Test that multiple clients receive status updates."""
    if live_base_url:
        async with websockets.connect(f"{ws_base_url}/ws") as ws1:
            async with websockets.connect(f"{ws_base_url}/ws") as ws2:
                sample_rate = 16000
                audio_data = bytes([0] * (sample_rate * 2))
                await ws1.send(audio_data)
                d1 = json.loads(await ws1.recv())
                d2 = json.loads(await ws2.recv())
                assert d1["event"] == "transcription_started"
                assert d2["event"] == "transcription_started"
    else:
        connection_one = AsyncMock()
        connection_two = AsyncMock()
        active_connections.update({connection_one, connection_two})
        try:
            await send_transcription_status("started")
        finally:
            active_connections.difference_update({connection_one, connection_two})

        expected_message = {"event": "started", "data": None}
        assert connection_one.send_json.await_args.args[0] == expected_message
        assert connection_two.send_json.await_args.args[0] == expected_message

@pytest.mark.manual
@pytest.mark.asyncio
async def test_binary_audio_data(api_base_url, ws_base_url, live_base_url):
    """Test handling binary audio data over WebSocket."""
    sample_rate = 16000
    audio_data = bytes([0] * (sample_rate * 2))
    if live_base_url:
        async with websockets.connect(f"{ws_base_url}/ws") as websocket:
            await websocket.send(audio_data)
            d1 = json.loads(await websocket.recv())
            assert d1["event"] == "transcription_started"
            d2 = json.loads(await websocket.recv())
            assert d2["event"] == "transcription_completed"
            assert "data" in d2
    else:
        client = TestClient(app)
        with client.websocket_connect("/ws") as websocket:
            websocket.send_bytes(audio_data)
            data = websocket.receive_json()
            assert data["event"] == "transcription_started"
            data = websocket.receive_json()
            assert data["event"] == "transcription_completed"
            assert "data" in data

@pytest.mark.manual
@pytest.mark.asyncio
async def test_connection_state_changes(api_base_url, ws_base_url, live_base_url):
    """Test WebSocket connection state handling."""
    if live_base_url:
        async with websockets.connect(f"{ws_base_url}/ws") as websocket:
            await websocket.send("ping")
            assert (await websocket.recv()) == "pong"
        async with websockets.connect(f"{ws_base_url}/ws") as websocket:
            await websocket.send("ping")
            assert (await websocket.recv()) == "pong"
            sample_rate = 16000
            sample_audio = bytes([0] * (sample_rate * 2))
            await websocket.send(sample_audio)
            d1 = json.loads(await websocket.recv())
            assert d1["event"] == "transcription_started"
            d2 = json.loads(await websocket.recv())
            assert d2["event"] == "transcription_completed"
            assert "data" in d2
    else:
        client = TestClient(app)
        with client.websocket_connect("/ws") as websocket:
            websocket.send_text("ping")
            assert websocket.receive_text() == "pong"
        with client.websocket_connect("/ws") as websocket:
            websocket.send_text("ping")
            assert websocket.receive_text() == "pong"
            sample_rate = 16000
            sample_audio = bytes([0] * (sample_rate * 2))
            websocket.send_bytes(sample_audio)
            data = websocket.receive_json()
            assert data["event"] == "transcription_started"
            data = websocket.receive_json()
            assert data["event"] == "transcription_completed"
            assert "data" in data