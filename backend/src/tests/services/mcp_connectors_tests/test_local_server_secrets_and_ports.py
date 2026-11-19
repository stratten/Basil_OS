"""Keychain secrets for a local server, free-port allocation and readiness, and the host-connected wait."""

from __future__ import annotations

import asyncio
import socket
from typing import Any, Dict, List

import pytest

from api.services import host_connection_channel
from api.services.mcp_connectors import local_server_secrets
from api.services.mcp_connectors.local_server_secrets import delete_secret_values, resolve_secret_env, secret_account
from api.services.mcp_connectors.port_allocation import (
    allocate_loopback_port,
    port_accepts_connections,
    wait_until_port_accepts,
)


class _FakeKeychain:
    """Stands in for the app: answers each requested account from a dict and records what was asked."""

    def __init__(self, saved: Dict[str, str], *, unavailable: bool = False) -> None:
        self.saved = saved
        self.unavailable = unavailable
        self.requested: List[str] = []

    async def __call__(self, *, connection_id: str, timeout_s, agent_task_id, include_refresh_token, cancel_event=None) -> Dict[str, Any]:
        self.requested.append(connection_id)
        assert agent_task_id is None
        assert include_refresh_token is False
        if self.unavailable:
            return {"kind": "client_unavailable", "message": "No Basil client is connected to provide the external service token."}
        if connection_id in self.saved:
            return {"kind": "token_available", "access_token": self.saved[connection_id]}
        return {"kind": "token_missing", "access_token": None}


def test_the_account_key_names_the_connection_and_the_variable():
    assert secret_account("abc", "API_KEY") == "abc.env.API_KEY"


@pytest.mark.asyncio
async def test_saved_values_are_returned_by_name_and_each_account_is_asked_once(monkeypatch):
    keychain = _FakeKeychain({"c1.env.A": "alpha", "c1.env.B": "beta"})
    monkeypatch.setattr(local_server_secrets, "_ask_swift_for_credentials", keychain)

    resolution = await resolve_secret_env("c1", ["A", "B", "A"])

    assert resolution.values == {"A": "alpha", "B": "beta"}
    assert resolution.complete is True
    assert keychain.requested == ["c1.env.A", "c1.env.B"]


@pytest.mark.asyncio
async def test_a_value_that_was_never_saved_is_reported_missing_without_failing_the_rest(monkeypatch):
    monkeypatch.setattr(local_server_secrets, "_ask_swift_for_credentials", _FakeKeychain({"c1.env.A": "alpha"}))

    resolution = await resolve_secret_env("c1", ["A", "B"])

    assert resolution.values == {"A": "alpha"}
    assert resolution.missing == ["B"]
    assert resolution.complete is False


@pytest.mark.asyncio
async def test_an_empty_saved_value_counts_as_missing(monkeypatch):
    monkeypatch.setattr(local_server_secrets, "_ask_swift_for_credentials", _FakeKeychain({"c1.env.A": ""}))

    resolution = await resolve_secret_env("c1", ["A"])

    assert resolution.values == {}
    assert resolution.missing == ["A"]


@pytest.mark.asyncio
async def test_no_connected_app_blocks_instead_of_pretending_the_value_is_missing(monkeypatch):
    keychain = _FakeKeychain({}, unavailable=True)
    monkeypatch.setattr(local_server_secrets, "_ask_swift_for_credentials", keychain)

    resolution = await resolve_secret_env("c1", ["A", "B"])

    assert resolution.blocked_message and "No Basil client" in resolution.blocked_message
    assert resolution.missing == []
    assert keychain.requested == ["c1.env.A"]
    assert resolution.complete is False


@pytest.mark.asyncio
async def test_no_names_means_no_keychain_traffic(monkeypatch):
    keychain = _FakeKeychain({})
    monkeypatch.setattr(local_server_secrets, "_ask_swift_for_credentials", keychain)

    resolution = await resolve_secret_env("c1", [], wait_for_host=True)

    assert resolution.complete is True and resolution.values == {}
    assert keychain.requested == []


@pytest.mark.asyncio
async def test_waiting_for_the_host_happens_before_the_first_request(monkeypatch):
    order: List[str] = []
    keychain = _FakeKeychain({"c1.env.A": "alpha"})

    async def _ask(**kwargs):
        order.append("ask")
        return await keychain(**kwargs)

    async def _wait(timeout_seconds=None):
        order.append("wait")
        return True

    monkeypatch.setattr(local_server_secrets, "_ask_swift_for_credentials", _ask)
    monkeypatch.setattr(host_connection_channel, "wait_for_host_connection", _wait)

    await resolve_secret_env("c1", ["A"], wait_for_host=True)

    assert order == ["wait", "ask"]


@pytest.mark.asyncio
async def test_deleting_pushes_one_delete_per_distinct_secret(monkeypatch):
    pushed: List[str] = []

    async def _push(connection_id: str) -> None:
        pushed.append(connection_id)

    monkeypatch.setattr(local_server_secrets, "_push_token_delete_to_swift", _push)

    await delete_secret_values("c1", ["A", "B", "A"])

    assert pushed == ["c1.env.A", "c1.env.B"]


def test_allocated_ports_are_free_and_usable():
    first = allocate_loopback_port()
    second = allocate_loopback_port()

    assert 1024 <= first <= 65535 and 1024 <= second <= 65535
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", first))


@pytest.mark.asyncio
async def test_port_readiness_follows_whether_something_is_listening():
    port = allocate_loopback_port()
    assert await port_accepts_connections(port) is False

    server = await asyncio.start_server(lambda reader, writer: writer.close(), "127.0.0.1", port)
    try:
        assert await port_accepts_connections(port) is True
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_waiting_for_a_port_returns_false_at_once_when_the_program_has_exited():
    assert await wait_until_port_accepts(allocate_loopback_port(), timeout_seconds=5, is_alive=lambda: False) is False


@pytest.mark.asyncio
async def test_waiting_for_a_port_gives_up_when_the_time_runs_out():
    assert await wait_until_port_accepts(allocate_loopback_port(), timeout_seconds=0.3, is_alive=lambda: True, poll_seconds=0.05) is False


@pytest.mark.asyncio
async def test_waiting_for_a_port_succeeds_when_the_program_binds_late():
    port = allocate_loopback_port()
    started: List[Any] = []

    async def _bind_late() -> None:
        await asyncio.sleep(0.3)
        started.append(await asyncio.start_server(lambda reader, writer: writer.close(), "127.0.0.1", port))

    binder = asyncio.create_task(_bind_late())
    try:
        assert await wait_until_port_accepts(port, timeout_seconds=5, is_alive=lambda: True, poll_seconds=0.05) is True
    finally:
        await binder
        for server in started:
            server.close()
            await server.wait_closed()


@pytest.mark.asyncio
async def test_the_host_wait_returns_at_once_when_a_host_is_already_connected(monkeypatch):
    monkeypatch.setattr(host_connection_channel, "host_connections", lambda: [object()])

    assert await host_connection_channel.wait_for_host_connection(timeout_seconds=0.1) is True
    assert host_connection_channel._host_waiters == []


@pytest.mark.asyncio
async def test_the_host_wait_is_woken_by_the_connection_event(monkeypatch):
    monkeypatch.setattr(host_connection_channel, "host_connections", lambda: [])

    waiter = asyncio.create_task(host_connection_channel.wait_for_host_connection(timeout_seconds=5))
    await asyncio.sleep(0)
    assert len(host_connection_channel._host_waiters) == 1

    host_connection_channel.note_host_connected()

    assert await waiter is True
    assert host_connection_channel._host_waiters == []


@pytest.mark.asyncio
async def test_the_host_wait_times_out_and_leaves_no_waiter_behind(monkeypatch):
    monkeypatch.setattr(host_connection_channel, "host_connections", lambda: [])

    assert await host_connection_channel.wait_for_host_connection(timeout_seconds=0.1) is False
    assert host_connection_channel._host_waiters == []
