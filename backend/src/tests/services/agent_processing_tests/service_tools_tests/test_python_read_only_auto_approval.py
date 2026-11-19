"""Approval-service tests for auto-approving a read-only Python one-liner."""

from __future__ import annotations

import shlex
from types import SimpleNamespace

import pytest

from api.core.config import api_settings
from api.core.models.preferences import ExecutionApprovalMode, ToolExecutionSettings
from api.services.agent_processing.tools.safety.execution_approval_service import ExecutionApprovalService

READ_SCRIPT = (
    "import json;d=json.load(open('.tool_results/r-1.txt'));"
    "[print(r['requestNumber'], r.get('status')) for r in d]"
)
WRITE_SCRIPT = "open('copy.txt', 'w').write(open('.tool_results/r-1.txt').read())"


def _settings(**overrides):
    values = dict(
        approval_mode=ExecutionApprovalMode.WHITELIST_ONLY,
        whitelisted_commands=[],
        auto_approve_read_only=True,
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
    (root / ".tool_results").mkdir(parents=True)
    (root / ".tool_results" / "r-1.txt").write_text('[{"requestNumber": "REQ-1", "status": "open"}]')
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


def _double_quoted(script):
    return '"' + script.replace("\\", "\\\\").replace('"', '\\"') + '"'


async def _evaluate(argv, context):
    return await ExecutionApprovalService(websocket_manager=None).evaluate_command(_echo(argv), context)


@pytest.mark.asyncio
async def test_a_read_only_python_one_liner_needs_no_approval(workspace, use_settings):
    argv = ["bash", "-lc", f"python3 -c {_double_quoted(READ_SCRIPT)}"]

    decision = await _evaluate(argv, _context(workspace, argv))

    assert decision.needs_approval is False
    assert decision.is_blocked is False
    assert decision.risk_level == "low"
    assert decision.reason == "Read-only Python script auto-approved"


@pytest.mark.asyncio
async def test_a_direct_python_invocation_needs_no_approval(workspace, use_settings):
    argv = ["python3", "-c", READ_SCRIPT]

    decision = await _evaluate(argv, _context(workspace, argv))

    assert decision.needs_approval is False
    assert decision.reason == "Read-only Python script auto-approved"


@pytest.mark.asyncio
async def test_a_python_script_that_writes_still_asks(workspace, use_settings):
    argv = ["bash", "-lc", f"python3 -c {_double_quoted(WRITE_SCRIPT)}"]

    decision = await _evaluate(argv, _context(workspace, argv))

    assert decision.needs_approval is True
    assert decision.reason.startswith("Needs your approval because ")


@pytest.mark.asyncio
async def test_turning_off_read_only_auto_approval_makes_python_ask_again(workspace, use_settings):
    use_settings(auto_approve_read_only=False)
    argv = ["python3", "-c", READ_SCRIPT]

    decision = await _evaluate(argv, _context(workspace, argv))

    assert decision.needs_approval is True


@pytest.mark.asyncio
async def test_safe_execution_mode_still_prompts_for_a_read_only_python_script(workspace, use_settings):
    use_settings(safe_execution_mode=True)
    argv = ["python3", "-c", READ_SCRIPT]

    decision = await _evaluate(argv, _context(workspace, argv))

    assert decision.needs_approval is True


@pytest.mark.asyncio
async def test_a_shadowing_module_in_the_working_directory_makes_python_ask(workspace, use_settings):
    (workspace / "json.py").write_text("raise SystemExit")
    argv = ["python3", "-c", READ_SCRIPT]

    decision = await _evaluate(argv, _context(workspace, argv))

    assert decision.needs_approval is True


@pytest.mark.asyncio
async def test_the_isolated_flag_lets_a_shadowed_directory_through(workspace, use_settings):
    (workspace / "json.py").write_text("raise SystemExit")
    argv = ["python3", "-I", "-c", READ_SCRIPT]

    decision = await _evaluate(argv, _context(workspace, argv))

    assert decision.needs_approval is False


@pytest.mark.asyncio
async def test_environment_overrides_make_python_ask(workspace, use_settings):
    argv = ["python3", "-c", READ_SCRIPT]

    decision = await _evaluate(argv, _context(workspace, argv, env=True))

    assert decision.needs_approval is True


@pytest.mark.asyncio
async def test_without_a_workspace_scope_python_asks_unless_isolated(workspace, use_settings):
    plain = ["python3", "-c", READ_SCRIPT]
    isolated = ["python3", "-I", "-c", READ_SCRIPT]
    service = ExecutionApprovalService(websocket_manager=None)

    assert (await service.evaluate_command(_echo(plain), {"source": "shell_service"})).needs_approval is True
    assert (await service.evaluate_command(_echo(isolated), {"source": "shell_service"})).needs_approval is False


@pytest.mark.asyncio
async def test_a_raw_shell_string_that_only_looks_like_python_asks(workspace, use_settings):
    command = f'python3 -c {_double_quoted(READ_SCRIPT)} > out.txt'

    decision = await ExecutionApprovalService(websocket_manager=None).evaluate_command(command, _context(workspace, ["python3"]))

    assert decision.needs_approval is True


@pytest.mark.asyncio
async def test_other_interpreters_are_unaffected(workspace, use_settings):
    argv = ["node", "-e", "console.log(1)"]

    decision = await _evaluate(argv, _context(workspace, argv))

    assert decision.needs_approval is True
    assert decision.reason == "Needs your approval because 'node' is not on the read-only list, and no remembered approval covers it"


@pytest.mark.asyncio
async def test_existing_read_only_shell_approval_is_unchanged(workspace, use_settings):
    argv = ["cat", "/etc/hosts"]

    decision = await _evaluate(argv, _context(workspace, argv))

    assert decision.needs_approval is False
    assert decision.reason == "Read-only command auto-approved"
