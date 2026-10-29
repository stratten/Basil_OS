"""The /ws route starts the provider-key sync on connect and accepts key replies only from the app."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.core.security.backend_request_guard import CREDENTIAL_SCOPE_KEY
from api.routes import websocket as websocket_module
from api.services import provider_keys_bridge as bridge


@pytest.fixture(autouse=True)
def keyring_hosted_environment(monkeypatch):
    monkeypatch.delenv("BASIL_CREDENTIAL_HOST", raising=False)


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


@pytest.mark.asyncio
async def test_a_reply_from_the_app_resolves_the_waiting_request(monkeypatch):
    waiters: dict = {}
    monkeypatch.setattr(bridge, "_waiters", waiters)
    future = asyncio.get_running_loop().create_future()
    waiters["corr-1"] = future

    await run_endpoint(make_websocket("host", {"type": "provider_key_result", "correlation_id": "corr-1", "ok": True}))

    assert future.done() and future.result()["ok"] is True


@pytest.mark.asyncio
async def test_a_reply_from_a_webview_connection_is_ignored(monkeypatch):
    waiters: dict = {}
    monkeypatch.setattr(bridge, "_waiters", waiters)
    future = asyncio.get_running_loop().create_future()
    waiters["corr-2"] = future

    await run_endpoint(make_websocket("webview", {
        "type": "provider_keys_snapshot", "correlation_id": "corr-2", "status": "ok", "keys": {"openai": "forged"},
    }))

    assert not future.done()


@pytest.mark.asyncio
async def test_connecting_starts_the_provider_key_sync_for_that_connection(monkeypatch):
    starter = MagicMock()
    monkeypatch.setattr(websocket_module, "start_provider_key_sync", starter)
    websocket = make_websocket("host")

    await run_endpoint(websocket)

    starter.assert_called_once_with(websocket)


def test_key_values_are_redacted_from_websocket_log_summaries():
    summary = websocket_module._summarize_websocket_payload_for_log(
        {"type": "provider_key_store", "correlation_id": "c", "name": "openai", "value": "sk-never-logged"}
    )

    assert "sk-never-logged" not in summary
    assert "redacted_keys=['value']" in summary
