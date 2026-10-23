"""Tests for re-authorizing MCP connections in place and recording dead credentials."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.core.models.preferences import MCPConnectionRecord, Preferences
from api.routes.connections import connection_route_helpers
from api.routes.connections import reconnect_support
from api.routes.connections import routes as connection_routes
from api.routes.connections import slack_routes
from api.routes.connections.models import (
    GitHubDeviceFlowPollRequest,
    SlackCompleteOAuthRequest,
    StartOAuthRequest,
)
from api.services.agent_processing.tools.external_services.external_catalog import auth as catalog_auth
from api.services.mcp_connectors import connection_status_service as status_service
from api.services.mcp_connectors.github_device_flow_coordinator import GITHUB_OAUTH_CLIENT_ID
from api.services.mcp_connectors.slack_local_server import LOCAL_SLACK_SENTINEL_URL


def _oauth_record(**overrides) -> MCPConnectionRecord:
    values = dict(
        friendly_name="Linear",
        server_url="https://mcp.linear.app/mcp",
        oauth_client_id="old-client",
        oauth_authorization_server="https://auth.linear.example",
        oauth_token_endpoint="https://auth.linear.example/token",
        oauth_scopes=["read"],
        tool_policies={"create_issue": "never_allow"},
        last_connection_status="needs_reconnect",
        last_connection_status_message="MCP server rejected credentials with HTTP 401",
    )
    values.update(overrides)
    return MCPConnectionRecord(**values)


def _install_prefs(monkeypatch, records):
    prefs = Preferences()
    prefs.connections.mcp_connections = list(records)
    saves = []
    for module in (connection_routes, reconnect_support, slack_routes):
        monkeypatch.setattr(module, "load_connection_preferences", lambda: prefs)
        monkeypatch.setattr(module, "save_connection_preferences", lambda p: saves.append(p))
    return prefs, saves


def _capture_token_pushes(monkeypatch, module):
    pushes = []

    async def fake_push(**kwargs):
        pushes.append(kwargs)

    monkeypatch.setattr(module, "_push_token_to_swift", fake_push)
    return pushes


def _descriptor(**overrides):
    values = dict(
        friendly_name="Linear",
        server_url="https://mcp.linear.app/mcp",
        client_id="new-client",
        authorization_server="https://auth.linear.example",
        token_endpoint="https://auth.linear.example/token",
        scopes=["read", "write"],
        token=SimpleNamespace(access_token="new-access", refresh_token="new-refresh", expires_in=3600),
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_auth_kind_classifies_each_sign_in_flow():
    assert connection_route_helpers.connection_auth_kind(_oauth_record()) == "oauth"
    assert connection_route_helpers.connection_auth_kind(
        MCPConnectionRecord(friendly_name="Slack", server_url=LOCAL_SLACK_SENTINEL_URL, oauth_client_id="slack-client")
    ) == "slack"
    assert connection_route_helpers.connection_auth_kind(
        MCPConnectionRecord(friendly_name="GitHub", server_url="https://api.githubcopilot.com/mcp/", oauth_client_id=GITHUB_OAUTH_CLIENT_ID)
    ) == "github_device"
    assert connection_route_helpers.connection_auth_kind(
        MCPConnectionRecord(friendly_name="Notion", server_url="https://notion.example/mcp")
    ) == "manual_token"


def test_connection_dto_carries_auth_kind():
    dto = connection_route_helpers.connection_to_dto(_oauth_record())
    assert dto.auth_kind == "oauth"


@pytest.mark.asyncio
async def test_start_oauth_reconnect_uses_the_existing_record(monkeypatch):
    record = _oauth_record()
    _install_prefs(monkeypatch, [record])
    monkeypatch.setattr(connection_routes, "_oauth_reconnect_targets", {})
    monkeypatch.setattr(connection_routes, "_oauth_connection_descriptions", {})
    calls = []

    class FakeCoordinator:
        async def begin_registration(self, **kwargs):
            calls.append(kwargs)
            return {"state": "state-1", "authorization_url": "https://auth.linear.example/authorize"}

    monkeypatch.setattr(connection_routes, "_oauth_coordinator", FakeCoordinator())

    response = await connection_routes.start_oauth(
        StartOAuthRequest(server_url="https://ignored.example", friendly_name="Ignored", connection_id=record.id),
        SimpleNamespace(base_url="http://127.0.0.1:8000/"),
    )

    assert response.state == "state-1"
    assert calls[0]["server_url"] == "https://mcp.linear.app/mcp"
    assert calls[0]["friendly_name"] == "Linear"
    assert connection_routes._oauth_reconnect_targets == {"state-1": record.id}
    assert connection_routes._oauth_connection_descriptions == {}


@pytest.mark.asyncio
async def test_start_oauth_reconnect_rejects_a_different_sign_in_kind(monkeypatch):
    record = MCPConnectionRecord(friendly_name="Notion", server_url="https://notion.example/mcp")
    _install_prefs(monkeypatch, [record])

    with pytest.raises(HTTPException) as exc:
        await connection_routes.start_oauth(
            StartOAuthRequest(server_url=record.server_url, friendly_name=record.friendly_name, connection_id=record.id),
            SimpleNamespace(base_url="http://127.0.0.1:8000/"),
        )

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_start_oauth_reconnect_for_unknown_connection_is_404(monkeypatch):
    _install_prefs(monkeypatch, [])

    with pytest.raises(HTTPException) as exc:
        await connection_routes.start_oauth(
            StartOAuthRequest(server_url="https://x.example", friendly_name="X", connection_id="missing"),
            SimpleNamespace(base_url="http://127.0.0.1:8000/"),
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_oauth_callback_reconnect_updates_the_existing_connection(monkeypatch):
    record = _oauth_record()
    prefs, saves = _install_prefs(monkeypatch, [record])
    pushes = _capture_token_pushes(monkeypatch, connection_routes)
    monkeypatch.setattr(connection_routes, "_oauth_reconnect_targets", {"state-2": record.id})

    class FakeCoordinator:
        async def complete_registration(self, *, state, code):
            return _descriptor()

    monkeypatch.setattr(connection_routes, "_oauth_coordinator", FakeCoordinator())

    response = await connection_routes.oauth_callback(state="state-2", code="auth-code")

    assert len(prefs.connections.mcp_connections) == 1
    assert record.oauth_client_id == "new-client"
    assert record.oauth_scopes == ["read", "write"]
    assert record.last_connection_status is None
    assert record.last_connection_status_message is None
    assert record.tool_policies == {"create_issue": "never_allow"}
    assert saves
    assert pushes == [
        {
            "connection_id": record.id,
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }
    ]
    assert f"connection_id={record.id}" in response.headers["location"]
    assert connection_routes._oauth_reconnect_targets == {}


@pytest.mark.asyncio
async def test_oauth_callback_reconnect_for_removed_connection_reports_error(monkeypatch):
    prefs, _saves = _install_prefs(monkeypatch, [])
    pushes = _capture_token_pushes(monkeypatch, connection_routes)
    monkeypatch.setattr(connection_routes, "_oauth_reconnect_targets", {"state-3": "removed-id"})

    class FakeCoordinator:
        async def complete_registration(self, *, state, code):
            return _descriptor()

    monkeypatch.setattr(connection_routes, "_oauth_coordinator", FakeCoordinator())

    response = await connection_routes.oauth_callback(state="state-3", code="auth-code")

    assert "status=error" in response.headers["location"]
    assert pushes == []
    assert prefs.connections.mcp_connections == []


@pytest.mark.asyncio
async def test_oauth_callback_error_consumes_the_reconnect_target(monkeypatch):
    monkeypatch.setattr(connection_routes, "_oauth_reconnect_targets", {"state-4": "conn-id"})

    response = await connection_routes.oauth_callback(state="state-4", error="access_denied")

    assert "status=error" in response.headers["location"]
    assert connection_routes._oauth_reconnect_targets == {}


@pytest.mark.asyncio
async def test_github_poll_reconnect_updates_the_existing_connection(monkeypatch):
    record = MCPConnectionRecord(
        friendly_name="GitHub",
        server_url="https://api.githubcopilot.com/mcp/",
        oauth_client_id=GITHUB_OAUTH_CLIENT_ID,
        oauth_scopes=["repo"],
        last_connection_status="needs_reconnect",
    )
    prefs, _saves = _install_prefs(monkeypatch, [record])
    pushes = _capture_token_pushes(monkeypatch, connection_routes)
    monkeypatch.setattr(connection_routes, "_github_reconnect_targets", {"device-1": record.id})
    monkeypatch.setattr(connection_routes, "_github_connection_descriptions", {})

    class FakeDeviceFlow:
        async def get_pending_authorization(self, device_code):
            return SimpleNamespace(friendly_name="GitHub", server_url=record.server_url, scopes=["repo"], interval=5)

        async def poll_token(self, *, device_code):
            return SimpleNamespace(access_token="gho-new", scope="repo,read:org")

    monkeypatch.setattr(connection_routes, "_github_device_flow_coordinator", FakeDeviceFlow())

    response = await connection_routes.poll_github_device_flow(GitHubDeviceFlowPollRequest(device_code="device-1"))

    assert response.status == "ok"
    assert response.connection.id == record.id
    assert response.connection.auth_kind == "github_device"
    assert len(prefs.connections.mcp_connections) == 1
    assert record.oauth_scopes == ["repo", "read:org"]
    assert record.last_connection_status is None
    assert pushes[0]["connection_id"] == record.id
    assert pushes[0]["access_token"] == "gho-new"
    assert connection_routes._github_reconnect_targets == {}


@pytest.mark.asyncio
async def test_slack_complete_reconnect_updates_the_existing_connection(monkeypatch):
    record = MCPConnectionRecord(
        friendly_name="Slack",
        server_url=LOCAL_SLACK_SENTINEL_URL,
        oauth_client_id="slack-client",
        oauth_scopes=["chat:write"],
        last_connection_status="needs_reconnect",
    )
    prefs, _saves = _install_prefs(monkeypatch, [record])
    pushes = _capture_token_pushes(monkeypatch, slack_routes)
    monkeypatch.setattr(slack_routes, "_slack_reconnect_targets", {"slack-state": record.id})
    monkeypatch.setattr(slack_routes, "_slack_connection_descriptions", {})

    class FakeSlack:
        async def complete_authorization(self, *, state, code):
            return _descriptor(friendly_name="Slack", client_id="slack-client-2", scopes=["chat:write", "search:read"])

    monkeypatch.setattr(slack_routes, "_slack_pkce_coordinator", FakeSlack())

    response = await slack_routes.slack_complete_oauth(SlackCompleteOAuthRequest(state="slack-state", code="code"))

    assert response.status == "ok"
    assert response.connection.id == record.id
    assert len(prefs.connections.mcp_connections) == 1
    assert record.server_url == LOCAL_SLACK_SENTINEL_URL
    assert record.oauth_client_id == "slack-client-2"
    assert record.oauth_token_endpoint == "https://slack.com/api/oauth.v2.user.access"
    assert pushes[0]["connection_id"] == record.id
    assert slack_routes._slack_reconnect_targets == {}


@pytest.mark.asyncio
async def test_new_connection_flow_still_appends_a_record(monkeypatch):
    prefs, _saves = _install_prefs(monkeypatch, [])
    pushes = _capture_token_pushes(monkeypatch, connection_routes)
    monkeypatch.setattr(connection_routes, "_oauth_reconnect_targets", {})
    monkeypatch.setattr(connection_routes, "_oauth_connection_descriptions", {"state-5": "Engineering"})

    class FakeCoordinator:
        async def complete_registration(self, *, state, code):
            return _descriptor()

    monkeypatch.setattr(connection_routes, "_oauth_coordinator", FakeCoordinator())

    await connection_routes.oauth_callback(state="state-5", code="auth-code")

    assert len(prefs.connections.mcp_connections) == 1
    assert prefs.connections.mcp_connections[0].description == "Engineering"
    assert pushes[0]["connection_id"] == prefs.connections.mcp_connections[0].id


def test_mark_connection_needs_reconnect_persists_status(monkeypatch):
    from api.core.preferences import preferences_io

    record = _oauth_record(last_connection_status="healthy", last_connection_status_message="Connected.")
    prefs = Preferences()
    prefs.connections.mcp_connections = [record]
    saves = []
    monkeypatch.setattr(preferences_io, "load_preferences", lambda: prefs)
    monkeypatch.setattr(preferences_io, "save_preferences", lambda p: saves.append(p))

    assert status_service.mark_connection_needs_reconnect(record.id, "rejected") is True
    assert record.last_connection_status == "needs_reconnect"
    assert record.last_connection_status_message == "rejected"
    assert record.last_connection_check_at is not None
    assert saves == [prefs]

    assert status_service.mark_connection_needs_reconnect("unknown-id", "rejected") is False
    assert saves == [prefs]


@pytest.mark.parametrize(
    ("envelope", "expected_calls"),
    [
        ({"ok": False, "error": {"kind": "auth_expired", "message": "HTTP 401"}}, [("conn-1", "HTTP 401")]),
        ({"ok": False, "error": {"kind": "auth_expired"}}, [("conn-1", "The server rejected this connection's credentials.")]),
        ({"ok": False, "error": {"kind": "auth_unavailable", "message": "no token"}}, []),
        ({"ok": False, "error": {"kind": "rate_limited", "message": "slow down"}}, []),
        ({"ok": True, "result": {}}, []),
    ],
)
def test_record_connection_auth_rejection_marks_only_rejected_credentials(monkeypatch, envelope, expected_calls):
    calls = []
    monkeypatch.setattr(
        status_service,
        "mark_connection_needs_reconnect",
        lambda connection_id, message: calls.append((connection_id, message)) or True,
    )

    catalog_auth.record_connection_auth_rejection("conn-1", envelope)

    assert calls == expected_calls
