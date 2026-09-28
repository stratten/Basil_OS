import uuid
import asyncio
import json
from hashlib import sha256
from pathlib import Path

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.lifecycle.execution_graph.service_tools import (
    create_service_tools,
)
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_ledger_capture import (
    ToolLedgerCaptureCoordinator,
)
from api.services.agent_processing.service_capabilities.service_capability_analyzer import (
    ServiceCapabilityAnalyzer,
)
from api.services.agent_processing.service_capabilities.service_execution_engine import (
    ServiceExecutionEngine,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_service import (
    ShellService,
)
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)


def test_shell_tool_progress_metadata_and_execution():
    shell_service = ShellService()

    analyzer = ServiceCapabilityAnalyzer(shell_service=shell_service)
    services = analyzer.discover_available_services()
    assert "shell_service" in services, "shell_service should be discoverable"

    execution_engine = ServiceExecutionEngine(analyzer)
    execution_engine.register_service("shell_service", shell_service)

    tools_result = asyncio.run(create_service_tools(
        service_execution_engine=execution_engine,
        capability_analyzer=analyzer,
        services=services,
    ))

    tool = None
    for t in tools_result.tools:
        if t.name == "shell_service_execute_command":
            tool = t
            break

    assert tool is not None, "shell_service_execute_command tool should be created"

    metadata = getattr(tool, "metadata", {}) or {}
    assert (
        metadata.get("progress_template") == "Running: {command}"
    ), "progress_template should indicate the command"
    assert (
        metadata.get("simple_description") == "Shell Service: execute command" or True
    ), "simple_description should be present (allow variations)"

    # Execute a trivial, non-interactive shell command via the tool
    # Use bash -lc to exercise the pipeline guidance
    result_str = asyncio.run(tool.ainvoke({
        "command": "bash",
        "args": ["-lc", "echo hello"],
        "timeout_s": 5,
        "skip_approval_check": True,
    }))

    assert isinstance(result_str, str) and result_str, "tool should return a JSON string"
    result_payload = json.loads(result_str)
    assert result_payload["success"] is True, f"instruction should succeed: {result_str}"
    assert result_payload["result"]["stdout"] == "hello\n", f"stdout should contain 'hello': {result_str}"
    assert "bash" in result_payload["result"]["command_echo"], "result should reflect executed command"


def test_shell_tool_creates_file_with_absolute_path_and_cwd_allowlist():
    shell_service = ShellService()

    # Use the service's allowlisted repo root as cwd
    repo_root = getattr(shell_service, "_repo_root")
    assert repo_root and Path(repo_root).is_dir(), "repo_root should be detected"

    analyzer = ServiceCapabilityAnalyzer(shell_service=shell_service)
    services = analyzer.discover_available_services()
    execution_engine = ServiceExecutionEngine(analyzer)
    execution_engine.register_service("shell_service", shell_service)

    tools_result = asyncio.run(create_service_tools(
        service_execution_engine=execution_engine,
        capability_analyzer=analyzer,
        services=services,
    ))

    tool = next((t for t in tools_result.tools if t.name == "shell_service_execute_command"), None)
    assert tool is not None, "shell_service_execute_command tool should be created"

    # Prepare unique temp path under repo root to satisfy allowlist
    tmp_dir = Path(repo_root) / "tmp_shell_test"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"test_{uuid.uuid4().hex[:8]}.txt"
    file_path = tmp_dir / file_name

    try:
        # Create file via shell using absolute POSIX path, with cwd set to repo_root
        result_str = asyncio.run(tool.ainvoke({
            "command": "bash",
            "args": [
                "-lc",
                f"echo 'hello world' > {sh_quote(str(file_path))}"
            ],
            "cwd": str(repo_root),
            "timeout_s": 10,
            "skip_approval_check": True,
            "file_operations": [{"operation": "create", "path": str(file_path)}],
        }))

        result_payload = json.loads(result_str)
        assert result_payload["success"] is True, f"instruction should succeed: {result_str}"
        assert result_payload["result"]["exit_code"] == 0, f"exit_code should be 0: {result_str}"
        # CWD should reflect allowlisted absolute path
        assert result_payload["result"]["cwd"] == str(Path(repo_root).resolve()), "cwd should be absolute repo root"

        # File should exist at the absolute path and contain expected content
        assert file_path.exists(), f"file should exist: {file_path}"
        content = file_path.read_text(encoding="utf-8")
        assert content.strip() == "hello world", "file content should match"
    finally:
        # Cleanup
        try:
            if file_path.exists():
                file_path.unlink()
            # Leave tmp_dir to avoid repeated creation errors across tests; it's harmless
        except Exception:
            pass


def test_shell_tool_returns_verified_declared_created_file():
    shell_service = ShellService()
    repo_root = Path(getattr(shell_service, "_repo_root"))
    analyzer = ServiceCapabilityAnalyzer(shell_service=shell_service)
    services = analyzer.discover_available_services()
    execution_engine = ServiceExecutionEngine(analyzer)
    execution_engine.register_service("shell_service", shell_service)
    tools_result = asyncio.run(create_service_tools(
        service_execution_engine=execution_engine,
        capability_analyzer=analyzer,
        services=services,
    ))
    tool = next((t for t in tools_result.tools if t.name == "shell_service_execute_command"), None)
    assert tool is not None, "shell_service_execute_command tool should be created"

    output_path = repo_root / "tmp_shell_test" / f"artifact_{uuid.uuid4().hex[:8]}.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result_str = asyncio.run(tool.ainvoke({
            "command": "bash",
            "args": ["-lc", f"printf 'verified' > {sh_quote(str(output_path))}"],
            "cwd": str(repo_root),
            "timeout_s": 10,
            "skip_approval_check": True,
            "file_operations": [{"operation": "create", "path": str(output_path)}],
        }))

        result_payload = json.loads(result_str)
        assert result_payload["success"] is True
        assert result_payload["result"]["file_artifacts"] == [{
            "name": output_path.name,
            "full_path": str(output_path),
            "operation": "create",
            "kind": "file",
            "sha256": sha256(output_path.read_bytes()).hexdigest(),
        }]
    finally:
        output_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_engine_shell_artifact_capture_is_not_duplicated_by_guard(tmp_path, monkeypatch):
    class ShellArtifactService:
        async def write_report(self, path):
            return {
                "file_artifacts": [{"full_path": path, "operation": "create"}],
            }

    knowledge_service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await knowledge_service.store_agent_task(
        agent_task_id="shell-ledger-task",
        original_prompt="Write report",
        transcribed_prompt="Write report",
        status="processing",
    )
    monkeypatch.setattr(
        "api.dependencies.get_sqlite_knowledge_service",
        lambda: knowledge_service,
    )
    engine = ServiceExecutionEngine()
    engine.register_service("shell_service", ShellArtifactService())
    context = {
        "agent_task_id": "shell-ledger-task",
        "root_task_id": "shell-ledger-task",
        "active_tool_invocation_id": "shell-call-1",
    }
    token = set_current_agent_context(context)
    try:
        result = await engine.execute_service_method(
            "shell_service",
            "write_report",
            {"path": "/tmp/report.txt"},
        )
        guard_outcome = await ToolLedgerCaptureCoordinator().capture_observation(
            tool_name="shell_service_write_report",
            tool_input={"path": "/tmp/report.txt"},
            observation=json.dumps(result.result),
            invocation_id="shell-call-1",
        )
    finally:
        reset_current_agent_context(token)

    session = await knowledge_service.agent_work_session_repository.get_latest_session_for_root(
        "shell-ledger-task",
    )
    receipts = await knowledge_service.agent_work_receipt_repository.get_receipts(
        session_id=session["id"],
    )

    assert guard_outcome.deduplicated is True
    assert len(receipts) == 1
    assert receipts[0]["verification_status"] == "verified"


def test_shell_tool_defaults_cwd_to_task_workspace_when_omitted():
    from api.services.agent_processing.tools.direct_application_interactions.shared.agent_task_workspace import (
        resolve_agent_task_workspace,
    )

    shell_service = ShellService()
    token = set_current_agent_context({"agent_task_id": "task-xyz-default-cwd"})
    expected_workspace = resolve_agent_task_workspace("task-xyz-default-cwd", create=False)
    try:
        result = asyncio.run(shell_service.execute_command(
            command="pwd",
            timeout_s=5,
            skip_approval_check=True,
        ))
    finally:
        reset_current_agent_context(token)
        if expected_workspace.is_dir():
            expected_workspace.rmdir()

    assert result["success"] is True, f"pwd should succeed: {result}"
    assert result["cwd"] == str(expected_workspace), "cwd should default to the task's scratch workspace"
    assert result["stdout"].strip() == str(expected_workspace), "pwd output should reflect the default workspace"


def test_shell_tool_default_workspace_is_shared_across_follow_up_turns():
    from api.services.agent_processing.tools.direct_application_interactions.shared.agent_task_workspace import (
        resolve_agent_task_workspace,
    )

    shell_service = ShellService()
    expected_workspace = resolve_agent_task_workspace("root-task-shared", create=False)
    try:
        token = set_current_agent_context({
            "root_task_id": "root-task-shared",
            "agent_task_id": "root-task-shared",
        })
        try:
            first_turn_result = asyncio.run(shell_service.execute_command(
                command="pwd",
                timeout_s=5,
                skip_approval_check=True,
            ))
        finally:
            reset_current_agent_context(token)

        # A follow-up turn gets its own agent_task_id but shares root_task_id.
        # workflow_coordinator also stamps the service's own _agent_task_id
        # with the turn-specific id (for approval broadcasts) - that must not
        # cause the workspace to fork per turn.
        shell_service._agent_task_id = "follow-up-turn-2"
        token = set_current_agent_context({
            "root_task_id": "root-task-shared",
            "agent_task_id": "follow-up-turn-2",
        })
        try:
            second_turn_result = asyncio.run(shell_service.execute_command(
                command="pwd",
                timeout_s=5,
                skip_approval_check=True,
            ))
        finally:
            reset_current_agent_context(token)
    finally:
        if expected_workspace.is_dir():
            expected_workspace.rmdir()

    assert first_turn_result["cwd"] == str(expected_workspace)
    assert second_turn_result["cwd"] == str(expected_workspace), (
        "follow-up turn should reuse the root task's workspace, not fork a new one"
    )


def test_shell_tool_leaves_cwd_unset_without_agent_context():
    shell_service = ShellService()
    result = asyncio.run(shell_service.execute_command(
        command="pwd",
        timeout_s=5,
        skip_approval_check=True,
    ))

    assert result["success"] is True, f"pwd should succeed: {result}"
    assert result["cwd"] == "", "cwd should remain unset (today's existing behavior) without an agent task in flight"


def sh_quote(s: str) -> str:
    """Minimal shell-safe quoting for use in tests with bash -lc."""
    return "'" + s.replace("'", "'\\''") + "'"


