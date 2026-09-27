"""Follow-up context coverage for browser automation targets."""

from __future__ import annotations

from api.services.agent_processing.lifecycle.planning.agent_context_assembler import (
    AgentContextAssembler,
)
from api.services.agent_processing.lifecycle.runtime.session_context_service import (
    WorkflowSessionContextService,
)
from api.services.agent_processing.lifecycle.runtime.workflow_results import (
    WorkflowExecutionResult,
)


def test_followup_context_renders_browser_automation_targets():
    target = {
        "browser": "Chrome",
        "window_index": 1,
        "tab_index": 1,
        "expected_url": "https://example.com",
        "expected_title": "Example",
        "created_by_basil": True,
        "agent_task_id": "agent-123",
    }
    assembled = AgentContextAssembler().assemble(
        current_request="continue that browser task",
        context={
            "chain_context": {
                "chain_agentTasks": [
                    {
                        "sequence": 1,
                        "text": "open example",
                        "status": "completed",
                        "result": {
                            "data": {
                                "workflow_details": {
                                    "results": [
                                        {"browser_automation_target": target}
                                    ]
                                }
                            }
                        },
                    }
                ]
            }
        },
    )

    assert "Browser automation targets:" in assembled.user_input
    assert "Attempt to reuse a listed Basil browser target" in assembled.user_input
    assert "https://example.com" in assembled.user_input


def test_workflow_artifact_extraction_includes_browser_automation_targets():
    target = {
        "browser": "Chrome",
        "window_index": 1,
        "tab_index": 1,
        "expected_url": "https://example.com",
        "expected_title": "Example",
        "created_by_basil": True,
        "agent_task_id": "agent-123",
    }
    result = WorkflowExecutionResult(
        original_prompt="open example",
        execution_results=[
            {
                "success": True,
                "result": {
                    "browser_automation_target": target,
                },
            }
        ],
        total_execution_duration=1.0,
        todos_completed=1,
        todos_failed=0,
        overall_success=True,
    )

    artifacts = WorkflowSessionContextService()._extract_artifacts_from_result(result)

    assert artifacts["browser_automation_targets"] == [target]
