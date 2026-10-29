"""Connector token replies on /ws are accepted only from the native app's host connection."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.core.security.backend_request_guard import CREDENTIAL_SCOPE_KEY
from api.routes import websocket as websocket_module
from api.services.mcp_connectors import swift_token_bridge


def make_websocket(credential_type: str, *messages: dict) -> AsyncMock:
    websocket = AsyncMock()
    websocket.scope = {CREDENTIAL_SCOPE_KEY: credential_type}
    websocket.receive.side_effect = [
        *({"type": "websocket.receive", "text": json.dumps(message)} for message in messages),
        {"type": "websocket.disconnect"},
    ]
    return websocket


async def run_endpoint(websocket: AsyncMock) -> None:
    await websocket_module.websocket_endpoint(
        websocket=websocket,
        agent_task_submission_service=MagicMock(),
        wake_word_service=MagicMock(),
        transcription_service=MagicMock(),
        conversation_turn_router=MagicMock(),
    )


def make_waiter(monkeypatch):
    waiters: dict = {}
    monkeypatch.setattr(swift_token_bridge, "_token_response_waiters", waiters)
    future = asyncio.get_running_loop().create_future()
    waiters["corr-1"] = future
    return future


@pytest.mark.asyncio
async def test_a_token_reply_from_the_app_resolves_the_waiting_request(monkeypatch):
    waiter = make_waiter(monkeypatch)
    await run_endpoint(make_websocket("host", {"type": "mcp_token_response", "correlation_id": "corr-1", "access_token": "real", "refresh_token": "r"}))

    assert waiter.done()
    assert waiter.result() == {"access_token": "real", "refresh_token": "r"}


@pytest.mark.asyncio
async def test_a_token_reply_from_a_webview_connection_is_ignored(monkeypatch):
    waiter = make_waiter(monkeypatch)
    await run_endpoint(make_websocket("webview", {"type": "mcp_token_response", "correlation_id": "corr-1", "access_token": "forged"}))

    assert not waiter.done()


@pytest.mark.asyncio
async def test_a_connection_with_no_credential_type_is_ignored(monkeypatch):
    waiter = make_waiter(monkeypatch)
    websocket = make_websocket("host", {"type": "mcp_token_response", "correlation_id": "corr-1", "access_token": "forged"})
    websocket.scope = {}

    await run_endpoint(websocket)

    assert not waiter.done()


@pytest.mark.asyncio
@pytest.mark.parametrize("credential_type, expected_calls", [("host", 1), ("webview", 0)])
async def test_the_keychain_prompt_notice_is_accepted_only_from_the_app(monkeypatch, credential_type, expected_calls):
    notice = AsyncMock(return_value=True)
    monkeypatch.setattr(swift_token_bridge, "broadcast_token_user_action_waiting", notice)

    await run_endpoint(make_websocket(credential_type, {"type": "mcp_token_user_action_waiting", "correlation_id": "corr-9", "connection_id": "c"}))

    assert notice.await_count == expected_calls
