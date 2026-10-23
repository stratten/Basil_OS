import asyncio
from types import SimpleNamespace

import pytest

from api.core.models.preferences import ToolExecutionSettings
from api.services.agent_processing.lifecycle.execution_graph.agent_progress_system import LiveProgressCallbackHandler
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.models import BaseModel
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_execution import create_tool_function
from api.services.agent_processing.lifecycle.execution_graph.tool_run_watchdog import get_tool_run_registry
from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import WorkflowCoordinator
from api.services.agent_processing.service_capabilities.service_execution_engine import ExecutionResult
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.file_system_service import FileSystemService
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_execution_result import (
    build_approval_failure_result,
)
from api.services.agent_processing.tools.safety.models import (
    ExecutionApprovalDecision,
    ExecutionApprovalOutcome,
)
from api.services.agent_processing.tools.safety.risk_assessment import RiskAssessor


class EmptyInput(BaseModel):
    pass


class DummyNotifier:
    def __init__(self):
        self.added = []
        self.updated = []
        self.progress = []
        self.details = []

    async def send_dynamic_step_added(self, **kwargs):
        self.added.append(kwargs)
        return "step_1"

    async def send_dynamic_step_updated(self, **kwargs):
        self.updated.append(kwargs)

    async def send_agent_progress_update(self, **kwargs):
        self.progress.append(kwargs)

    async def send_step_detail_update(self, **kwargs):
        self.details.append(kwargs)


class FakeExecutionEngine:
    async def execute_service_method(self, service_name, method_name, parameters):
        return ExecutionResult(
            success=True,
            result={"ok": True},
            service=service_name,
            method=method_name,
            parameters_used=parameters,
            execution_time=0.01,
        )


@pytest.mark.asyncio
async def test_progress_callback_closes_completed_tool_run():
    registry = get_tool_run_registry()
    registry.clear_agent_task("task-watchdog-complete")
    notifier = DummyNotifier()
    handler = LiveProgressCallbackHandler(notifier=notifier, todo_id="task-watchdog-complete")

    await handler.on_tool_start({"name": "shell_service_execute_command"}, run_id="run-1", inputs={"command": "echo"})
    assert registry.get("run-1") is not None

    await handler.on_tool_end(output={"success": True}, run_id="run-1", name="shell_service_execute_command")

    assert registry.get("run-1") is None
    assert notifier.updated[-1]["status"] == "completed"


@pytest.mark.asyncio
async def test_progress_callback_stops_tool_runs_cut_off_by_cancellation():
    registry = get_tool_run_registry()
    registry.clear_agent_task("task-watchdog-canceled")
    notifier = DummyNotifier()
    handler = LiveProgressCallbackHandler(notifier=notifier, todo_id="task-watchdog-canceled")

    await handler.on_tool_start({"name": "shell_service_execute_command"}, run_id="run-canceled", inputs={"command": "echo"})
    registry.get("run-canceled").mark("approval_waiting", "approval_requested")
    heartbeat = handler._heartbeat_tasks_by_run["run-canceled"]

    handler.stop_active_tool_runs()
    await asyncio.wait({heartbeat}, timeout=1)

    assert heartbeat.done()
    assert registry.get("run-canceled") is None
    assert handler._heartbeat_tasks_by_run == {}
    assert handler._step_ids_by_run == {}


def test_watchdog_reports_approval_waiting_and_returned_stale():
    registry = get_tool_run_registry()
    registry.clear_agent_task("task-watchdog-stale")
    run = registry.register(
        run_id="run-stale",
        agent_task_id="task-watchdog-stale",
        step_id="step-stale",
        tool_name="shell_service_execute_command",
        description="Running shell command",
    )

    run.mark("approval_waiting", "approval_requested")
    assert registry.assess("run-stale").status == "approval_waiting"

    run.mark("returned", "tool_returned_to_langchain")
    run.last_progress_at_monotonic -= 16
    assessment = registry.assess("run-stale")
    assert assessment.status == "stale"
    assert assessment.stale_reason == "tool_returned_without_callback"
    registry.discard("run-stale")


def test_dangerous_patterns_do_not_match_filename_substrings():
    assessor = RiskAssessor()
    settings = ToolExecutionSettings(dangerous_patterns=["format", "mkfs", "dd if=", "sudo rm"])

    blocked, reason = assessor.check_dangerous_patterns("mv 'MD BCBA Information.csv' '/tmp/Information.csv'", settings)
    assert blocked is False
    assert reason is None

    assert assessor.check_dangerous_patterns("format /dev/disk4", settings)[0] is True
    assert assessor.check_dangerous_patterns("mkfs /dev/disk4", settings)[0] is True
    assert assessor.check_dangerous_patterns("dd if=/dev/zero of=/dev/disk4", settings)[0] is True
    assert assessor.check_dangerous_patterns("sudo rm /tmp/file", settings)[0] is True


def test_shell_policy_block_result_is_not_user_denial():
    outcome = ExecutionApprovalOutcome(
        approved=False,
        status="policy_blocked",
        reason="Command contains dangerous pattern: format",
        decision=ExecutionApprovalDecision(
            needs_approval=False,
            reason="Command contains dangerous pattern: format",
            risk_level="critical",
            is_blocked=True,
            block_reason="Command contains dangerous pattern: format",
        ),
    )

    result = build_approval_failure_result(
        cwd="/tmp",
        command_echo="mv 'Information.csv' '/tmp/Information.csv'",
        outcome=outcome,
    )

    assert result["approval_blocked"] is True
    assert result["approval_denied"] is False
    assert result["approval_status"] == "policy_blocked"
    assert "blocked by safety policy" in result["stderr"]


@pytest.mark.asyncio
async def test_tool_wrapper_records_returned_state_without_callback():
    registry = get_tool_run_registry()
    registry.clear_agent_task("task-wrapper")
    registry.register(
        run_id="wrapper-run",
        agent_task_id="task-wrapper",
        step_id="step-wrapper",
        tool_name="fake_service_do_work",
        description="Doing work",
    )
    token = set_current_agent_context({"agent_task_id": "task-wrapper"})
    try:
        factory = SimpleNamespace(
            service_execution_engine=FakeExecutionEngine(),
            max_tool_output_chars=20_000,
            max_context_tokens=200_000,
            tool_error_log=[],
        )
        tool = create_tool_function(factory, "fake_service_do_work", "Do work", EmptyInput, "fake_service", "do_work", {})

        output = await tool.ainvoke({})

        run = registry.get("wrapper-run")
        assert output
        assert run is not None
        assert run.status == "returned"
        assert run.progress_kind == "tool_returned_to_langchain"
    finally:
        reset_current_agent_context(token)
        registry.discard("wrapper-run")


@pytest.mark.asyncio
async def test_reference_paths_block_ambiguous_current_document_detection():
    token = set_current_agent_context({"reference_paths": ["/Users/test/Downloads/Skillful"]})
    try:
        service = FileSystemService()
        result = await service.detect_and_prepare_current_document("organize those files")

        assert result["success"] is False
        assert result["tool_selection_error"] is True
        assert result["reference_paths"] == ["/Users/test/Downloads/Skillful"]
    finally:
        reset_current_agent_context(token)


@pytest.mark.asyncio
async def test_workflow_guard_moves_timeout_to_failure(monkeypatch):
    async def never_returns(user_agent_task, context):
        await asyncio.sleep(1)
        return {}

    async def passthrough_context(user_agent_task, context, agent_task_id=None):
        return context

    coordinator = WorkflowCoordinator()
    coordinator.session_context_service = SimpleNamespace(
        enrich_context_with_session_history=passthrough_context,
    )
    coordinator.checkpoint_workflow_service = SimpleNamespace(
        is_checkpoint_request=lambda error: False,
    )
    coordinator.status_notifier = SimpleNamespace(
        set_agent_task_id=lambda agent_task_id: None,
        set_chain_identity=lambda **kwargs: None,
        send_status_update=lambda *args, **kwargs: asyncio.sleep(0),
    )
    coordinator._service_execution_engine = None

    import api.services.agent_processing.lifecycle.runtime.workflow_coordinator as workflow_coordinator_module

    monkeypatch.setattr(workflow_coordinator_module, "execute_tool_enhanced_workflow", never_returns)

    with pytest.raises(TimeoutError):
        await coordinator._execute_with_tools(
            "do slow work",
            {"workflow_wallclock_limit_seconds": 0.01},
            "task-workflow-guard",
        )
