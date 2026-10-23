"""Tests for vision backend resolution on analyze_with_vision."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services.agent_processing.lifecycle.execution_graph import agent_graph_nodes as nodes
from api.services.agent_processing.lifecycle.execution_graph.agent_progress_system import PlanningState
from api.services.agent_processing.lifecycle.execution_graph.service_tools import ToolCreationResult
from api.services.agent_processing.service_capabilities.service_method_planner import ServiceCapabilityCache
from api.services.agent_processing.tools.vision.backend_resolver import VisionBackend


@pytest.fixture
def minimal_cache() -> ServiceCapabilityCache:
    return ServiceCapabilityCache(
        services={"stub": {"methods": {"noop": {}}}},
        method_signatures={},
        retrieval_timestamp=time.time(),
        total_services=1,
        total_methods=1,
    )


@pytest.fixture
def mock_coord() -> MagicMock:
    c = MagicMock()
    c._llm_model = MagicMock(model_name="gpt-5.1")
    c._service_execution_engine = MagicMock()
    c._websocket_manager = None
    c._ensure_services_initialized = AsyncMock()
    c._ensure_llm_components_initialized = AsyncMock()
    return c


@pytest.mark.asyncio
async def test_create_tools_skips_vision_when_profile_lacks_capability(
    mock_coord: MagicMock, minimal_cache: ServiceCapabilityCache
) -> None:
    empty_result = ToolCreationResult(tools=[], tool_map={}, errors=[], optional_warnings=[])
    with (
        patch.object(nodes, "_get_run_coordinator", return_value=mock_coord),
        patch.object(nodes, "create_service_tools", return_value=empty_result),
        patch(
            "api.services.agent_processing.tools.vision.backend_resolver.resolve_agent_vision_backend",
            return_value=VisionBackend.UNAVAILABLE,
        ),
        patch(
            "api.services.agent_processing.tools.internal_basil_tools."
            "vision_analysis_tool.create_vision_analysis_tool",
        ) as vision_factory,
    ):
        state = PlanningState(user_agent_task="x", context={}, capability_cache=minimal_cache)
        out = await nodes._node_create_tools(state)
        vision_factory.assert_not_called()
        tr = out["available_tools"]
        assert tr.errors == []
        assert "vision.analyze" not in tr.tool_map


@pytest.mark.asyncio
async def test_create_tools_adds_vision_when_capability_present(
    mock_coord: MagicMock, minimal_cache: ServiceCapabilityCache
) -> None:
    empty_result = ToolCreationResult(tools=[], tool_map={}, errors=[], optional_warnings=[])
    fake_tool = MagicMock()
    fake_tool.name = "analyze_with_vision"
    with (
        patch.object(nodes, "_get_run_coordinator", return_value=mock_coord),
        patch.object(nodes, "create_service_tools", return_value=empty_result),
        patch(
            "api.services.agent_processing.tools.vision.backend_resolver.resolve_agent_vision_backend",
            return_value=VisionBackend.NATIVE,
        ),
        patch(
            "api.services.agent_processing.tools.internal_basil_tools."
            "vision_analysis_tool.create_vision_analysis_tool",
            return_value=fake_tool,
        ) as vision_factory,
    ):
        state = PlanningState(user_agent_task="x", context={}, capability_cache=minimal_cache)
        out = await nodes._node_create_tools(state)
        vision_factory.assert_called_once()
        tr = out["available_tools"]
        assert fake_tool in tr.tools
        assert tr.tool_map.get("vision.analyze") is fake_tool
        assert tr.errors == []


@pytest.mark.asyncio
async def test_create_tools_vision_failure_is_optional_warning_not_fatal_error(
    mock_coord: MagicMock, minimal_cache: ServiceCapabilityCache
) -> None:
    empty_result = ToolCreationResult(tools=[], tool_map={}, errors=[], optional_warnings=[])
    with (
        patch.object(nodes, "_get_run_coordinator", return_value=mock_coord),
        patch.object(nodes, "create_service_tools", return_value=empty_result),
        patch(
            "api.services.agent_processing.tools.vision.backend_resolver.resolve_agent_vision_backend",
            return_value=VisionBackend.NATIVE,
        ),
        patch(
            "api.services.agent_processing.tools.internal_basil_tools."
            "vision_analysis_tool.create_vision_analysis_tool",
            side_effect=RuntimeError("vision init failed"),
        ),
    ):
        state = PlanningState(user_agent_task="x", context={}, capability_cache=minimal_cache)
        out = await nodes._node_create_tools(state)
        tr = out["available_tools"]
        assert tr.errors == []
        assert len(tr.optional_warnings) >= 1
        assert "vision" in tr.optional_warnings[0].lower()


@pytest.mark.asyncio
async def test_create_tools_passes_conversation_id_to_factory(
    mock_coord: MagicMock, minimal_cache: ServiceCapabilityCache
) -> None:
    empty_result = ToolCreationResult(tools=[], tool_map={}, errors=[], optional_warnings=[])
    captured = {}

    async def fake_create_service_tools(**kwargs):
        captured.update(kwargs)
        return empty_result

    with (
        patch.object(nodes, "_get_run_coordinator", return_value=mock_coord),
        patch.object(nodes, "create_service_tools", side_effect=fake_create_service_tools),
        patch(
            "api.services.agent_processing.tools.vision.backend_resolver.resolve_agent_vision_backend",
            return_value=VisionBackend.UNAVAILABLE,
        ),
    ):
        state = PlanningState(
            user_agent_task="x",
            context={"agent_task_id": "task-1", "conversation_id": "conversation-1"},
            capability_cache=minimal_cache,
        )
        await nodes._node_create_tools(state)

    assert captured["current_agent_task_id"] == "task-1"
    assert captured["current_conversation_id"] == "conversation-1"
