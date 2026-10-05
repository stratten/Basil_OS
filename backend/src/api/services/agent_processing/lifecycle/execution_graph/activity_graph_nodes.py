"""Phase-reporting wrappers around the established LangGraph node implementations."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from ..runtime.activity_phase_notifier import emit_activity_phase
from . import agent_graph_nodes as legacy_nodes


async def _run_node_phase(
    state: Any,
    *,
    phase: str,
    title: str,
    node: Callable[[Any], Awaitable[Dict[str, Any]]],
) -> Dict[str, Any]:
    await emit_activity_phase(
        state, phase=phase, lifecycle_state="started", title=title, source="graph_node",
    )
    try:
        result = await node(state)
    except Exception as error:
        await emit_activity_phase(
            state,
            phase=phase,
            lifecycle_state="failed",
            title=f"{title} failed",
            source="graph_node",
            error=error,
        )
        raise

    status = "completed"
    if isinstance(result, dict):
        tool_results = result.get("tool_execution_results") or []
        if tool_results and isinstance(tool_results[0], dict):
            status = tool_results[0].get("status") or status
    if status in {"awaiting_user_input", "waiting_user_input"}:
        status = "waiting_user_input"
    await emit_activity_phase(
        state, phase=phase, lifecycle_state=status, title=title, source="graph_node",
    )
    return result


async def _node_analyze_request(state: Any) -> Dict[str, Any]:
    return await _run_node_phase(
        state, phase="analysis", title="Analyzing request", node=legacy_nodes._node_analyze_request,
    )


async def _node_plan_capabilities(state: Any) -> Dict[str, Any]:
    return await _run_node_phase(
        state, phase="planning", title="Planning available actions", node=legacy_nodes._node_plan_capabilities,
    )


async def _node_create_tools(state: Any) -> Dict[str, Any]:
    return await _run_node_phase(
        state, phase="tool_setup", title="Preparing tools", node=legacy_nodes._node_create_tools,
    )


async def _node_consider_skills(state: Any) -> Dict[str, Any]:
    return await _run_node_phase(
        state, phase="skill_selection", title="Considering saved skills", node=legacy_nodes._node_consider_skills,
    )


async def _node_execute_todos_with_tools(state: Any) -> Dict[str, Any]:
    return await _run_node_phase(
        state, phase="execution", title="Working on the task", node=legacy_nodes._node_execute_todos_with_tools,
    )
