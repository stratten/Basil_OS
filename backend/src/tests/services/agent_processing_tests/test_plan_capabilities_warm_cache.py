"""Tests for P5 capability-cache integration in plan_capabilities node."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services.agent_processing.lifecycle.execution_graph import agent_graph_nodes
from api.services.agent_processing.lifecycle.runtime.warm_artifact_cache import (
    get_warm_artifact_cache,
)
from api.services.agent_processing.service_capabilities.service_method_planner import (
    ServiceCapabilityCache,
)


@pytest.fixture(autouse=True)
def _clear_warm_cache():
    get_warm_artifact_cache().invalidate()
    yield
    get_warm_artifact_cache().invalidate()


@pytest.mark.asyncio
async def test_plan_capabilities_warm_cache_hit_on_second_call():
    calls = {"n": 0}
    cache_obj = ServiceCapabilityCache(
        services={"shell_service": {"methods": {}}},
        method_signatures={},
        retrieval_timestamp=1.0,
        total_services=1,
        total_methods=0,
    )

    async def fake_plan():
        calls["n"] += 1
        return cache_obj

    coordinator = MagicMock()
    coordinator._websocket_manager = None
    coordinator._service_execution_engine = MagicMock()
    coordinator._service_execution_engine.get_registered_services.return_value = [
        "shell_service"
    ]
    coordinator._ensure_services_initialized = AsyncMock()
    coordinator.service_method_planner = MagicMock()
    coordinator.service_method_planner.plan_service_capabilities = fake_plan

    state = SimpleNamespace(
        context={"agent_task_id": "task-1", "root_task_id": "root-1"},
        capability_cache=None,
    )

    with patch.object(agent_graph_nodes, "_get_run_coordinator", return_value=coordinator):
        result1 = await agent_graph_nodes._node_plan_capabilities(state)
        result2 = await agent_graph_nodes._node_plan_capabilities(state)

    assert calls["n"] == 1
    assert result1["capability_cache"] is cache_obj
    assert result2["capability_cache"] is cache_obj


@pytest.mark.asyncio
async def test_plan_capabilities_rebuilds_when_service_set_changes():
    calls = {"n": 0}

    async def fake_plan():
        calls["n"] += 1
        return ServiceCapabilityCache(
            services={},
            method_signatures={},
            retrieval_timestamp=float(calls["n"]),
            total_services=0,
            total_methods=0,
        )

    coordinator = MagicMock()
    coordinator._websocket_manager = None
    coordinator._service_execution_engine = MagicMock()
    coordinator._ensure_services_initialized = AsyncMock()
    coordinator.service_method_planner = MagicMock()
    coordinator.service_method_planner.plan_service_capabilities = fake_plan

    state = SimpleNamespace(context={"agent_task_id": "task-1"}, capability_cache=None)

    with patch.object(agent_graph_nodes, "_get_run_coordinator", return_value=coordinator):
        coordinator._service_execution_engine.get_registered_services.return_value = ["a"]
        await agent_graph_nodes._node_plan_capabilities(state)
        coordinator._service_execution_engine.get_registered_services.return_value = [
            "a",
            "b",
        ]
        await agent_graph_nodes._node_plan_capabilities(state)

    assert calls["n"] == 2
