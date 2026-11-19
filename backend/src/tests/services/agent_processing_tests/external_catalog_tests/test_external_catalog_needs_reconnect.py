"""external_catalog fails fast for connections already marked needs_reconnect."""

from types import SimpleNamespace

import pytest

from api.services.agent_processing.tools.external_services.external_catalog import (
    actions as external_catalog_actions,
)


def _record(status):
    return SimpleNamespace(
        id="linear-prod",
        friendly_name="Linear",
        description=None,
        server_url="https://mcp.linear.app/mcp",
        enabled=True,
        cached_tools=[],
        tool_policies={"getIssue": "always_ask"},
        last_connection_status=status,
    )


def _install(monkeypatch, record):
    prefs = SimpleNamespace(connections=SimpleNamespace(mcp_connections=[record]))
    calls = {"token": 0, "approval": 0, "remote": 0, "audit": []}

    async def fake_token(connection_id):
        calls["token"] += 1
        return SimpleNamespace(access_token="tok")

    async def fake_approval(*args, **kwargs):
        calls["approval"] += 1
        return True

    async def fake_audit(**kwargs):
        calls["audit"].append(kwargs)

    class FakeClient:
        async def list_tools(self, server_url, access_token):
            calls["remote"] += 1
            return {"ok": True, "result": {"server": {}, "tools": []}}

        async def call_tool(self, server_url, tool_name, arguments, access_token):
            calls["remote"] += 1
            return {"ok": True, "result": {}}

    async def fake_schema_guard(record_arg, connection_id, tool_name):
        return None

    monkeypatch.setattr(external_catalog_actions, "load_external_catalog_preferences", lambda: prefs)
    monkeypatch.setattr(external_catalog_actions, "resolve_external_catalog_access_token", fake_token)
    monkeypatch.setattr(external_catalog_actions, "request_external_catalog_user_approval", fake_approval)
    monkeypatch.setattr(external_catalog_actions, "record_external_catalog_audit", fake_audit)
    monkeypatch.setattr(external_catalog_actions, "get_external_catalog_mcp_client", lambda: FakeClient())
    monkeypatch.setattr(external_catalog_actions, "ensure_tool_schema_surfaced", fake_schema_guard)
    return calls


@pytest.mark.asyncio
async def test_call_tool_skips_token_approval_and_remote_call_when_reconnect_is_needed(monkeypatch):
    calls = _install(monkeypatch, _record("needs_reconnect"))

    envelope = await external_catalog_actions.call_external_catalog_tool("linear-prod", "getIssue", {"id": "BAS-1"})

    assert envelope["ok"] is False
    assert envelope["error"]["kind"] == "auth_expired"
    assert envelope["error"]["retryable"] is False
    assert envelope["error"]["user_action_required"] == "Reconnect Linear in Settings → Connections."
    assert envelope["error"]["raw"] == {"known_status": "needs_reconnect"}
    assert calls["token"] == 0
    assert calls["approval"] == 0
    assert calls["remote"] == 0
    assert len(calls["audit"]) == 1
    assert calls["audit"][0]["classification"] == "error"
    assert calls["audit"][0]["tool_name"] == "getIssue"


@pytest.mark.asyncio
async def test_describe_server_skips_token_and_remote_call_when_reconnect_is_needed(monkeypatch):
    calls = _install(monkeypatch, _record("needs_reconnect"))

    envelope = await external_catalog_actions.describe_external_catalog_server("linear-prod")

    assert envelope["error"]["kind"] == "auth_expired"
    assert calls["token"] == 0
    assert calls["remote"] == 0
    assert calls["audit"][0]["tool_name"] == "describe_server"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["healthy", "token_unavailable", "error", None])
async def test_other_statuses_still_dispatch(monkeypatch, status):
    calls = _install(monkeypatch, _record(status))

    envelope = await external_catalog_actions.call_external_catalog_tool("linear-prod", "getIssue", {"id": "BAS-1"})

    assert envelope["ok"] is True
    assert calls["token"] == 1
    assert calls["approval"] == 1
    assert calls["remote"] == 1
