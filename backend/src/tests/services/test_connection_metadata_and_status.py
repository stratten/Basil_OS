"""Tests for MCP connection metadata and status evaluation."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from api.core.models.preferences import MCPCachedTool, MCPConnectionRecord, Preferences
from api.routes.connections import metadata_routes, status_routes
from api.services.mcp_connectors import connection_status_service as status_service
from api.services.mcp_connectors import generic_oauth_token_refresh as token_refresh_service
from api.services.mcp_connectors.connection_status_service import (
    ConnectionStatusCheckResult,
)


@pytest.mark.asyncio
async def test_metadata_route_persists_name_and_description(monkeypatch):
    record = MCPConnectionRecord(
        friendly_name="Linear",
        server_url="https://mcp.linear.app/mcp",
    )
    prefs = Preferences()
    prefs.connections.mcp_connections = [record]
    saved = {}

    monkeypatch.setattr(metadata_routes, "load_connection_preferences", lambda: prefs)
    monkeypatch.setattr(
        metadata_routes,
        "save_connection_preferences",
        lambda p: saved.update({"prefs": p}),
    )

    response = await metadata_routes.update_connection_metadata(
        record.id,
        SimpleNamespace(
            friendly_name="  Linear - Engineering  ",
            description="  Engineering workspace  ",
        ),
    )

    assert record.friendly_name == "Linear - Engineering"
    assert record.description == "Engineering workspace"
    assert response.friendly_name == "Linear - Engineering"
    assert response.description == "Engineering workspace"
    assert saved["prefs"] is prefs


@pytest.mark.asyncio
async def test_metadata_route_rejects_empty_name(monkeypatch):
    record = MCPConnectionRecord(
        friendly_name="Linear",
        server_url="https://mcp.linear.app/mcp",
    )
    prefs = Preferences()
    prefs.connections.mcp_connections = [record]
    monkeypatch.setattr(metadata_routes, "load_connection_preferences", lambda: prefs)

    with pytest.raises(Exception) as exc:
        await metadata_routes.update_connection_metadata(
            record.id,
            SimpleNamespace(friendly_name="   ", description=None),
        )

    assert getattr(exc.value, "status_code", None) == 400


@pytest.mark.asyncio
async def test_status_route_persists_evaluated_status(monkeypatch):
    checked_at = datetime.utcnow()
    record = MCPConnectionRecord(
        friendly_name="Linear",
        server_url="https://mcp.linear.app/mcp",
    )
    prefs = Preferences()
    prefs.connections.mcp_connections = [record]
    saved = {}

    async def fake_check_connection_status(_record):
        return ConnectionStatusCheckResult(
            status="healthy",
            message="Connection validated successfully.",
            checked_at=checked_at,
            refreshed_credentials=True,
            server={"name": "linear-mcp"},
        )

    monkeypatch.setattr(status_routes, "load_connection_preferences", lambda: prefs)
    monkeypatch.setattr(
        status_routes,
        "save_connection_preferences",
        lambda p: saved.update({"prefs": p}),
    )
    monkeypatch.setattr(status_routes, "check_connection_status", fake_check_connection_status)

    response = await status_routes.check_connection_status_route(record.id)

    assert record.last_connection_status == "healthy"
    assert record.last_connection_status_message == "Connection validated successfully."
    assert record.last_connection_check_at == checked_at
    assert record.server_name == "linear-mcp"
    assert response.connection.last_connection_status == "healthy"
    assert response.refreshed_credentials is True
    assert saved["prefs"] is prefs


@pytest.mark.asyncio
async def test_generic_status_success_does_not_refresh_tool_catalog(monkeypatch):
    record = MCPConnectionRecord(
        friendly_name="Generic",
        server_url="https://generic.example/mcp",
        cached_tools=[MCPCachedTool(name="cached_old")],
        last_tool_refresh_at=datetime.utcnow(),
    )
    original_tools = list(record.cached_tools)
    original_refresh_at = record.last_tool_refresh_at

    async def fake_token(connection_id):
        return SimpleNamespace(access_token="access", message=None, user_action_required=None)

    class FakeClient:
        async def list_tools(self, server_url, access_token):
            return {
                "ok": True,
                "result": {
                    "server": {"name": "generic-mcp"},
                    "tools": [{"name": "live_new"}],
                },
            }

    monkeypatch.setattr(status_service, "_request_access_token_from_swift", fake_token)

    result = await status_service.check_connection_status(
        record,
        mcp_client=FakeClient(),
    )

    assert result.status == "healthy"
    assert result.server == {"name": "generic-mcp"}
    assert record.cached_tools == original_tools
    assert record.last_tool_refresh_at == original_refresh_at


@pytest.mark.asyncio
async def test_generic_status_refreshes_oauth_token_after_auth_expired(monkeypatch):
    pushes = []
    record = MCPConnectionRecord(
        friendly_name="Generic",
        server_url="https://generic.example/mcp",
        oauth_client_id="client-id",
        oauth_token_endpoint="https://auth.example/token",
    )

    async def fake_access_token(connection_id):
        return SimpleNamespace(access_token="old", message=None, user_action_required=None)

    async def fake_bundle(connection_id, **_kwargs):
        return SimpleNamespace(refresh_token="refresh")

    async def fake_push(**kwargs):
        pushes.append(kwargs)

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def list_tools(self, server_url, access_token):
            self.calls += 1
            if self.calls == 1:
                return {
                    "ok": False,
                    "error": {"kind": "auth_expired", "message": "expired"},
                }
            return {"ok": True, "result": {"server": {}, "tools": []}}

    class FakeOAuth:
        async def refresh(self, **kwargs):
            return SimpleNamespace(
                access_token="new",
                refresh_token="refresh-new",
                expires_in=3600,
            )

    monkeypatch.setattr(status_service, "_request_access_token_from_swift", fake_access_token)
    monkeypatch.setattr(token_refresh_service, "_request_token_bundle_from_swift", fake_bundle)
    monkeypatch.setattr(token_refresh_service, "_push_token_to_swift", fake_push)

    result = await status_service.check_connection_status(
        record,
        mcp_client=FakeClient(),
        oauth_coordinator=FakeOAuth(),
    )

    assert result.status == "healthy"
    assert result.refreshed_credentials is True
    assert pushes == [
        {
            "connection_id": record.id,
            "access_token": "new",
            "refresh_token": "refresh-new",
            "expires_in": 3600,
        }
    ]


@pytest.mark.asyncio
async def test_generic_status_without_refresh_metadata_needs_reconnect(monkeypatch):
    record = MCPConnectionRecord(
        friendly_name="Manual",
        server_url="https://manual.example/mcp",
    )

    async def fake_token(connection_id):
        return SimpleNamespace(access_token="bad", message=None, user_action_required=None)

    class FakeClient:
        async def list_tools(self, server_url, access_token):
            return {
                "ok": False,
                "error": {"kind": "auth_expired", "message": "bad credentials"},
            }

    monkeypatch.setattr(status_service, "_request_access_token_from_swift", fake_token)

    result = await status_service.check_connection_status(record, mcp_client=FakeClient())

    assert result.status == "needs_reconnect"
    assert "bad credentials" in result.message


@pytest.mark.asyncio
async def test_slack_status_uses_real_validation_not_static_catalog(monkeypatch):
    record = MCPConnectionRecord(
        friendly_name="Slack",
        server_url="basil-local://slack",
        oauth_client_id="client-id",
    )

    async def fake_token(connection_id):
        return SimpleNamespace(access_token="bad", message=None, user_action_required=None)

    async def fake_validate(access_token):
        return SimpleNamespace(kind="invalid", message="Slack rejected the token (invalid_auth).")

    async def fake_refresh(**kwargs):
        return SimpleNamespace(
            kind="missing_refresh_token",
            access_token=None,
            message="No refresh token.",
        )

    monkeypatch.setattr(status_service, "_request_access_token_from_swift", fake_token)
    monkeypatch.setattr(status_service, "validate_slack_access_token", fake_validate)
    monkeypatch.setattr(status_service, "refresh_slack_token", fake_refresh)

    result = await status_service.check_connection_status(record)

    assert result.status == "needs_reconnect"
    assert "No refresh token" in result.message


@pytest.mark.asyncio
async def test_slack_status_refresh_success_validates_new_token(monkeypatch):
    record = MCPConnectionRecord(
        friendly_name="Slack",
        server_url="basil-local://slack",
        oauth_client_id="client-id",
    )
    validated_tokens = []

    async def fake_token(connection_id):
        return SimpleNamespace(access_token="old", message=None, user_action_required=None)

    async def fake_validate(access_token):
        validated_tokens.append(access_token)
        if access_token == "new":
            return SimpleNamespace(kind="valid", message="ok")
        return SimpleNamespace(kind="invalid", message="invalid")

    async def fake_refresh(**kwargs):
        return SimpleNamespace(kind="refreshed", access_token="new", message=None)

    monkeypatch.setattr(status_service, "_request_access_token_from_swift", fake_token)
    monkeypatch.setattr(status_service, "validate_slack_access_token", fake_validate)
    monkeypatch.setattr(status_service, "refresh_slack_token", fake_refresh)

    result = await status_service.check_connection_status(record)

    assert result.status == "healthy"
    assert result.refreshed_credentials is True
    assert validated_tokens == ["old", "new"]
