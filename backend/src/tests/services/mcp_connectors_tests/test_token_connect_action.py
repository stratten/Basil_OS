"""The connect_with_token agent action and the needs_manual_token pointer in connect_server."""

import json

import pytest

from api.services.agent_processing.tools.external_services import external_catalog_tool
from api.services.agent_processing.tools.external_services.external_catalog import connect, token_connect
from api.services.mcp_connectors import connection_setup_plan


class Record:
    def __init__(self, record_id: str, url: str, name: str):
        self.id, self.server_url, self.friendly_name = record_id, url, name


def use_registered(monkeypatch, *records):
    real = connection_setup_plan.plan_connection_setup

    def plan(url, name=None, **_kwargs):
        return real(url, name, registered_connections=list(records))

    monkeypatch.setattr(token_connect, "plan_connection_setup", plan)
    monkeypatch.setattr(connect, "plan_connection_setup", plan)
    monkeypatch.setattr(token_connect, "_existing_connection_names", lambda: [record.friendly_name for record in records])


def stub_window(monkeypatch, outcome):
    calls = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return outcome

    monkeypatch.setattr(token_connect, "request_token_entry", fake)
    return calls


@pytest.mark.asyncio
async def test_a_connected_window_reports_the_connection_and_tool_count(monkeypatch):
    use_registered(monkeypatch)
    calls = stub_window(monkeypatch, {"status": "connected", "connection_id": "c-1", "tool_count": 4})

    result = await token_connect.connect_external_catalog_server_with_token("mcp.example.com/mcp", "Example", "Docs")

    assert result["ok"] is True
    assert result["result"]["status"] == "connected"
    assert result["result"]["connection_id"] == "c-1"
    assert result["result"]["tool_count"] == 4
    assert calls == [{
        "server_url": "https://mcp.example.com/mcp", "friendly_name": "Example", "description": "Docs",
        "existing_names": [], "already_connected_as": None,
    }]


@pytest.mark.asyncio
async def test_the_name_and_description_the_user_chose_are_reported_back(monkeypatch):
    use_registered(monkeypatch)
    stub_window(monkeypatch, {"status": "connected", "connection_id": "c-2", "tool_count": 3, "friendly_name": "Example (work)", "description": "Work account"})
    result = await token_connect.connect_external_catalog_server_with_token("https://mcp.example.com/mcp", "Example")
    assert result["result"]["service"] == "Example (work)"
    assert result["result"]["description"] == "Work account"
    assert "Example (work) is connected" in result["result"]["message"]


@pytest.mark.asyncio
async def test_a_canceled_window_saves_nothing_and_is_not_an_error(monkeypatch):
    use_registered(monkeypatch)
    stub_window(monkeypatch, {"status": "canceled"})
    result = await token_connect.connect_external_catalog_server_with_token("https://mcp.example.com/mcp")
    assert result["ok"] is True
    assert result["result"]["status"] == "canceled"
    assert "Nothing was saved" in result["result"]["message"]


@pytest.mark.asyncio
async def test_a_failed_window_is_a_retryable_error_with_the_reason(monkeypatch):
    use_registered(monkeypatch)
    stub_window(monkeypatch, {"status": "failed", "message": "The service rejected the token (401)."})
    result = await token_connect.connect_external_catalog_server_with_token("https://mcp.example.com/mcp")
    assert result["ok"] is False
    assert result["error"]["kind"] == "connection_setup_failed"
    assert result["error"]["retryable"] is True
    assert "401" in result["error"]["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("address", [None, "", "   ", "http://mcp.example.com/mcp", "https://localhost/mcp", "https://10.0.0.5/mcp", "https://user:pw@mcp.example.com/"])
async def test_a_missing_or_unsafe_address_never_opens_the_window(monkeypatch, address):
    use_registered(monkeypatch)
    calls = stub_window(monkeypatch, {"status": "connected"})
    result = await token_connect.connect_external_catalog_server_with_token(address)
    assert result["ok"] is False
    assert result["error"]["kind"] == "invalid_arguments"
    assert calls == []


@pytest.mark.asyncio
async def test_an_address_that_is_already_connected_still_opens_the_window_for_a_second_instance(monkeypatch):
    use_registered(monkeypatch, Record("c-9", "https://mcp.example.com/mcp", "Example"))
    calls = stub_window(monkeypatch, {"status": "connected", "connection_id": "c-10", "tool_count": 2, "friendly_name": "Example (work)"})
    result = await token_connect.connect_external_catalog_server_with_token("https://mcp.example.com/mcp/", "Example (work)")
    assert result["result"]["status"] == "connected"
    assert result["result"]["connection_id"] == "c-10"
    assert calls[0]["existing_names"] == ["Example"]
    assert calls[0]["already_connected_as"] == "Example"
    assert calls[0]["friendly_name"] == "Example (work)"


@pytest.mark.asyncio
async def test_slack_is_pointed_back_to_browser_sign_in(monkeypatch):
    use_registered(monkeypatch)
    calls = stub_window(monkeypatch, {"status": "connected"})
    from api.routes.connections.models import STARTER_SERVERS

    slack = next(entry for entry in STARTER_SERVERS if entry.id == "slack")
    result = await token_connect.connect_external_catalog_server_with_token(slack.server_url)
    assert result["ok"] is False
    assert "connect_server" in result["error"]["message"]
    assert calls == []


@pytest.mark.asyncio
async def test_the_tool_dispatches_the_new_action(monkeypatch):
    seen = {}

    async def fake(server_url, friendly_name, description):
        seen.update(server_url=server_url, friendly_name=friendly_name, description=description)
        return {"ok": True, "result": {"status": "connected"}}

    monkeypatch.setattr(external_catalog_tool, "_connect_with_token", fake)
    raw = await external_catalog_tool._external_catalog_impl(action="connect_with_token", server_url="https://a.example.com/", friendly_name="A", description="note")
    assert json.loads(raw)["result"]["status"] == "connected"
    assert seen == {"server_url": "https://a.example.com/", "friendly_name": "A", "description": "note"}
    assert "connect_with_token" in external_catalog_tool.ExternalCatalogInput.model_json_schema()["properties"]["action"]["enum"]


@pytest.mark.asyncio
async def test_connect_server_points_a_needs_manual_token_result_at_the_new_action(monkeypatch):
    use_registered(monkeypatch)

    async def approve(_plan):
        return True

    async def start(_plan):
        return {"status": "needs_manual_token", "service": "Example", "message": "Add it in Settings."}

    monkeypatch.setattr(connect, "request_connection_setup_approval", approve)
    monkeypatch.setattr(connect, "run_connection_setup", start)

    result = await connect.connect_external_catalog_server("https://mcp.example.com/mcp", "Example")

    assert result["result"]["status"] == "needs_manual_token"
    assert "connect_with_token" in result["result"]["message"]
    assert "Settings" not in result["result"]["message"]
