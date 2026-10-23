"""A resumed run must skip request analysis and skill selection but still rebuild services and tools."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from api.services.agent_processing.lifecycle.execution_graph import agent_graph_runtime
from api.services.agent_processing.lifecycle.execution_graph.agent_progress_system import PlanningState


def _install_recording_nodes(monkeypatch, visited: List[str]) -> None:
    def _node(name: str):
        async def _run(state: PlanningState) -> Dict[str, Any]:
            visited.append(name)
            return {}

        return _run

    monkeypatch.setattr(agent_graph_runtime, "_node_analyze_request", _node("analyze_request"))
    monkeypatch.setattr(agent_graph_runtime, "_node_plan_capabilities", _node("plan_capabilities"))
    monkeypatch.setattr(agent_graph_runtime, "_node_create_tools", _node("create_tools"))
    monkeypatch.setattr(agent_graph_runtime, "_node_consider_skills", _node("consider_skills"))
    monkeypatch.setattr(agent_graph_runtime, "_node_execute_todos_with_tools", _node("execute_todos_with_tools"))


async def _run_graph(tmp_path, state: PlanningState, thread_id: str) -> None:
    async with agent_graph_runtime._open_tool_enhanced_graph(str(tmp_path / "checkpoints.sqlite")) as app:
        await app.ainvoke(state, {"configurable": {"thread_id": thread_id}})


@pytest.mark.asyncio
async def test_fresh_run_visits_every_node(monkeypatch, tmp_path):
    visited: List[str] = []
    _install_recording_nodes(monkeypatch, visited)

    await _run_graph(tmp_path, PlanningState(user_agent_task="task", context={}), "fresh")

    assert visited == [
        "analyze_request",
        "plan_capabilities",
        "create_tools",
        "consider_skills",
        "execute_todos_with_tools",
    ]


@pytest.mark.asyncio
async def test_resumed_run_skips_analysis_and_skill_selection(monkeypatch, tmp_path):
    visited: List[str] = []
    _install_recording_nodes(monkeypatch, visited)

    await _run_graph(
        tmp_path,
        PlanningState(user_agent_task="task", context={}, agent_resume_input="Blue"),
        "resumed",
    )

    assert visited == ["plan_capabilities", "create_tools", "execute_todos_with_tools"]


def test_route_functions_key_off_the_resume_input():
    fresh = PlanningState(user_agent_task="task", context={})
    resumed = PlanningState(user_agent_task="task", context={}, agent_resume_input="x")

    assert agent_graph_runtime.route_graph_entry(fresh) == "analyze_request"
    assert agent_graph_runtime.route_graph_entry(resumed) == "plan_capabilities"
    assert agent_graph_runtime.route_after_create_tools(fresh) == "consider_skills"
    assert agent_graph_runtime.route_after_create_tools(resumed) == "execute_todos_with_tools"
