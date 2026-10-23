import pytest
from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import WorkflowCoordinator
from api.services.agent_processing.lifecycle.runtime.workflow_results import WorkflowExecutionResult


def _successful_workflow_result(prompt: str) -> WorkflowExecutionResult:
    return WorkflowExecutionResult(
        original_prompt=prompt,
        execution_results=[{"success": True}],
        total_execution_duration=0.1,
        todos_completed=1,
        todos_failed=0,
        overall_success=True,
    )


@pytest.mark.asyncio
async def test_workflow_coordinator_executes_tool_enhanced_path(monkeypatch):
    """WorkflowCoordinator now exposes one tool-enhanced execution entry point."""
    coordinator = WorkflowCoordinator()

    async def fake_execute_with_tools(user_agent_task, context, agent_task_id):
        assert user_agent_task == "Draft a test email to john@example.com (do not send)"
        assert context == {}
        assert agent_task_id == "task-123"
        return _successful_workflow_result(user_agent_task)

    monkeypatch.setattr(coordinator, "_execute_with_tools", fake_execute_with_tools)

    result = await coordinator.execute_complete_workflow(
        user_agent_task="Draft a test email to john@example.com (do not send)",
        context={},
        agent_task_id="task-123",
    )

    assert isinstance(result, WorkflowExecutionResult)
    assert result.original_prompt.startswith("Draft a test email")
    assert result.overall_success is True
    assert result.todos_completed == 1

@pytest.mark.asyncio 
async def test_workflow_coordinator_returns_failure_result_on_execution_error():
    """Execution failures should be normalized into WorkflowExecutionResult."""
    coordinator = WorkflowCoordinator()

    async def failing_execute_with_tools(user_agent_task, context, agent_task_id):
        raise RuntimeError("boom")

    coordinator._execute_with_tools = failing_execute_with_tools

    result = await coordinator.execute_complete_workflow(
        user_agent_task="Send a test email to john@example.com",
        context={},
    )

    assert isinstance(result, WorkflowExecutionResult)
    assert result.overall_success is False
    assert result.todos_failed == 1
