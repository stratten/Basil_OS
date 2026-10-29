"""The token window bridge: request, answer, cancel, and the guarantee that no token is carried back."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.core.security.backend_request_guard import CREDENTIAL_SCOPE_KEY
from api.routes import websocket as websocket_module
from api.services.mcp_connectors import connection_secret_bridge as bridge


class FakeHost:
    """Records what the backend sends to the app and answers the way the app would."""

    def __init__(self, monkeypatch, *, connections: int = 1, reply=None):
        self.sent: list = []
        self.connections = connections
        self.reply = reply
        monkeypatch.setattr(bridge, "send_json_to_host_connections", self.send)

    async def send(self, payload, **_kwargs):
        self.sent.append(payload)
        if payload["type"] == bridge.REQUEST_TYPE and self.reply is not None and self.connections:
            reply = {**self.reply, "request_id": payload["request_id"]}
            asyncio.get_running_loop().call_soon(bridge.handle_connection_secret_result, reply)
        return self.connections


@pytest.mark.asyncio
async def test_a_connected_answer_returns_the_connection_without_any_token(monkeypatch):
    host = FakeHost(monkeypatch, reply={
        "type": bridge.RESULT_TYPE, "status": "connected", "connection_id": "c-1", "tool_count": 7,
        "token": "sk-leak", "access_token": "sk-leak", "value": "sk-leak",
    })

    outcome = await bridge.request_token_entry(server_url="https://mcp.example.com/mcp", friendly_name="Example")

    assert outcome == {"status": "connected", "connection_id": "c-1", "tool_count": 7, "friendly_name": None, "description": None}
    assert "sk-leak" not in json.dumps(outcome)
    assert host.sent[0]["server_url"] == "https://mcp.example.com/mcp"
    assert host.sent[0]["friendly_name"] == "Example"
    assert host.sent[0]["existing_names"] == []
    assert host.sent[0]["already_connected_as"] is None
    assert bridge.pending_request_count() == 0


@pytest.mark.asyncio
async def test_a_canceled_answer_is_reported_as_canceled(monkeypatch):
    FakeHost(monkeypatch, reply={"status": "canceled"})
    outcome = await bridge.request_token_entry(server_url="https://a.example.com/", friendly_name="A")
    assert outcome == {"status": "canceled"}


@pytest.mark.asyncio
async def test_a_failed_answer_keeps_a_bounded_message(monkeypatch):
    FakeHost(monkeypatch, reply={"status": "failed", "message": "x" * 2000})
    outcome = await bridge.request_token_entry(server_url="https://a.example.com/", friendly_name="A")
    assert outcome["status"] == "failed"
    assert len(outcome["message"]) == bridge.MAX_MESSAGE_CHARACTERS


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["connected-ish", None, 7, "ok"])
async def test_an_unrecognized_status_counts_as_failed(monkeypatch, status):
    FakeHost(monkeypatch, reply={"status": status})
    outcome = await bridge.request_token_entry(server_url="https://a.example.com/", friendly_name="A")
    assert outcome["status"] == "failed"
    assert outcome["message"]


@pytest.mark.asyncio
async def test_connected_answer_with_malformed_fields_drops_them(monkeypatch):
    FakeHost(monkeypatch, reply={"status": "connected", "connection_id": 5, "tool_count": -3})
    outcome = await bridge.request_token_entry(server_url="https://a.example.com/", friendly_name="A")
    assert outcome == {"status": "connected", "connection_id": None, "tool_count": None, "friendly_name": None, "description": None}


@pytest.mark.asyncio
async def test_the_name_and_description_the_user_settled_on_come_back_bounded(monkeypatch):
    FakeHost(monkeypatch, reply={"status": "connected", "connection_id": "c", "tool_count": 1, "friendly_name": "  Hugging Face (work)  ", "description": "d" * 2000})
    outcome = await bridge.request_token_entry(server_url="https://a.example.com/", friendly_name="Hugging Face")
    assert outcome["friendly_name"] == "Hugging Face (work)"
    assert len(outcome["description"]) == bridge.MAX_DESCRIPTION_CHARACTERS


@pytest.mark.asyncio
async def test_the_thread_records_the_request_and_a_successful_connection_without_the_token(monkeypatch):
    from api.services.agent_processing.shared import agent_runtime_context

    FakeHost(monkeypatch, reply={
        "type": bridge.RESULT_TYPE, "status": "connected", "connection_id": "c-1", "tool_count": 12,
        "friendly_name": "Hugging Face", "token": "hf_should_never_land",
    })
    asked = []
    resolved = []

    async def fake_asked(*_args, **kwargs):
        asked.append(kwargs)

    async def fake_resolved(*_args, **kwargs):
        resolved.append(kwargs)

    import api.services.agent_processing.lifecycle.runtime.user_interaction_timeline as timeline

    monkeypatch.setattr(timeline, "record_user_interaction_asked", fake_asked)
    monkeypatch.setattr(timeline, "record_user_interaction_resolved", fake_resolved)

    manager = AsyncMock()
    token = agent_runtime_context.set_current_agent_context({
        "websocket_manager": manager,
        "agent_task_id": "task-hf",
    })
    try:
        outcome = await bridge.request_token_entry(
            server_url="https://huggingface.co/mcp",
            friendly_name="Hugging Face",
        )
    finally:
        agent_runtime_context.reset_current_agent_context(token)

    assert outcome["status"] == "connected"
    assert asked[0]["kind"] == "connection_token"
    assert "huggingface.co" in asked[0]["prompt"]
    assert "hf_should_never_land" not in asked[0]["prompt"]
    assert resolved[0]["status"] == "approved"
    assert "12 tools" in resolved[0]["response"]
    assert "hf_should_never_land" not in resolved[0]["response"]


def test_exchange_copy_never_includes_a_token():
    prompt = bridge._exchange_prompt({
        "friendly_name": "Hugging Face",
        "host": "huggingface.co",
        "server_url": "https://huggingface.co/mcp",
        "already_connected_as": "Hugging Face",
    })
    assert "huggingface.co" in prompt
    assert "second connection" in prompt
    status, response = bridge._exchange_resolution({
        "status": "connected", "friendly_name": "Hugging Face (work)", "tool_count": 4,
    })
    assert (status, response) == ("approved", "Hugging Face (work) is connected. The service accepted the token (4 tools).")
    assert bridge._exchange_resolution({"status": "canceled"}) == ("dismissed", None)
    assert bridge._exchange_resolution({"status": "failed", "message": "The service rejected the token."}) == (
        "resolved", "The service rejected the token.",
    )
    assert bridge._exchange_resolution({"status": "failed", "message": bridge.TIMED_OUT_MESSAGE}) == ("timed_out", None)


@pytest.mark.asyncio
async def test_the_request_is_also_shown_in_the_agent_overlay(monkeypatch):
    from api.services.agent_processing.shared import agent_runtime_context

    host = FakeHost(monkeypatch, reply={"status": "canceled"})
    manager = AsyncMock()
    token = agent_runtime_context.set_current_agent_context({
        "websocket_manager": manager,
        "agent_task_id": "task-hf",
    })
    try:
        await bridge.request_token_entry(
            server_url="https://huggingface.co/mcp",
            friendly_name="Hugging Face",
            description="Write access for Basil model inventory",
        )
    finally:
        agent_runtime_context.reset_current_agent_context(token)

    manager.broadcast.assert_awaited()
    events = [call.args[0] for call in manager.broadcast.await_args_list]
    overlay = next(event for event in events if event.get("event_type") == bridge.REQUEST_TYPE)
    assert overlay["agent_task_id"] == "task-hf"
    assert overlay["host"] == "huggingface.co"
    assert overlay["server_url"] == "https://huggingface.co/mcp"
    assert overlay["friendly_name"] == "Hugging Face"
    assert "token" not in overlay
    assert host.sent[0]["host"] == "huggingface.co"


@pytest.mark.asyncio
async def test_timeout_hides_the_agent_overlay(monkeypatch):
    from api.services.agent_processing.shared import agent_runtime_context

    FakeHost(monkeypatch)
    manager = AsyncMock()
    token = agent_runtime_context.set_current_agent_context({
        "websocket_manager": manager,
        "agent_task_id": "task-hf",
    })
    try:
        await bridge.request_token_entry(server_url="https://huggingface.co/mcp", friendly_name="Hugging Face", timeout=0.05)
    finally:
        agent_runtime_context.reset_current_agent_context(token)

    event_types = [call.args[0]["event_type"] for call in manager.broadcast.await_args_list]
    assert bridge.REQUEST_TYPE in event_types
    assert bridge.CANCEL_TYPE in event_types


@pytest.mark.asyncio
async def test_the_request_carries_suggestions_and_existing_names(monkeypatch):
    host = FakeHost(monkeypatch, reply={"status": "canceled"})
    await bridge.request_token_entry(
        server_url="https://a.example.com/", friendly_name="A (work)", description="Work account",
        existing_names=["A", "B"], already_connected_as="A",
    )
    sent = host.sent[0]
    assert (sent["friendly_name"], sent["description"], sent["existing_names"], sent["already_connected_as"]) == ("A (work)", "Work account", ["A", "B"], "A")


@pytest.mark.asyncio
async def test_no_app_connection_fails_immediately_and_leaves_no_waiter(monkeypatch):
    FakeHost(monkeypatch, connections=0)
    outcome = await bridge.request_token_entry(server_url="https://a.example.com/", friendly_name="A")
    assert outcome == {"status": "failed", "message": bridge.NOT_CONNECTED_MESSAGE}
    assert bridge.pending_request_count() == 0


@pytest.mark.asyncio
async def test_an_unanswered_window_times_out_and_the_app_is_told_to_close_it(monkeypatch):
    host = FakeHost(monkeypatch)
    outcome = await bridge.request_token_entry(server_url="https://a.example.com/", friendly_name="A", timeout=0.05)
    assert outcome == {"status": "failed", "message": bridge.TIMED_OUT_MESSAGE}
    assert [payload["type"] for payload in host.sent] == [bridge.REQUEST_TYPE, bridge.CANCEL_TYPE]
    assert host.sent[1]["request_id"] == host.sent[0]["request_id"]
    assert bridge.pending_request_count() == 0


@pytest.mark.asyncio
async def test_an_answer_for_an_unknown_or_finished_request_is_ignored():
    assert bridge.handle_connection_secret_result({"request_id": "nope", "status": "connected"}) is False
    assert bridge.handle_connection_secret_result({"status": "connected"}) is False
    assert bridge.handle_connection_secret_result({"request_id": 4, "status": "connected"}) is False


@pytest.mark.asyncio
async def test_a_duplicate_answer_does_not_replace_the_first(monkeypatch):
    waiter = asyncio.get_running_loop().create_future()
    monkeypatch.setitem(bridge._waiters, "r-1", waiter)
    assert bridge.handle_connection_secret_result({"request_id": "r-1", "status": "canceled"}) is True
    assert bridge.handle_connection_secret_result({"request_id": "r-1", "status": "connected"}) is False
    assert waiter.result()["status"] == "canceled"


def make_websocket(credential_type: str, message: dict) -> AsyncMock:
    websocket = AsyncMock()
    websocket.scope = {CREDENTIAL_SCOPE_KEY: credential_type}
    websocket.receive.side_effect = [
        {"type": "websocket.receive", "text": json.dumps(message)},
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
@pytest.mark.parametrize("credential_type, resolved", [("host", True), ("webview", False)])
async def test_only_the_app_connection_can_answer_a_token_window(monkeypatch, credential_type, resolved):
    waiter = asyncio.get_running_loop().create_future()
    monkeypatch.setitem(bridge._waiters, "r-9", waiter)

    await run_endpoint(make_websocket(credential_type, {"type": bridge.RESULT_TYPE, "request_id": "r-9", "status": "connected", "connection_id": "c"}))

    assert waiter.done() is resolved
