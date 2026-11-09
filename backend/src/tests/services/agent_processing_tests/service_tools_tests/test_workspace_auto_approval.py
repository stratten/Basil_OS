"""Approval-service and shell-tool tests for auto-approving commands inside the task workspace."""

from __future__ import annotations

import shlex
from types import SimpleNamespace

import pytest

from api.core.config import api_settings
from api.core.models.preferences import ExecutionApprovalMode, ToolExecutionSettings
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_service import ShellService
from api.services.agent_processing.tools.safety.execution_approval_service import ExecutionApprovalService
from api.services.agent_processing.tools.safety.models import ExecutionApprovalOutcome


def _settings(**overrides):
    values = dict(
        approval_mode=ExecutionApprovalMode.WHITELIST_ONLY,
        whitelisted_commands=[],
        auto_approve_read_only=False,
        safe_execution_mode=False,
    )
    values.update(overrides)
    return ToolExecutionSettings(**values)


@pytest.fixture
def use_settings(monkeypatch):
    def apply(**overrides):
        stub = SimpleNamespace(tool_execution=_settings(**overrides))
        monkeypatch.setattr(
            "api.services.agent_processing.tools.safety.approval_override.load_preferences",
            lambda: stub,
        )

    apply()
    return apply


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(api_settings.settings, "STORAGE_DIR", tmp_path)
    root = tmp_path / "agent_task_workspaces" / "task-1"
    root.mkdir(parents=True)
    (root / "a.txt").write_text("alpha\n")
    return root


def _context(workspace, argv, *, cwd=None, env=False):
    return {
        "source": "shell_service",
        "workspace_scope": {
            "argv": argv,
            "cwd": str(cwd or workspace),
            "workspace": str(workspace),
            "has_env_overrides": env,
        },
    }


def _echo(argv):
    return " ".join(shlex.quote(part) for part in argv)


async def _evaluate(argv, context):
    return await ExecutionApprovalService(websocket_manager=None).evaluate_command(_echo(argv), context)


@pytest.mark.asyncio
async def test_a_command_inside_the_workspace_needs_no_approval(workspace, use_settings):
    argv = ["cat", "a.txt"]

    decision = await _evaluate(argv, _context(workspace, argv))

    assert decision.needs_approval is False
    assert decision.is_blocked is False
    assert decision.risk_level == "low"
    assert "inside this task's workspace" in decision.reason


@pytest.mark.asyncio
async def test_a_write_inside_the_workspace_needs_no_approval(workspace, use_settings):
    argv = ["bash", "-lc", "cat a.txt | sort > sorted.txt && cp sorted.txt copy.txt"]

    decision = await _evaluate(argv, _context(workspace, argv))

    assert decision.needs_approval is False


@pytest.mark.asyncio
async def test_a_path_outside_the_workspace_falls_back_to_the_normal_rules(workspace, use_settings):
    argv = ["cat", "/etc/hosts"]

    decision = await _evaluate(argv, _context(workspace, argv))

    assert decision.needs_approval is True
    assert decision.reason == "Command not in whitelist"


@pytest.mark.asyncio
async def test_existing_read_only_auto_approval_still_applies_outside_the_workspace(workspace, use_settings):
    use_settings(auto_approve_read_only=True)
    argv = ["cat", "/etc/hosts"]

    decision = await _evaluate(argv, _context(workspace, argv))

    assert decision.needs_approval is False
    assert decision.reason == "Read-only command auto-approved"


@pytest.mark.asyncio
async def test_safe_execution_mode_still_prompts_for_everything(workspace, use_settings):
    use_settings(safe_execution_mode=True)
    argv = ["cat", "a.txt"]

    decision = await _evaluate(argv, _context(workspace, argv))

    assert decision.needs_approval is True
    assert "Safe execution mode" in decision.reason


@pytest.mark.asyncio
async def test_always_prompt_mode_still_prompts(workspace, use_settings):
    use_settings(approval_mode=ExecutionApprovalMode.ALWAYS_PROMPT)
    argv = ["cat", "a.txt"]

    decision = await _evaluate(argv, _context(workspace, argv))

    assert decision.needs_approval is True
    assert decision.reason == "Always prompt mode enabled"


@pytest.mark.asyncio
async def test_a_blocked_command_stays_blocked(workspace, use_settings):
    argv = ["rm", "-rf", "/"]

    decision = await _evaluate(argv, _context(workspace, argv))

    assert decision.is_blocked is True
    assert decision.needs_approval is False


@pytest.mark.asyncio
async def test_a_script_interpreter_still_needs_approval(workspace, use_settings):
    argv = ["python3", "script.py"]

    decision = await _evaluate(argv, _context(workspace, argv))

    assert decision.needs_approval is True


@pytest.mark.asyncio
async def test_environment_overrides_still_need_approval(workspace, use_settings):
    argv = ["cat", "a.txt"]

    decision = await _evaluate(argv, _context(workspace, argv, env=True))

    assert decision.needs_approval is True


@pytest.mark.asyncio
@pytest.mark.parametrize("context", [None, {}, {"workspace_scope": "not a dict"}, {"workspace_scope": {}}])
async def test_a_context_without_a_usable_scope_changes_nothing(context, use_settings):
    decision = await ExecutionApprovalService(websocket_manager=None).evaluate_command("cat a.txt", context)

    assert decision.needs_approval is True
    assert decision.reason == "Command not in whitelist"


class _CapturingApprovalService:
    def __init__(self):
        self.contexts = []

    async def request_approval_with_outcome(self, command, context=None):
        self.contexts.append(context)
        return ExecutionApprovalOutcome(approved=True, reason="Approved by test fixture.")


@pytest.mark.asyncio
async def test_the_shell_tool_sends_the_scope_with_the_approval_request(workspace, use_settings):
    shell = ShellService()
    shell._approval_service = _CapturingApprovalService()
    token = set_current_agent_context({"root_task_id": "task-1", "agent_task_id": "task-1"})
    try:
        await shell.execute_command("cat", ["a.txt"], purpose="Read a file")
    finally:
        reset_current_agent_context(token)

    scope = shell._approval_service.contexts[0]["workspace_scope"]
    assert scope["argv"] == ["cat", "a.txt"]
    assert scope["workspace"] == str(workspace)
    assert scope["cwd"] == str(workspace)
    assert scope["has_env_overrides"] is False


@pytest.mark.asyncio
async def test_the_shell_tool_runs_an_in_workspace_command_without_a_prompt(workspace, use_settings):
    token = set_current_agent_context({"root_task_id": "task-1", "agent_task_id": "task-1"})
    try:
        result = await ShellService().execute_command("cat", ["a.txt"], purpose="Read a file")
    finally:
        reset_current_agent_context(token)

    assert result["success"] is True
    assert "alpha" in result["stdout"]


@pytest.mark.asyncio
async def test_the_shell_tool_still_stops_for_a_path_outside_the_workspace(workspace, use_settings, tmp_path):
    elsewhere = tmp_path / "elsewhere.txt"
    elsewhere.write_text("not yours\n")
    token = set_current_agent_context({"root_task_id": "task-1", "agent_task_id": "task-1"})
    try:
        result = await ShellService().execute_command("cat", [str(elsewhere)], purpose="Read a file")
    finally:
        reset_current_agent_context(token)

    assert result["success"] is False
    assert result["error_type"] == "approval_unavailable"
    assert "not yours" not in result["stdout"]
