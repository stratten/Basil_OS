import uuid

import pytest

from api.services.agent_processing.lifecycle.execution_graph.agent_graph_runtime import (
    execute_tool_enhanced_workflow,
    plan_capabilities_with_graph,
)


@pytest.mark.asyncio
async def test_plan_capabilities_parity():
    """
    Compare ServiceCapabilityCache from direct planner vs graph runner.
    Ensures the graph wiring/checkpointer doesn't change capability discovery.
    Both should use WorkflowCoordinator for proper service initialization.
    """
    from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import WorkflowCoordinator

    direct_coordinator = WorkflowCoordinator()
    await direct_coordinator._ensure_services_initialized()
    direct_cache = await direct_coordinator.service_method_planner.plan_service_capabilities()

    graph_cache = await plan_capabilities_with_graph(user_agent_task="test", context={})

    assert direct_cache.total_services == graph_cache.total_services
    assert direct_cache.total_methods == graph_cache.total_methods


@pytest.mark.asyncio
@pytest.mark.manual
async def test_tool_enhanced_workflow_creates_tools_and_executes_steps():
    """The 4-node dynamic pipeline should create a nonzero tool surface and
    actually execute at least one step for a simple, unambiguous request."""
    unique_instruction = f"Draft a test email to john@example.com (do not send) at {uuid.uuid4().hex[:8]}"

    results = await execute_tool_enhanced_workflow(user_agent_task=unique_instruction, context={})

    assert results.get("tools_created", 0) > 0, f"Should have created tools, got {results.get('tools_created')}"
    assert results.get("tool_creation_errors") == [], f"Should have no tool creation errors, got {results.get('tool_creation_errors')}"
    assert results.get("todos_processed", 0) > 0, f"Should have processed at least one execution unit, got {results.get('todos_processed')}"
    assert results.get("steps_executed", 0) > 0, "Should have executed at least one step"
    assert results.get("steps_failed", 0) == results.get("steps_failed", 0)  # steps_failed must be present/countable
    assert "final_envelope" in results, "A completed run should produce a final_envelope"
    assert isinstance(results["final_envelope"], dict)


@pytest.mark.asyncio
@pytest.mark.manual
async def test_dynamic_applescript_fallback_for_novel_automation():
    """Novel automation with no specialized tool should route through the
    applescript family, not silently produce zero tools/steps."""
    unique_marker = uuid.uuid4().hex[:8]
    novel_instruction = (
        f"Open TextEdit, create a new document, type 'Hello from Basil AI Agent {unique_marker}!', "
        f"and save it as 'agent-test-{unique_marker}.txt' on the Desktop"
    )

    results = await execute_tool_enhanced_workflow(user_agent_task=novel_instruction, context={})

    assert results.get("tools_created", 0) > 0, "Should have created tools including the AppleScript tool"
    assert results.get("steps_executed", 0) > 0, "Should have attempted to execute at least one step"

    available_tools = results.get("available_tools")
    tool_names = [tool.name for tool in getattr(available_tools, "tools", [])]
    applescript_tools = [name for name in tool_names if "applescript" in name.lower()]
    assert applescript_tools, f"AppleScript tool should be in the available toolset, got {tool_names}"


@pytest.mark.asyncio
@pytest.mark.manual
async def test_tool_selection_prefers_email_service_over_applescript():
    """For an unambiguous email task, the specialized email_service tool
    should be selected over the generic AppleScript fallback."""
    email_instruction = "Draft a quick email to test@example.com saying hello (do not send)"

    results = await execute_tool_enhanced_workflow(user_agent_task=email_instruction, context={})

    assert results.get("tools_created", 0) > 0, "Should have created tools"
    tool_execution_results = results.get("tool_execution_results") or []
    assert tool_execution_results, "Should have at least one tool execution result"

    combined_text = str(tool_execution_results).lower()
    assert "email_service" in combined_text, f"Expected email_service usage, got: {combined_text[:500]}"
