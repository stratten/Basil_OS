"""Tests for the provider-key bridge between the backend and the native app's Keychain vault."""

import asyncio
import json
import logging
from contextlib import suppress
from unittest.mock import AsyncMock

import pytest

from api.core.security.backend_request_guard import CREDENTIAL_SCOPE_KEY
from api.services import host_connection_channel, provider_keys_bridge as bridge
from api.services import provider_keys_migration
from api.services.mcp_connectors import swift_token_bridge
from api.services.websocket_connection_manager import active_connections
from config.client_hosted_credential_store import (
    NOT_CONNECTED_MESSAGE,
    VAULT_UNREADABLE_MESSAGE,
    ClientHostedCredentialStore,
)
from config.credential_store import CredentialStoreUnavailableError


class FakeSocket:
    def __init__(self, credential_type: str = "host", fail: bool = False) -> None:
        self.scope = {CREDENTIAL_SCOPE_KEY: credential_type}
        self.sent: list[dict] = []
        self.fail = fail

    async def send_text(self, text: str) -> None:
        if self.fail:
            raise RuntimeError("socket closed")
        self.sent.append(json.loads(text))


async def wait_for_sent(socket: FakeSocket, count: int = 1) -> None:
    for _ in range(400):
        if len(socket.sent) >= count:
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"expected {count} message(s), saw {len(socket.sent)}")


@pytest.fixture(autouse=True)
def clean_bridge_state(monkeypatch):
    active_connections.clear()
    monkeypatch.setattr(bridge, "_sync_task", None)
    monkeypatch.setattr(bridge, "_waiters", {})
    monkeypatch.setattr(bridge, "is_client_hosted", lambda: True)
    yield
    active_connections.clear()


@pytest.fixture
def migration(monkeypatch):
    mock = AsyncMock(return_value=0)
    monkeypatch.setattr(provider_keys_migration, "migrate_legacy_provider_keys", mock)
    return mock


def snapshot(correlation_id: str, keys: dict | None = None, status: str = "ok") -> dict:
    return {"type": "provider_keys_snapshot", "correlation_id": correlation_id, "status": status, "keys": keys or {}}


def result(correlation_id: str, ok: bool = True, error: str | None = None) -> dict:
    message = {"type": "provider_key_result", "correlation_id": correlation_id, "ok": ok}
    if error:
        message["error"] = error
    return message


def test_the_scope_key_matches_the_request_guard():
    assert host_connection_channel.CREDENTIAL_SCOPE_KEY == CREDENTIAL_SCOPE_KEY


def test_only_connections_authenticated_with_the_host_credential_are_host_connections():
    assert host_connection_channel.is_host_connection(FakeSocket("host")) is True
    assert host_connection_channel.is_host_connection(FakeSocket("webview")) is False
    assert host_connection_channel.is_host_connection(AsyncMock()) is False
    assert host_connection_channel.is_host_connection(object()) is False


@pytest.mark.asyncio
async def test_secret_bearing_messages_reach_only_host_connections_and_failures_never_log_the_payload(caplog):
    host, webview, dead = FakeSocket("host"), FakeSocket("webview"), FakeSocket("host", fail=True)
    active_connections.update({host, webview, dead})

    with caplog.at_level(logging.DEBUG):
        sent = await host_connection_channel.send_json_to_host_connections({"type": "provider_key_store", "value": "sk-never-logged"})

    assert sent == 1
    assert host.sent[0]["value"] == "sk-never-logged"
    assert webview.sent == []
    assert dead not in active_connections
    assert "sk-never-logged" not in caplog.text


@pytest.mark.asyncio
async def test_connector_tokens_are_pushed_only_to_the_app():
    host, webview = FakeSocket("host"), FakeSocket("webview")
    active_connections.update({host, webview})

    await swift_token_bridge._push_token_to_swift(
        connection_id="gmail-1", access_token="access", refresh_token="refresh", expires_in=3600
    )

    assert [message["type"] for message in host.sent] == ["mcp_token_store"]
    assert webview.sent == []


@pytest.mark.asyncio
async def test_a_host_connection_starts_the_sync_and_the_snapshot_fills_the_store(migration):
    host = FakeSocket()
    active_connections.add(host)
    store = ClientHostedCredentialStore()

    task = bridge.start_provider_key_sync(host, store)
    assert task is not None
    await wait_for_sent(host)
    request = host.sent[0]
    assert request["type"] == "provider_keys_request"
    assert bridge.start_provider_key_sync(host, store) is task
    assert bridge.handle_provider_key_message(snapshot(request["correlation_id"], {"openai": "sk-a", "custom_x": "k"})) is True
    await task

    assert store.is_ready() is True
    assert store.unavailable_reason() is None
    assert store.names() == ["custom_x", "openai"]
    assert store.read("openai") == "sk-a"
    migration.assert_awaited_once()


@pytest.mark.asyncio
async def test_an_unreadable_vault_marks_the_store_unavailable_and_skips_the_migration(migration):
    host = FakeSocket()
    active_connections.add(host)
    store = ClientHostedCredentialStore()

    task = bridge.start_provider_key_sync(host, store)
    await wait_for_sent(host)
    bridge.handle_provider_key_message(snapshot(host.sent[0]["correlation_id"], status="unavailable"))
    await task

    assert store.is_ready() is True
    assert store.unavailable_reason() == VAULT_UNREADABLE_MESSAGE
    assert store.read("openai") is None
    migration.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failed_migration_still_readies_the_store_with_the_vault_keys(migration):
    migration.side_effect = RuntimeError("keyring exploded")
    host = FakeSocket()
    active_connections.add(host)
    store = ClientHostedCredentialStore()

    task = bridge.start_provider_key_sync(host, store)
    await wait_for_sent(host)
    bridge.handle_provider_key_message(snapshot(host.sent[0]["correlation_id"], {"openai": "sk-a"}))
    await task

    assert store.is_ready() is True
    assert store.read("openai") == "sk-a"


@pytest.mark.asyncio
async def test_a_connection_that_is_not_the_app_gets_nothing_and_starts_nothing():
    webview = FakeSocket("webview")
    active_connections.add(webview)
    store = ClientHostedCredentialStore()

    assert bridge.start_provider_key_sync(webview, store) is None

    assert webview.sent == []
    assert store.is_ready() is False


@pytest.mark.asyncio
async def test_nothing_starts_unless_the_app_hosts_the_credentials(monkeypatch):
    monkeypatch.setattr(bridge, "is_client_hosted", lambda: False)
    host = FakeSocket()
    active_connections.add(host)

    assert bridge.start_provider_key_sync(host, ClientHostedCredentialStore()) is None
    assert host.sent == []


@pytest.mark.asyncio
async def test_nothing_restarts_once_the_keys_have_arrived():
    host = FakeSocket()
    active_connections.add(host)
    store = ClientHostedCredentialStore()
    store.mark_ready()

    assert bridge.start_provider_key_sync(host, store) is None


@pytest.mark.asyncio
async def test_a_later_connection_retries_after_an_unavailable_vault(migration):
    host = FakeSocket()
    active_connections.add(host)
    store = ClientHostedCredentialStore()
    store.mark_unavailable(VAULT_UNREADABLE_MESSAGE)

    task = bridge.start_provider_key_sync(host, store)

    assert task is not None
    await wait_for_sent(host)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_an_unanswered_request_is_repeated_with_the_same_correlation_id_and_then_gives_up(monkeypatch):
    monkeypatch.setattr(bridge, "SNAPSHOT_ATTEMPT_SECONDS", 0.01)
    monkeypatch.setattr(bridge, "SNAPSHOT_MAX_ATTEMPTS", 2)
    host = FakeSocket()
    active_connections.add(host)
    store = ClientHostedCredentialStore()

    await bridge._run_sync(store)

    assert len(host.sent) == 2
    assert host.sent[0]["correlation_id"] == host.sent[1]["correlation_id"]
    assert store.is_ready() is True
    assert store.unavailable_reason() == bridge.UNACKNOWLEDGED_MESSAGE


@pytest.mark.asyncio
async def test_the_sync_ends_without_readying_the_store_when_no_app_is_connected():
    store = ClientHostedCredentialStore()

    await bridge._run_sync(store)

    assert store.is_ready() is False


@pytest.mark.asyncio
async def test_saving_a_key_waits_for_the_apps_acknowledgment():
    host = FakeSocket()
    active_connections.add(host)
    store = ClientHostedCredentialStore()
    store.attach_transport(bridge._transport)
    store.load_snapshot({})
    store.mark_ready()

    save = asyncio.create_task(store.asave("openai", "sk-new"))
    await wait_for_sent(host)
    message = host.sent[0]
    assert (message["type"], message["name"], message["value"]) == ("provider_key_store", "openai", "sk-new")
    assert store.read("openai") is None
    bridge.handle_provider_key_message(result(message["correlation_id"]))
    await save

    assert store.read("openai") == "sk-new"


@pytest.mark.asyncio
async def test_a_refused_save_raises_the_curated_reason_and_keeps_nothing():
    host = FakeSocket()
    active_connections.add(host)
    store = ClientHostedCredentialStore()
    store.attach_transport(bridge._transport)
    store.mark_ready()

    save = asyncio.create_task(store.asave("openai", "sk-new"))
    await wait_for_sent(host)
    bridge.handle_provider_key_message(result(host.sent[0]["correlation_id"], ok=False, error="vault_unreadable"))

    with pytest.raises(CredentialStoreUnavailableError) as raised:
        await save
    assert str(raised.value) == VAULT_UNREADABLE_MESSAGE
    assert store.read("openai") is None


@pytest.mark.asyncio
async def test_deleting_a_key_asks_the_app_and_forgets_it_after_the_acknowledgment():
    host = FakeSocket()
    active_connections.add(host)
    store = ClientHostedCredentialStore()
    store.attach_transport(bridge._transport)
    store.load_snapshot({"openai": "sk-a"})
    store.mark_ready()

    delete = asyncio.create_task(store.adelete("openai"))
    await wait_for_sent(host)
    message = host.sent[0]
    assert (message["type"], message["name"]) == ("provider_key_delete", "openai")
    bridge.handle_provider_key_message(result(message["correlation_id"]))
    await delete

    assert store.read("openai") is None


@pytest.mark.asyncio
async def test_a_write_with_no_app_connected_is_reported_as_not_connected():
    store = ClientHostedCredentialStore()
    store.attach_transport(bridge._transport)
    store.mark_ready()

    with pytest.raises(CredentialStoreUnavailableError) as raised:
        await store.asave("openai", "sk-new")

    assert str(raised.value) == NOT_CONNECTED_MESSAGE


@pytest.mark.asyncio
async def test_an_acknowledgment_that_never_arrives_times_out_with_a_clear_reason():
    host = FakeSocket()
    active_connections.add(host)

    with pytest.raises(CredentialStoreUnavailableError) as raised:
        await bridge._round_trip({"type": "provider_key_delete", "name": "x"}, 0.01)

    assert str(raised.value) == bridge.UNACKNOWLEDGED_MESSAGE
    assert bridge._waiters == {}


def test_replies_without_a_matching_waiter_are_ignored():
    assert bridge.handle_provider_key_message({"type": "provider_key_result"}) is False
    assert bridge.handle_provider_key_message({"type": "provider_key_result", "correlation_id": 7}) is False
    assert bridge.handle_provider_key_message({"type": "provider_key_result", "correlation_id": "unknown"}) is False


@pytest.mark.asyncio
async def test_a_reply_resolves_its_waiter_only_once():
    future = asyncio.get_running_loop().create_future()
    bridge._waiters["abc"] = future

    assert bridge.handle_provider_key_message(result("abc")) is True
    assert bridge.handle_provider_key_message(result("abc")) is False
