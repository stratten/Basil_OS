"""Agent tools cannot reach Basil's runtime credentials, and cannot skip command approval."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from api.core.models.preferences import ExecutionApprovalMode, ToolExecutionSettings
from api.core.security.protected_runtime_paths import (
    PROTECTED_RUNTIME_REFUSAL,
    is_protected_runtime_path,
    references_protected_runtime_path,
)
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.schema_generation import (
    ShellExecuteCommandArgs,
)
from api.services.agent_processing.lifecycle.execution_graph.service_tools import create_service_tools
from api.services.agent_processing.service_capabilities.service_capability_analyzer import (
    ServiceCapabilityAnalyzer,
)
from api.services.agent_processing.service_capabilities.service_execution_engine import ServiceExecutionEngine
from api.services.agent_processing.tools.direct_application_interactions.applescript_automation.generic_applescript_service import (
    GenericAppleScriptService,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_interact_tool import (
    _browser_interact_impl,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.file_system_service import (
    FileSystemService,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval.file_retrieval_service import (
    FileRetrievalService,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_service import ShellService
from api.services.agent_processing.tools.safety import approval_override
from api.services.agent_processing.tools.safety.execution_approval_service import ExecutionApprovalService
from api.services.agent_processing.tools.safety.models import ExecutionApprovalOutcome

CREDENTIAL_PAYLOAD = '{"version": 1, "host_token": "secret-host", "webview_token": "secret-webview"}'


@pytest.fixture
def credential_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    runtime_directory = tmp_path / ".basil" / "runtime"
    runtime_directory.mkdir(parents=True)
    path = runtime_directory / "backend_credentials.json"
    path.write_text(CREDENTIAL_PAYLOAD, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "text",
    [
        "cat ~/.basil/runtime/backend_credentials.json",
        "cat ~/.basil/'runtime'/token",
        'jq -r .host_token "$HOME/.basil/runtime/backend_credentials.json"',
        "type C:\\Users\\me\\.basil\\runtime\\backend_credentials.json",
        "cat ~/.basil//runtime/x",
        "cat ~/.basil/./runtime/x",
        "cat BACKEND_CREDENTIALS.JSON",
    ],
)
def test_references_to_the_runtime_directory_are_detected(text: str) -> None:
    assert references_protected_runtime_path(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "ls ~/.basil/models",
        "cat runtime.txt",
        "rg backend_credentials backend/src",
        "cat backend/src/api/core/security/backend_credentials.py",
        "git status",
        "",
        None,
    ],
)
def test_unrelated_text_is_not_detected(text: str | None) -> None:
    assert references_protected_runtime_path(text) is False


def test_protected_paths_resolve_traversal_and_symlinks(credential_file: Path, tmp_path: Path) -> None:
    runtime_directory = credential_file.parent
    link = tmp_path / "innocent"
    link.symlink_to(runtime_directory, target_is_directory=True)

    assert is_protected_runtime_path(runtime_directory)
    assert is_protected_runtime_path(credential_file)
    assert is_protected_runtime_path("~/.basil/runtime/backend_credentials.json")
    assert is_protected_runtime_path(str(tmp_path / ".basil" / "models" / ".." / "runtime" / "backend_credentials.json"))
    assert is_protected_runtime_path(str(link / "backend_credentials.json"))
    assert not is_protected_runtime_path(str(tmp_path / ".basil" / "models" / "model.bin"))
    assert not is_protected_runtime_path(str(tmp_path / ".basil" / "runtime-other" / "file.txt"))


def test_command_evaluation_blocks_even_when_every_setting_is_permissive(
    credential_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    permissive = ToolExecutionSettings(
        approval_mode=ExecutionApprovalMode.ALWAYS_APPROVE,
        block_dangerous_patterns=False,
        safe_execution_mode=False,
    )
    monkeypatch.setattr(approval_override, "resolve_tool_execution_settings", lambda context=None: permissive)
    service = ExecutionApprovalService()

    blocked = asyncio.run(service.evaluate_command(f"cat {credential_file}"))
    allowed = asyncio.run(service.evaluate_command("echo hello"))

    assert blocked.is_blocked is True
    assert blocked.block_reason == PROTECTED_RUNTIME_REFUSAL
    assert "backend_credentials" not in blocked.reason
    assert allowed.is_blocked is False
    assert allowed.needs_approval is False


@pytest.mark.parametrize(
    "call",
    [
        {"command": "cat", "args": ["~/.basil/runtime/backend_credentials.json"]},
        {"command": "ls", "cwd": "RUNTIME_DIRECTORY"},
        {"command": "printenv", "env_overrides": {"TARGET": "~/.basil/runtime/backend_credentials.json"}},
    ],
    ids=["command-text", "cwd", "env-override"],
)
def test_shell_refuses_protected_targets_even_for_internal_callers(credential_file: Path, call: dict) -> None:
    arguments = dict(call)
    if arguments.get("cwd") == "RUNTIME_DIRECTORY":
        arguments["cwd"] = str(credential_file.parent)

    result = asyncio.run(ShellService().execute_command(skip_approval_check=True, timeout_s=5, **arguments))

    assert result["success"] is False
    assert result["stderr"] == PROTECTED_RUNTIME_REFUSAL
    assert result["stdout"] == ""
    assert "secret-host" not in json.dumps(result)


def test_applescript_refuses_protected_targets_before_running(credential_file: Path) -> None:
    script = f'do shell script "cat {credential_file}"'

    result = asyncio.run(GenericAppleScriptService().execute_applescript(script, skip_approval_check=True))

    assert result.success is False
    assert result.error == PROTECTED_RUNTIME_REFUSAL
    assert result.output == ""


def test_direct_file_reads_return_the_generic_failure(credential_file: Path) -> None:
    file_system = FileSystemService()

    content = asyncio.run(FileRetrievalService().read_file_content(str(credential_file)))
    prepared = asyncio.run(file_system.prepare_file_by_path(str(credential_file)))
    fetched = asyncio.run(file_system.get_file_content(str(credential_file), "utf8_text"))

    assert content is None
    assert prepared["success"] is False
    assert fetched["success"] is False
    assert "secret-host" not in json.dumps(prepared) + json.dumps(fetched)


def test_direct_file_writes_are_refused_and_leave_the_file_unchanged(credential_file: Path, tmp_path: Path) -> None:
    result = asyncio.run(
        FileSystemService(write_roots=[tmp_path]).write_text_file(
            path=str(credential_file),
            content="{}",
            mode="overwrite",
        )
    )

    assert result["success"] is False
    assert result["error_type"] == "policy_blocked"
    assert result["error"] == PROTECTED_RUNTIME_REFUSAL
    assert credential_file.read_text(encoding="utf-8") == CREDENTIAL_PAYLOAD


def test_browser_navigation_to_the_runtime_directory_is_refused(credential_file: Path) -> None:
    result = json.loads(
        asyncio.run(
            _browser_interact_impl(browser="Safari", action="navigate", selector=f"file://{credential_file}")
        )
    )

    assert result == {"success": False, "action": "navigate", "error": PROTECTED_RUNTIME_REFUSAL}


def test_agent_shell_schema_no_longer_offers_skip_approval_check() -> None:
    method = ShellService().get_service_capabilities()["methods"]["execute_command"]

    assert "skip_approval_check" not in ShellExecuteCommandArgs.model_fields
    assert "skip_approval_check" not in method["parameters"]
    assert "skip_approval_check" not in method["signature"]


def test_execution_engine_strips_skip_approval_check() -> None:
    class RecordingService:
        def __init__(self) -> None:
            self.received: list[bool] = []

        async def run(self, skip_approval_check: bool = False) -> dict:
            self.received.append(skip_approval_check)
            return {"ok": True}

    service = RecordingService()
    engine = ServiceExecutionEngine()
    engine.register_service("recording_service", service)

    asyncio.run(engine.execute_service_method("recording_service", "run", {"skip_approval_check": True}))

    assert service.received == [False]


def test_agent_shell_tool_cannot_skip_approval() -> None:
    class DenyingApprovalService:
        def __init__(self) -> None:
            self.commands: list[str] = []

        async def request_approval_with_outcome(self, command, context=None):
            self.commands.append(command)
            return ExecutionApprovalOutcome(approved=False, status="user_denied", reason="Denied by test fixture.")

    shell_service = ShellService()
    approvals = DenyingApprovalService()
    shell_service._approval_service = approvals
    analyzer = ServiceCapabilityAnalyzer(shell_service=shell_service)
    services = analyzer.discover_available_services()
    engine = ServiceExecutionEngine(analyzer)
    engine.register_service("shell_service", shell_service)
    tools = asyncio.run(create_service_tools(service_execution_engine=engine, capability_analyzer=analyzer, services=services))
    tool = next(tool for tool in tools.tools if tool.name == "shell_service_execute_command")

    payload = json.loads(asyncio.run(tool.ainvoke({
        "command": "bash",
        "args": ["-lc", "echo should-not-run"],
        "timeout_s": 5,
        "skip_approval_check": True,
    })))

    result = payload.get("result") or {}
    assert approvals.commands, "the approval service must be consulted"
    assert result.get("approval_denied") is True
    assert "should-not-run" not in result.get("stdout", "")
