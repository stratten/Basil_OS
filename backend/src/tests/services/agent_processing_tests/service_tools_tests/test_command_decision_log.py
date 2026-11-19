"""Every command verdict is written to the desktop debug log, so a day's auto-approvals and prompts can be reviewed afterward."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.core.models.preferences import ExecutionApprovalMode, ToolExecutionSettings
from api.services.agent_processing.tools.safety import execution_approval_service as service_module
from api.services.agent_processing.tools.safety.execution_approval_service import ExecutionApprovalService


@pytest.fixture
def decisions(monkeypatch):
    lines = []

    class Recorder:
        def info(self, template, *args):
            lines.append(template % args)

    monkeypatch.setattr(service_module, "decision_logger", Recorder())
    return lines


@pytest.fixture
def read_only_settings(monkeypatch):
    stub = SimpleNamespace(
        tool_execution=ToolExecutionSettings(
            approval_mode=ExecutionApprovalMode.WHITELIST_ONLY,
            whitelisted_commands=[],
            auto_approve_read_only=True,
            safe_execution_mode=False,
        )
    )
    monkeypatch.setattr("api.services.agent_processing.tools.safety.approval_override.load_preferences", lambda: stub)


@pytest.mark.asyncio
async def test_an_auto_approved_command_is_logged_with_its_reason(decisions, read_only_settings):
    decision = await ExecutionApprovalService(websocket_manager=None).evaluate_command("ls -la /tmp")

    assert decision.needs_approval is False
    assert decisions == ["Command auto-approved (risk=low, reason=Read-only command auto-approved): ls -la /tmp"]


@pytest.mark.asyncio
async def test_a_command_that_asks_is_logged_as_asking(decisions, read_only_settings):
    decision = await ExecutionApprovalService(websocket_manager=None).evaluate_command("curl -sL https://example.com/x -o -")

    assert decision.needs_approval is True
    assert len(decisions) == 1
    assert decisions[0].startswith("Command asks (risk=")
    assert "Needs your approval because 'curl' is not on the read-only list" in decisions[0]
    assert decisions[0].endswith("curl -sL https://example.com/x -o -")


@pytest.mark.asyncio
async def test_the_card_names_the_part_of_the_command_that_made_it_ask(decisions, read_only_settings):
    decision = await ExecutionApprovalService(websocket_manager=None).evaluate_command("ls -la; mdutil -a -i off; wc -l x")

    assert decision.needs_approval is True
    assert decision.reason == "Needs your approval because 'mdutil' is not on the read-only list, and no remembered approval covers it"


@pytest.mark.asyncio
async def test_a_checksum_and_a_multi_range_sed_print_no_longer_ask(decisions, read_only_settings):
    service = ExecutionApprovalService(websocket_manager=None)

    for command in ("ls -la; md5 -r * | sort; grep -c '^## Transcript' *", "sed -n '40,78p;96,112p' notes.txt"):
        decision = await service.evaluate_command(command)
        assert decision.needs_approval is False, command


@pytest.mark.asyncio
async def test_a_connected_tool_is_logged_by_name_only_and_a_long_command_is_cut(decisions, read_only_settings):
    service = ExecutionApprovalService(websocket_manager=None)
    await service.evaluate_command('mcp:Gmail - Speakeasy:send_draft({"summary":"Dear Nelly, the private text of the email"})')
    await service.evaluate_command("echo " + "x" * 500 + " | wc -c")

    assert decisions[0].endswith(": mcp:Gmail - Speakeasy:send_draft")
    assert "private text" not in decisions[0]
    assert decisions[1].endswith("…")
    assert len(decisions[1].rsplit(": ", 1)[1]) <= service_module.MAX_LOGGED_COMMAND_CHARS + 1


@pytest.mark.asyncio
async def test_a_logging_failure_never_changes_the_verdict(monkeypatch, read_only_settings):
    class Broken:
        def info(self, *args):
            raise RuntimeError("log disk full")

    monkeypatch.setattr(service_module, "decision_logger", Broken())
    decision = await ExecutionApprovalService(websocket_manager=None).evaluate_command("ls")

    assert decision.needs_approval is False
