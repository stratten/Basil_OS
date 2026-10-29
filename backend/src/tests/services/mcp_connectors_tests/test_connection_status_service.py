"""Tests for MCP connection status checking.

Covers the Slack/generic dispatch branch (now routed through the shared
``is_slack_connection`` predicate) and the generic branch's delegation to
the shared ``refresh_generic_oauth_access_token`` - this file had zero
coverage before that refactor, so these lock in behavior parity.
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from api.services.mcp_connectors import connection_status_service as status_service


def _record(**overrides):
    defaults = dict(
        id="conn-1",
        server_url="https://mcp.linear.app/mcp",
        oauth_client_id="client-abc",
        oauth_token_endpoint="https://linear.app/oauth/token",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class _FakeMCPClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def list_tools(self, server_url, access_token):
        self.calls.append((server_url, access_token))
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_check_connection_status_routes_slack_records_through_the_slack_branch(monkeypatch):
    calls = []

    async def fake_check_slack_status(record, *, slack_coordinator):
        calls.append(record.id)
        return status_service.ConnectionStatusCheckResult(
            status=status_service.STATUS_HEALTHY,
            message="ok",
            checked_at=datetime.utcnow(),
        )

    monkeypatch.setattr(status_service, "is_slack_connection", lambda record: True)
    monkeypatch.setattr(status_service, "_check_slack_status", fake_check_slack_status)

    result = await status_service.check_connection_status(_record(server_url="basil-local://slack"))

    assert calls == ["conn-1"]
    assert result.status == status_service.STATUS_HEALTHY


@pytest.mark.asyncio
async def test_generic_status_check_is_healthy_without_needing_a_refresh(monkeypatch):
    monkeypatch.setattr(status_service, "is_slack_connection", lambda record: False)

    async def fake_token(connection_id, **kwargs):
        return SimpleNamespace(access_token="tok", message=None, user_action_required=None)

    monkeypatch.setattr(status_service, "_request_access_token_from_swift", fake_token)

    client = _FakeMCPClient([{"ok": True, "result": {"tools": ["a", "b"], "server": {"name": "Linear"}}}])

    async def fail_refresh(*args, **kwargs):
        raise AssertionError("must not attempt a refresh when the first call succeeds")

    monkeypatch.setattr(status_service, "refresh_generic_oauth_access_token", fail_refresh)

    result = await status_service.check_connection_status(_record(), mcp_client=client)

    assert result.status == status_service.STATUS_HEALTHY
    assert result.refreshed_credentials is False
    assert "2 tool(s)" in result.message
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_generic_status_check_recovers_silently_after_a_stale_token(monkeypatch):
    """The exact scenario the user observed: Settings' status check silently
    refreshes a merely-stale generic MCP token and reports healthy."""

    monkeypatch.setattr(status_service, "is_slack_connection", lambda record: False)

    async def fake_token(connection_id, **kwargs):
        return SimpleNamespace(access_token="stale-tok", message=None, user_action_required=None)

    monkeypatch.setattr(status_service, "_request_access_token_from_swift", fake_token)

    client = _FakeMCPClient(
        [
            {"ok": False, "error": {"kind": "auth_expired", "message": "expired"}},
            {"ok": True, "result": {"tools": ["a"], "server": {}}},
        ]
    )

    async def fake_refresh(record, *, oauth_coordinator):
        assert record.id == "conn-1"
        return "fresh-tok"

    monkeypatch.setattr(status_service, "refresh_generic_oauth_access_token", fake_refresh)

    result = await status_service.check_connection_status(_record(), mcp_client=client)

    assert result.status == status_service.STATUS_HEALTHY
    assert result.refreshed_credentials is True
    assert client.calls[0] == ("https://mcp.linear.app/mcp", "stale-tok")
    assert client.calls[1] == ("https://mcp.linear.app/mcp", "fresh-tok")


@pytest.mark.asyncio
async def test_generic_status_check_still_asks_to_reconnect_when_refresh_is_unavailable(monkeypatch):
    """No stored refresh token (or a rejected one) must still surface the
    existing needs_reconnect messaging - no silent failure, no regression."""

    monkeypatch.setattr(status_service, "is_slack_connection", lambda record: False)

    async def fake_token(connection_id, **kwargs):
        return SimpleNamespace(access_token="stale-tok", message=None, user_action_required=None)

    monkeypatch.setattr(status_service, "_request_access_token_from_swift", fake_token)

    client = _FakeMCPClient([{"ok": False, "error": {"kind": "auth_expired", "message": "expired"}}])

    async def fake_refresh(record, *, oauth_coordinator):
        return None

    monkeypatch.setattr(status_service, "refresh_generic_oauth_access_token", fake_refresh)

    result = await status_service.check_connection_status(_record(), mcp_client=client)

    assert result.status == status_service.STATUS_NEEDS_RECONNECT
    assert result.refreshed_credentials is False
    assert "Reconnect this server" in result.user_action_required
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_generic_status_check_reports_needs_reconnect_when_the_refreshed_token_is_also_rejected(monkeypatch):
    monkeypatch.setattr(status_service, "is_slack_connection", lambda record: False)

    async def fake_token(connection_id, **kwargs):
        return SimpleNamespace(access_token="stale-tok", message=None, user_action_required=None)

    monkeypatch.setattr(status_service, "_request_access_token_from_swift", fake_token)

    client = _FakeMCPClient(
        [
            {"ok": False, "error": {"kind": "auth_expired", "message": "expired"}},
            {"ok": False, "error": {"kind": "auth_expired", "message": "still rejected"}},
        ]
    )

    async def fake_refresh(record, *, oauth_coordinator):
        return "fresh-tok-that-is-also-bad"

    monkeypatch.setattr(status_service, "refresh_generic_oauth_access_token", fake_refresh)

    result = await status_service.check_connection_status(_record(), mcp_client=client)

    assert result.status == status_service.STATUS_NEEDS_RECONNECT
    assert result.refreshed_credentials is True
    assert "still rejected" in result.message
