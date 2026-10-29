"""The core agent's connect_server action validates, asks for approval every time, then starts the sign-in."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from api.core.models.preferences import ExecutionApprovalMode, ToolExecutionSettings
from api.services.agent_processing.tools.external_services.external_catalog import connect as connect_module
from api.services.agent_processing.tools.external_services.external_catalog.connect import (
    connect_external_catalog_server,
)
from api.services.agent_processing.tools.safety.execution_approval_service import ExecutionApprovalService


class _RecordingApprovalService:
    instances: list["_RecordingApprovalService"] = []
    approve = True

    def __init__(self, websocket_manager=None):
        self.websocket_manager = websocket_manager
        self.requests: list[tuple[str, dict]] = []
        _RecordingApprovalService.instances.append(self)

    async def request_approval(self, command, context=None):
        self.requests.append((command, dict(context or {})))
        return (_RecordingApprovalService.approve, False, "exact")


@pytest.fixture
def approvals(monkeypatch):
    _RecordingApprovalService.instances = []
    _RecordingApprovalService.approve = True
    monkeypatch.setattr(
        "api.services.agent_processing.tools.safety.execution_approval_service.ExecutionApprovalService",
        _RecordingApprovalService,
    )
    return _RecordingApprovalService


@pytest.fixture
def started(monkeypatch):
    calls = []

    async def fake_run(plan):
        calls.append(plan)
        return {"status": "sign_in_started", "browser_opened": True, "message": "Finish signing in."}

    monkeypatch.setattr(connect_module, "run_connection_setup", fake_run)
    monkeypatch.setattr(
        "api.core.preferences.preferences_io.load_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[])),
    )
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, "", "   "])
async def test_a_missing_address_is_refused_without_asking_the_user(bad, approvals, started) -> None:
    result = await connect_external_catalog_server(bad)

    assert result["ok"] is False
    assert result["error"]["kind"] == "invalid_arguments"
    assert approvals.instances == []
    assert started == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    ["http://example.com/mcp", "https://localhost/mcp", "https://192.168.1.5/mcp", "https://user:pw@example.com/mcp", "ftp://example.com"],
)
async def test_unsafe_addresses_never_reach_the_user_or_the_runner(bad, approvals, started) -> None:
    result = await connect_external_catalog_server(bad)

    assert result["ok"] is False
    assert result["error"]["kind"] == "invalid_arguments"
    assert approvals.instances == []
    assert started == []


@pytest.mark.asyncio
async def test_denial_stops_before_any_sign_in_starts(approvals, started) -> None:
    approvals.approve = False

    result = await connect_external_catalog_server("https://mcp.notion.com/mcp", "Notion")

    assert result["ok"] is False
    assert result["error"]["kind"] == "permission_denied"
    assert started == []


@pytest.mark.asyncio
async def test_approval_names_the_exact_address_and_cannot_be_skipped_or_remembered(approvals, started) -> None:
    result = await connect_external_catalog_server("https://mcp.notion.com/mcp", "Notion")

    assert result == {
        "ok": True,
        "result": {"status": "sign_in_started", "browser_opened": True, "message": "Finish signing in."},
    }
    assert len(started) == 1
    assert started[0].server_url == "https://mcp.notion.com/mcp"
    command, context = approvals.instances[0].requests[0]
    assert "https://mcp.notion.com/mcp" in command
    assert context["require_explicit_approval"] is True
    assert context["execution_type"] == "mcp_connection_setup"
    assert "https://mcp.notion.com/mcp" in context["purpose"]
    assert "never sees your password" in context["purpose"]


@pytest.mark.asyncio
async def test_a_server_that_is_already_connected_is_reported_not_restarted(monkeypatch, approvals) -> None:
    record = SimpleNamespace(id="n1", server_url="https://mcp.notion.com/mcp", friendly_name="Notion")
    monkeypatch.setattr(
        "api.core.preferences.preferences_io.load_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[record])),
    )

    result = await connect_external_catalog_server("https://mcp.notion.com/mcp")

    assert result["ok"] is True
    assert result["result"]["status"] == "already_connected"
    assert result["result"]["connection_id"] == "n1"
    assert approvals.instances == []


@pytest.mark.asyncio
async def test_a_runner_failure_points_to_settings(monkeypatch, approvals, started) -> None:
    from api.services.mcp_connectors.connection_setup_plan import ConnectionSetupError

    async def failing(plan):
        raise ConnectionSetupError("The service rejected the request.")

    monkeypatch.setattr(connect_module, "run_connection_setup", failing)

    result = await connect_external_catalog_server("https://mcp.notion.com/mcp")

    assert result["ok"] is False
    assert result["error"]["kind"] == "connection_setup_failed"
    assert "Settings" in result["error"]["user_action_required"]


@pytest.mark.asyncio
async def test_the_catalog_tool_exposes_the_action_end_to_end(monkeypatch, approvals, started) -> None:
    from api.services.agent_processing.tools.external_services.external_catalog_tool import (
        create_external_catalog_tool,
    )

    tool = create_external_catalog_tool()
    raw = await tool.coroutine(action="connect_server", server_url="https://mcp.notion.com/mcp", friendly_name="Notion")

    assert json.loads(raw)["result"]["status"] == "sign_in_started"
    assert "connect_server" in tool.description


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings",
    [
        ToolExecutionSettings(approval_mode=ExecutionApprovalMode.ALWAYS_APPROVE),
        ToolExecutionSettings(approval_mode=ExecutionApprovalMode.WHITELIST_ONLY, auto_approve_read_only=True),
    ],
)
async def test_always_approve_and_read_only_auto_approval_do_not_skip_the_explicit_flag(monkeypatch, settings) -> None:
    monkeypatch.setattr(
        "api.services.agent_processing.tools.safety.approval_override.load_preferences",
        lambda: SimpleNamespace(tool_execution=settings),
    )
    service = ExecutionApprovalService()

    flagged = await service.evaluate_command("ls", {"require_explicit_approval": True})
    unflagged = await service.evaluate_command("ls", {})

    assert flagged.needs_approval is True
    assert unflagged.needs_approval is False
