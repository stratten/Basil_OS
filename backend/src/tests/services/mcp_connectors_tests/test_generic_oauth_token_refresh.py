"""Tests for the shared generic-OAuth (non-Slack) MCP token refresh."""

from types import SimpleNamespace

import pytest

from api.services.mcp_connectors import generic_oauth_token_refresh
from api.services.mcp_connectors import slack_token_service
from api.services.mcp_connectors.generic_oauth_token_refresh import (
    refresh_generic_oauth_access_token,
)


def _record(**overrides):
    defaults = dict(
        id="conn-linear",
        server_url="https://mcp.linear.app/mcp",
        oauth_client_id="client-abc",
        oauth_token_endpoint="https://linear.app/oauth/token",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_slack_connection_is_never_refreshed_through_the_generic_path(monkeypatch):
    """Slack records also populate oauth_client_id/oauth_token_endpoint - field
    presence alone must not trigger a generic refresh attempt against Slack's
    endpoint through the wrong (non-PKCE) coordinator."""

    async def fail_bundle(*args, **kwargs):
        raise AssertionError("must not ask Swift for a bundle on a Slack connection")

    monkeypatch.setattr(slack_token_service, "is_slack_connection", lambda record: True)
    monkeypatch.setattr(generic_oauth_token_refresh, "_request_token_bundle_from_swift", fail_bundle)

    result = await refresh_generic_oauth_access_token(_record(server_url="basil-local://slack"))

    assert result is None


@pytest.mark.asyncio
async def test_missing_oauth_endpoint_or_client_id_short_circuits(monkeypatch):
    monkeypatch.setattr(slack_token_service, "is_slack_connection", lambda record: False)

    async def fail_bundle(*args, **kwargs):
        raise AssertionError("must not round-trip to Swift without endpoint/client_id")

    monkeypatch.setattr(generic_oauth_token_refresh, "_request_token_bundle_from_swift", fail_bundle)

    assert await refresh_generic_oauth_access_token(_record(oauth_token_endpoint=None)) is None
    assert await refresh_generic_oauth_access_token(_record(oauth_client_id=None)) is None


@pytest.mark.asyncio
async def test_no_refresh_token_in_bundle_returns_none(monkeypatch):
    monkeypatch.setattr(slack_token_service, "is_slack_connection", lambda record: False)

    async def fake_bundle(connection_id, **kwargs):
        return SimpleNamespace(refresh_token=None)

    monkeypatch.setattr(generic_oauth_token_refresh, "_request_token_bundle_from_swift", fake_bundle)

    result = await refresh_generic_oauth_access_token(_record())

    assert result is None


@pytest.mark.asyncio
async def test_successful_exchange_pushes_new_token_and_returns_it(monkeypatch):
    monkeypatch.setattr(slack_token_service, "is_slack_connection", lambda record: False)
    pushed = {}

    async def fake_bundle(connection_id, **kwargs):
        assert connection_id == "conn-linear"
        return SimpleNamespace(refresh_token="old-refresh-token")

    async def fake_push(*, connection_id, access_token, refresh_token, expires_in):
        pushed.update(
            connection_id=connection_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )

    class FakeCoordinator:
        async def refresh(self, *, token_endpoint, client_id, refresh_token):
            assert token_endpoint == "https://linear.app/oauth/token"
            assert client_id == "client-abc"
            assert refresh_token == "old-refresh-token"
            return SimpleNamespace(
                access_token="new-access-token",
                refresh_token="new-refresh-token",
                expires_in=3600,
            )

    monkeypatch.setattr(generic_oauth_token_refresh, "_request_token_bundle_from_swift", fake_bundle)
    monkeypatch.setattr(generic_oauth_token_refresh, "_push_token_to_swift", fake_push)

    result = await refresh_generic_oauth_access_token(_record(), oauth_coordinator=FakeCoordinator())

    assert result == "new-access-token"
    assert pushed == {
        "connection_id": "conn-linear",
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
        "expires_in": 3600,
    }


@pytest.mark.asyncio
async def test_coordinator_omitting_a_rotated_refresh_token_preserves_the_bundle_one(monkeypatch):
    monkeypatch.setattr(slack_token_service, "is_slack_connection", lambda record: False)
    pushed = {}

    async def fake_bundle(connection_id, **kwargs):
        return SimpleNamespace(refresh_token="stable-refresh-token")

    async def fake_push(*, connection_id, access_token, refresh_token, expires_in):
        pushed.update(refresh_token=refresh_token)

    class FakeCoordinator:
        async def refresh(self, **kwargs):
            return SimpleNamespace(access_token="new-access-token", refresh_token=None, expires_in=900)

    monkeypatch.setattr(generic_oauth_token_refresh, "_request_token_bundle_from_swift", fake_bundle)
    monkeypatch.setattr(generic_oauth_token_refresh, "_push_token_to_swift", fake_push)

    await refresh_generic_oauth_access_token(_record(), oauth_coordinator=FakeCoordinator())

    assert pushed["refresh_token"] == "stable-refresh-token"


@pytest.mark.asyncio
async def test_coordinator_exception_is_caught_and_returns_none(monkeypatch):
    monkeypatch.setattr(slack_token_service, "is_slack_connection", lambda record: False)

    async def fake_bundle(connection_id, **kwargs):
        return SimpleNamespace(refresh_token="old-refresh-token")

    class FakeCoordinator:
        async def refresh(self, **kwargs):
            raise RuntimeError("token endpoint unreachable")

    monkeypatch.setattr(generic_oauth_token_refresh, "_request_token_bundle_from_swift", fake_bundle)

    result = await refresh_generic_oauth_access_token(_record(), oauth_coordinator=FakeCoordinator())

    assert result is None


@pytest.mark.asyncio
async def test_agent_task_id_and_cancel_event_are_threaded_to_the_bundle_request(monkeypatch):
    monkeypatch.setattr(slack_token_service, "is_slack_connection", lambda record: False)
    captured = {}

    async def fake_bundle(connection_id, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(refresh_token=None)

    monkeypatch.setattr(generic_oauth_token_refresh, "_request_token_bundle_from_swift", fake_bundle)

    sentinel_event = object()
    await refresh_generic_oauth_access_token(
        _record(), agent_task_id="task-1", cancel_event=sentinel_event
    )

    assert captured["agent_task_id"] == "task-1"
    assert captured["cancel_event"] is sentinel_event
