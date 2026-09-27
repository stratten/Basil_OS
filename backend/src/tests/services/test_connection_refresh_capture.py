"""Server-metadata capture on the connection tool-refresh path.

Proves that ``refresh_tools`` persists the secret-free server self-description
(serverInfo.name + MCP ``instructions``) onto the connection record so routing
surfaces can later identify which system the connection serves.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.core.models.preferences import MCPConnectionRecord, Preferences
from api.routes.connections import routes


@pytest.mark.asyncio
async def test_refresh_tools_captures_server_name_and_instructions(monkeypatch):
    record = MCPConnectionRecord(
        friendly_name="Speakeasy - Custom",
        server_url="https://app.speakeasy.is/mcp",
    )
    prefs = Preferences()
    prefs.connections.mcp_connections = [record]

    saved = {}

    monkeypatch.setattr(routes, "load_connection_preferences", lambda: prefs)
    monkeypatch.setattr(routes, "save_connection_preferences", lambda p: saved.update({"prefs": p}))

    async def _fake_token(connection_id):
        return SimpleNamespace(
            access_token="tok", kind=None, message=None, user_action_required=None
        )

    monkeypatch.setattr(routes, "_request_access_token_from_swift", _fake_token)

    async def _fake_list_tools(server_url, access_token):
        return {
            "ok": True,
            "result": {
                "server": {
                    "name": "salesforce-mcp",
                    "version": "1.0",
                    "protocol": "2025-06-18",
                    "instructions": "Use these tools to read and write Salesforce records.",
                },
                "tools": [
                    {
                        "name": "sf_query",
                        "description": "Query Salesforce records.",
                        "is_read_only_hint": True,
                    }
                ],
            },
        }

    monkeypatch.setattr(routes._mcp_client, "list_tools", _fake_list_tools)

    await routes.refresh_tools(record.id, request=None)

    assert record.server_name == "salesforce-mcp"
    assert record.server_instructions == "Use these tools to read and write Salesforce records."
    assert record.cached_tools and record.cached_tools[0].name == "sf_query"
    assert saved.get("prefs") is prefs


@pytest.mark.asyncio
async def test_refresh_tools_no_server_block_leaves_metadata_unset(monkeypatch):
    record = MCPConnectionRecord(
        friendly_name="Bare Server",
        server_url="https://bare.example/mcp",
    )
    prefs = Preferences()
    prefs.connections.mcp_connections = [record]

    monkeypatch.setattr(routes, "load_connection_preferences", lambda: prefs)
    monkeypatch.setattr(routes, "save_connection_preferences", lambda p: None)

    async def _fake_token(connection_id):
        return SimpleNamespace(
            access_token="tok", kind=None, message=None, user_action_required=None
        )

    monkeypatch.setattr(routes, "_request_access_token_from_swift", _fake_token)

    async def _fake_list_tools(server_url, access_token):
        return {"ok": True, "result": {"server": {}, "tools": []}}

    monkeypatch.setattr(routes._mcp_client, "list_tools", _fake_list_tools)

    await routes.refresh_tools(record.id, request=None)

    assert record.server_name is None
    assert record.server_instructions is None


@pytest.mark.asyncio
async def test_refresh_tools_marks_connection_healthy_on_success(monkeypatch):
    """A successful tool-catalog fetch already proves the token is valid and
    the server is reachable -- the same evidence a manual "Check Status"
    would produce -- so the connection should read as healthy immediately
    after it's added instead of "not checked yet" until the user manually
    checks it."""
    record = MCPConnectionRecord(
        friendly_name="Linear",
        server_url="https://mcp.linear.app/sse",
    )
    assert record.last_connection_status is None

    prefs = Preferences()
    prefs.connections.mcp_connections = [record]

    monkeypatch.setattr(routes, "load_connection_preferences", lambda: prefs)
    monkeypatch.setattr(routes, "save_connection_preferences", lambda p: None)

    async def _fake_token(connection_id):
        return SimpleNamespace(
            access_token="tok", kind=None, message=None, user_action_required=None
        )

    monkeypatch.setattr(routes, "_request_access_token_from_swift", _fake_token)

    async def _fake_list_tools(server_url, access_token):
        return {"ok": True, "result": {"server": {}, "tools": []}}

    monkeypatch.setattr(routes._mcp_client, "list_tools", _fake_list_tools)

    await routes.refresh_tools(record.id, request=None)

    assert record.last_connection_status == "healthy"
    assert record.last_connection_status_message == "Connected."
    assert record.last_connection_check_at is not None
