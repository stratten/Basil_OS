"""Tests for P5 tool blueprint warm cache and per-turn identity binding."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from api.services.agent_processing.lifecycle.execution_graph import service_tools as service_tools_module
from api.services.agent_processing.lifecycle.execution_graph.service_tools import (
    build_tool_method_blueprints,
    create_service_tools,
)
from api.services.agent_processing.lifecycle.runtime.warm_artifact_cache import (
    get_warm_artifact_cache,
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


@pytest.fixture(autouse=True)
def _clear_warm_cache():
    get_warm_artifact_cache().invalidate()
    yield
    get_warm_artifact_cache().invalidate()


@pytest.mark.asyncio
async def test_tool_blueprint_cache_hit_reuses_input_models():
    shell_service = ShellService()
    analyzer = ServiceCapabilityAnalyzer(shell_service=shell_service)
    services = analyzer.discover_available_services()
    engine = ServiceExecutionEngine(analyzer)
    engine.register_service("shell_service", shell_service)

    result1 = await create_service_tools(
        service_execution_engine=engine,
        capability_analyzer=analyzer,
        services=services,
        current_agent_task_id="task-a",
    )
    result2 = await create_service_tools(
        service_execution_engine=engine,
        capability_analyzer=analyzer,
        services=services,
        current_agent_task_id="task-b",
    )

    tool1 = next(t for t in result1.tools if t.name == "shell_service_execute_command")
    tool2 = next(t for t in result2.tools if t.name == "shell_service_execute_command")

    assert tool1.args_schema is tool2.args_schema
    assert tool1 is not tool2


@pytest.mark.asyncio
async def test_recall_tool_uses_current_agent_task_id_per_turn():
    shell_service = ShellService()
    analyzer = ServiceCapabilityAnalyzer(shell_service=shell_service)
    services = analyzer.discover_available_services()
    engine = ServiceExecutionEngine(analyzer)
    engine.register_service("shell_service", shell_service)

    result_a = await create_service_tools(
        service_execution_engine=engine,
        capability_analyzer=analyzer,
        services=services,
        current_agent_task_id="turn-a",
        current_root_task_id="root-a",
    )
    result_b = await create_service_tools(
        service_execution_engine=engine,
        capability_analyzer=analyzer,
        services=services,
        current_agent_task_id="turn-b",
        current_root_task_id="root-b",
    )

    recall_a = next(t for t in result_a.tools if "recall" in t.name)
    recall_b = next(t for t in result_b.tools if "recall" in t.name)
    assert recall_a is not recall_b


def test_build_tool_method_blueprints_is_pure():
    shell_service = ShellService()
    analyzer = ServiceCapabilityAnalyzer(shell_service=shell_service)
    services = analyzer.discover_available_services()

    blueprints_a = build_tool_method_blueprints(services)
    blueprints_b = build_tool_method_blueprints(services)

    assert blueprints_a.keys() == blueprints_b.keys()
    key = next(iter(blueprints_a))
    assert blueprints_a[key].input_model is blueprints_b[key].input_model


def test_build_tool_method_blueprints_skips_one_bad_method_without_raising(monkeypatch):
    """A single method whose description/schema generation raises must be
    skipped with a warning, not abort blueprint construction for every other
    method -- this is the pre-P5 fault-isolation contract
    (_create_tools_for_service's per-method try/except) that the cached
    blueprint builder must preserve."""
    shell_service = ShellService()
    analyzer = ServiceCapabilityAnalyzer(shell_service=shell_service)
    services = analyzer.discover_available_services()

    good_blueprints = build_tool_method_blueprints(services)
    shell_blueprint = next(
        bp for bp in good_blueprints.values() if bp.service_name == "shell_service"
    )
    bad_method_name = shell_blueprint.method_name
    real_generate_tool_description = service_tools_module.generate_tool_description

    def _flaky_generate_tool_description(service_name, method_name, *args, **kwargs):
        if service_name == "shell_service" and method_name == bad_method_name:
            raise ValueError("simulated schema generation failure")
        return real_generate_tool_description(service_name, method_name, *args, **kwargs)

    monkeypatch.setattr(
        service_tools_module, "generate_tool_description", _flaky_generate_tool_description
    )

    blueprints = build_tool_method_blueprints(services)

    assert len(blueprints) == len(good_blueprints) - 1
    assert f"shell_service.{bad_method_name}" not in blueprints


@pytest.mark.asyncio
async def test_create_service_tools_tolerates_one_bad_method(monkeypatch):
    """End-to-end: a method skipped during blueprint construction must not
    surface in ToolCreationResult.errors. A populated `errors` list makes
    _node_execute_todos_with_tools raise and abort the whole turn, so one bad
    method must never poison the rest of the tool surface."""
    shell_service = ShellService()
    analyzer = ServiceCapabilityAnalyzer(shell_service=shell_service)
    services = analyzer.discover_available_services()
    engine = ServiceExecutionEngine(analyzer)
    engine.register_service("shell_service", shell_service)

    baseline = await create_service_tools(
        service_execution_engine=engine,
        capability_analyzer=analyzer,
        services=services,
        current_agent_task_id="task-baseline",
    )
    good_blueprints = build_tool_method_blueprints(services)
    shell_blueprint = next(
        bp for bp in good_blueprints.values() if bp.service_name == "shell_service"
    )
    bad_method_name = shell_blueprint.method_name
    bad_tool_name = f"shell_service_{bad_method_name}"
    assert bad_tool_name in {t.name for t in baseline.tools}, "sanity: tool exists before the fault"

    # Force a rebuild so the patched generate_tool_description is actually
    # exercised on the next call (the blueprint cache would otherwise serve
    # the already-built, unpatched blueprints from the baseline call above).
    get_warm_artifact_cache().invalidate()

    real_generate_tool_description = service_tools_module.generate_tool_description

    def _flaky_generate_tool_description(service_name, method_name, *args, **kwargs):
        if service_name == "shell_service" and method_name == bad_method_name:
            raise ValueError("simulated schema generation failure")
        return real_generate_tool_description(service_name, method_name, *args, **kwargs)

    monkeypatch.setattr(
        service_tools_module, "generate_tool_description", _flaky_generate_tool_description
    )

    result = await create_service_tools(
        service_execution_engine=engine,
        capability_analyzer=analyzer,
        services=services,
        current_agent_task_id="task-flaky",
    )

    assert result.errors == [], f"a single bad method must not raise a tool-creation error: {result.errors}"
    assert bad_tool_name not in {t.name for t in result.tools}
    assert len(result.tools) == len(baseline.tools) - 1


@pytest.mark.asyncio
async def test_conversation_recall_tool_uses_current_conversation_id_per_turn():
    shell_service = ShellService()
    analyzer = ServiceCapabilityAnalyzer(shell_service=shell_service)
    services = analyzer.discover_available_services()
    engine = ServiceExecutionEngine(analyzer)
    engine.register_service("shell_service", shell_service)

    result_a = await create_service_tools(
        service_execution_engine=engine,
        capability_analyzer=analyzer,
        services=services,
        current_conversation_id="conversation-a",
    )
    result_b = await create_service_tools(
        service_execution_engine=engine,
        capability_analyzer=analyzer,
        services=services,
        current_conversation_id="conversation-b",
    )
    recall_a = next(tool for tool in result_a.tools if tool.name == "recall_conversations")
    recall_b = next(tool for tool in result_b.tools if tool.name == "recall_conversations")

    with patch(
        "api.services.agent_processing.tools.internal_basil_tools.recall.conversation_source."
        "ConversationRecallSource.current_thread",
        new_callable=AsyncMock,
        return_value=[],
    ) as current_thread:
        raw = await recall_a.ainvoke({})

    assert recall_a is not recall_b
    assert result_a.tool_map["recall.recall_conversations"] is recall_a
    assert json.loads(raw)["conversation_id"] == "conversation-a"
    current_thread.assert_awaited_once_with("conversation-a", 20)
