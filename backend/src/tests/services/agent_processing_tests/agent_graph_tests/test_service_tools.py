"""
Tests for LangChain Tool integration with Basil services.

Tests the conversion of existing services into formal LangChain Tools with proper
schema validation and execution integration.
"""

import pytest
import asyncio
from typing import Dict, Any

# Import the service tools module
from api.services.agent_processing.lifecycle.execution_graph.service_tools import (
    ServiceToolFactory, create_service_tools, LANGCHAIN_AVAILABLE
)
from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import WorkflowCoordinator


@pytest.mark.asyncio
async def test_langchain_tools_available():
    """Test that LangChain dependencies are available."""
    assert LANGCHAIN_AVAILABLE, "LangChain tools require langchain-core to be installed"


@pytest.mark.asyncio
async def test_create_shell_service_tools():
    """Test creating LangChain Tools for shell service methods."""
    if not LANGCHAIN_AVAILABLE:
        pytest.skip("LangChain not available")
    
    # Initialize coordinator to get services
    coordinator = WorkflowCoordinator()
    await coordinator._ensure_services_initialized()
    await coordinator._ensure_llm_components_initialized()
    
    # Get service capabilities
    capability_cache = await coordinator.service_method_planner.plan_service_capabilities()
    services = capability_cache.services
    
    # Filter to the currently registered shell service.
    shell_services = {k: v for k, v in services.items() if "shell" in k.lower()}
    assert shell_services, "Shell service should be discovered"
    
    # Create tools
    factory = ServiceToolFactory(
        coordinator._service_execution_engine, 
        coordinator._service_capability_analyzer
    )
    
    result = factory.create_tools_from_services(shell_services)
    
    # Validate results
    assert len(result.tools) > 0, "Should create at least one tool"
    assert len(result.errors) == 0, f"Should have no errors, got: {result.errors}"
    
    # Check for the shell command tool.
    shell_tools = [t for t in result.tools if "shell_service_execute_command" == t.name]
    assert len(shell_tools) == 1, "Should create tool for shell_service.execute_command"
    
    shell_tool = shell_tools[0]
    assert shell_tool.description, "Tool should have description"
    assert shell_tool.args_schema, "Tool should have input schema"
    
    print(f"✅ Created {len(result.tools)} shell service tools")
    print(f"✅ Found shell command tool: {shell_tool.name}")


@pytest.mark.asyncio
async def test_create_email_service_tools():
    """Test creating LangChain Tools for email service methods."""
    if not LANGCHAIN_AVAILABLE:
        pytest.skip("LangChain not available")
    
    # Initialize coordinator to get services
    coordinator = WorkflowCoordinator()
    await coordinator._ensure_services_initialized()
    await coordinator._ensure_llm_components_initialized()
    
    # Get service capabilities
    capability_cache = await coordinator.service_method_planner.plan_service_capabilities()
    services = capability_cache.services
    
    # Filter to just email service for this test
    email_services = {k: v for k, v in services.items() if "email" in k.lower()}
    assert email_services, "Email service should be discovered"
    
    # Create tools
    result = await create_service_tools(
        coordinator._service_execution_engine,
        coordinator._service_capability_analyzer,
        email_services
    )
    
    # Validate results
    assert len(result.tools) > 0, "Should create at least one email tool"
    assert len(result.errors) == 0, f"Should have no errors, got: {result.errors}"
    
    # Check for process_email_request tool
    email_tools = [t for t in result.tools if "process_email_request" in t.name]
    assert len(email_tools) > 0, "Should create tool for process_email_request"
    
    email_tool = email_tools[0]
    assert email_tool.description, "Email tool should have description"
    assert email_tool.args_schema, "Email tool should have input schema"
    
    print(f"✅ Created {len(result.tools)} email service tools")
    print(f"✅ Found process_email_request tool: {email_tool.name}")


@pytest.mark.asyncio
async def test_tool_input_schema_validation():
    """Test that tool input schemas are properly generated."""
    if not LANGCHAIN_AVAILABLE:
        pytest.skip("LangChain not available")
    
    # Initialize coordinator
    coordinator = WorkflowCoordinator()
    await coordinator._ensure_services_initialized()
    await coordinator._ensure_llm_components_initialized()
    
    # Get shell service capabilities
    capability_cache = await coordinator.service_method_planner.plan_service_capabilities()
    services = capability_cache.services
    
    shell_services = {k: v for k, v in services.items() if "shell" in k.lower()}
    
    # Create tools
    result = await create_service_tools(
        coordinator._service_execution_engine,
        coordinator._service_capability_analyzer,
        shell_services
    )
    
    # Find shell_service.execute_command.
    shell_tools = [t for t in result.tools if "shell_service_execute_command" == t.name]
    assert len(shell_tools) == 1
    
    tool = shell_tools[0]
    schema = tool.args_schema
    
    # Validate schema has expected fields
    assert hasattr(schema, '__fields__'), "Schema should have fields"
    fields = schema.__fields__
    
    # Should have command and args parameters.
    assert 'command' in fields, "Should have command parameter"
    assert 'args' in fields, "Should have args parameter"
    
    print(f"✅ Tool schema validation passed")
    print(f"✅ Schema fields: {list(fields.keys())}")


@pytest.mark.asyncio  
async def test_convenience_function():
    """Test the convenience function for creating service tools."""
    if not LANGCHAIN_AVAILABLE:
        pytest.skip("LangChain not available")
    
    # Initialize coordinator
    coordinator = WorkflowCoordinator()
    await coordinator._ensure_services_initialized()
    await coordinator._ensure_llm_components_initialized()
    
    # Get all service capabilities
    capability_cache = await coordinator.service_method_planner.plan_service_capabilities()
    services = capability_cache.services
    
    # Create all tools using convenience function
    result = await create_service_tools(
        coordinator._service_execution_engine,
        coordinator._service_capability_analyzer,
        services
    )
    
    # Should create tools for all services
    assert len(result.tools) > 0, "Should create tools"
    assert len(result.tool_map) > 0, "Should create tool map"
    
    # Tool map should use service.method format
    tool_keys = list(result.tool_map.keys())
    assert any("." in key for key in tool_keys), "Tool map should use service.method format"
    
    print(f"✅ Created {len(result.tools)} total tools")
    print(f"✅ Tool map has {len(result.tool_map)} entries")
    print(f"✅ Sample tool keys: {tool_keys[:3]}")
