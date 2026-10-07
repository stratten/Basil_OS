"""
LangGraph Agent Execution Runtime

This module provides the main public API for LangGraph-based agent workflows and graph builders.
The actual node functions and progress system have been moved to separate modules for better organization:

- agent_progress_system.py: Progress tracking, callbacks, and step parsing  
- agent_graph_nodes.py: All individual node functions that make up the workflows

This file contains:
- Graph builders that compose nodes into complete workflows
- Public API functions that external code calls to run workflows
- LangGraph infrastructure and imports
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import logging
import asyncio
import json
import time
from typing import Any, Dict, List, Optional
from ..finalization.result_finalizer_tool import finalize_agent_task_result
import os
from pathlib import Path
import uuid

# Import shared components from split modules
from .agent_progress_system import PlanningState
from .activity_graph_nodes import (
    _node_analyze_request,
    _node_plan_capabilities, 
    _node_create_tools,
    _node_consider_skills,
    _node_execute_todos_with_tools
    # _node_construct_todos, _node_persist_todos removed - pre-planning phase deprecated
)

# Existing modules for return types
from ..planning.request_analyzer import RequestAnalyzer, RequestAnalysis
from ...service_capabilities.service_method_planner import ServiceCapabilityCache
# EnhancedTodo, DatabasePersistedTodo imports removed - pre-planning phase deprecated
from ..runtime.workflow_results import WorkflowExecutionResult
from ..runtime.agent_checkpoint_store import AGENT_CHECKPOINT_DATABASE_PATH, ExitDurabilityGraph


def _emit_runtime_trace(event: str, **fields: Any) -> None:
    """Emit opt-in, prompt-free LangGraph timing data for local runtime diagnosis."""
    if os.getenv("BASIL_LOCAL_RUNTIME_TRACE") != "1":
        return
    logging.getLogger(__name__).warning(
        "LOCAL_RUNTIME_TRACE %s",
        json.dumps(
            {"event": event, "monotonic_seconds": time.monotonic(), **fields},
            sort_keys=True,
        ),
    )


# LangGraph imports (installed via Poetry)
try:
    from langgraph.graph import StateGraph
except Exception as _:
    # Defer hard import failures to runtime; this module is additive
    StateGraph = None  # type: ignore


# === Checkpoint Serialization (msgpack-safe) ===
def _sanitize_for_msgpack(value: Any) -> Any:
    """Recursively convert runtime objects to msgpack-safe primitives for checkpointing only.

    This does NOT affect in-memory runtime behavior; it's only used by the checkpointer.
    """
    # Primitive passthrough
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    # Bytes -> string representation
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return str(value)
    # Dict
    if isinstance(value, dict):
        safe_dict: Dict[str, Any] = {}
        for k, v in value.items():
            key_str = k if isinstance(k, str) else str(k)
            safe_dict[key_str] = _sanitize_for_msgpack(v)
        return safe_dict
    # List/Tuple/Set -> list
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_msgpack(v) for v in list(value)]
    # Known problematic tool result containers -> summarize
    try:
        type_name = type(value).__name__
    except Exception:
        type_name = ""
    if type_name in {"ToolCreationResult", "AppleScriptResult"}:
        summary: Dict[str, Any] = {"_type": type_name}
        for attr in ("success", "error", "output", "tools", "errors", "optional_warnings"):
            if hasattr(value, attr):
                try:
                    attr_val = getattr(value, attr)
                    if attr == "tools" and isinstance(attr_val, list):
                        summary["tool_names"] = [getattr(t, "name", str(t)) for t in attr_val]
                        summary["tool_count"] = len(attr_val)
                    elif attr == "errors" and isinstance(attr_val, list):
                        summary["errors"] = [str(e) for e in attr_val]
                    elif attr == "optional_warnings" and isinstance(attr_val, list):
                        summary["optional_warnings"] = [str(e) for e in attr_val]
                    else:
                        summary[attr] = _sanitize_for_msgpack(attr_val)
                except Exception:
                    summary[attr] = str(getattr(value, attr))
        return summary
    # Fallback to string representation for non-serializable objects
    return str(value)


class BasilCheckpointSerde:
    """Serializer for LangGraph checkpointing that preserves runtime by storing a sanitized snapshot only."""

    def dumps(self, obj: Any) -> bytes:
        safe = _sanitize_for_msgpack(obj)
        try:
            import ormsgpack  # type: ignore
            return ormsgpack.packb(safe)
        except Exception:
            import json as _json
            return _json.dumps(safe, ensure_ascii=False).encode("utf-8")

    def loads(self, data: bytes) -> Any:
        # Return the sanitized structure; runtime will rebuild rich objects naturally in subsequent nodes
        try:
            import ormsgpack  # type: ignore
            return ormsgpack.unpackb(data)
        except Exception:
            import json as _json
            return _json.loads(data.decode("utf-8", errors="replace"))


# === GRAPH BUILDERS ===

@asynccontextmanager
async def _open_tool_enhanced_graph(
    checkpoint_path: str = AGENT_CHECKPOINT_DATABASE_PATH,
):
    """Yield one compiled graph and close its SQLite checkpointer on exit."""
    if StateGraph is None:
        raise RuntimeError("LangGraph dependencies are not available in the environment.")

    graph = StateGraph(PlanningState)

    def _timed_node(stage_name, fn):
        async def _wrapped(state):
            from ..runtime.turn_timing import get_or_create_turn_timing
            timing = get_or_create_turn_timing(getattr(state, "context", None))
            if timing is not None:
                timing.start(stage_name)
            try:
                return await fn(state)
            finally:
                if timing is not None:
                    timing.stop(stage_name)
        return _wrapped

    graph.add_node("analyze_request", _timed_node("analyze_request", _node_analyze_request))
    graph.add_node("plan_capabilities", _timed_node("plan_capabilities", _node_plan_capabilities))
    graph.add_node("create_tools", _timed_node("create_tools", _node_create_tools))
    graph.add_node("consider_skills", _timed_node("consider_skills", _node_consider_skills))
    graph.add_node("execute_todos_with_tools", _timed_node("execute_todos_with_tools", _node_execute_todos_with_tools))

    graph.set_entry_point("analyze_request")
    graph.add_edge("analyze_request", "plan_capabilities")
    graph.add_edge("plan_capabilities", "create_tools")
    graph.add_edge("create_tools", "consider_skills")
    graph.add_edge("consider_skills", "execute_todos_with_tools")

    checkpoint_database_path = os.path.expanduser(checkpoint_path)
    Path(checkpoint_database_path).parent.mkdir(parents=True, exist_ok=True)
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # type: ignore

    async with AsyncSqliteSaver.from_conn_string(checkpoint_database_path) as saver:
        yield ExitDurabilityGraph(
            graph.compile(checkpointer=AsyncSqliteSaver(saver.conn, serde=BasilCheckpointSerde()))
        )


def _derive_thread_id(context: Dict[str, Any], user_agent_task: str) -> str:
    """Derive a stable-enough thread_id for LangGraph checkpointer.

    Prefers explicit IDs from context, otherwise falls back to a short UUID.
    """
    try:
        if isinstance(context, dict):
            for key in ("thread_id", "session_id", "agent_task_id"):
                val = context.get(key)
                if val:
                    return str(val)
    except Exception:
        pass
    return f"session_{uuid.uuid4().hex[:8]}"


def _retrieve_task_outcome(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()


async def _settle_stream_tasks(*tasks: Optional[asyncio.Task]) -> None:
    """Cancel and wait out the stream's helper tasks so none is left running or holding an unretrieved exception."""
    live_tasks = [task for task in tasks if task is not None]
    for task in live_tasks:
        task.add_done_callback(_retrieve_task_outcome)
        if not task.done():
            task.cancel()
    unfinished = [task for task in live_tasks if not task.done()]
    if unfinished:
        await asyncio.wait(unfinished)


async def _close_graph_stream_safely(graph_stream: Any) -> None:
    """Best-effort ``aclose()`` on a graph astream, tolerating one benign race.

    ``graph_stream.aclose()`` runs in a ``finally`` block after we may have
    just canceled an in-flight ``__anext__()`` call on this same async
    generator (see the cancel_event branch in
    ``execute_tool_enhanced_workflow`` below). If that cancellation has not
    fully unwound the generator's frame yet, CPython's async generator
    machinery raises ``RuntimeError: aclose(): asynchronous generator is
    already running``. By the time this cleanup call runs, the pass is
    already being torn down (via cancellation or normal exhaustion), so this
    is best-effort cleanup only: swallowing this one narrow, known-benign
    error does not hide any user-facing correctness issue -- it only stops an
    internal cleanup collision from crashing an otherwise-complete or
    already-canceled agent-task run.
    """
    if not hasattr(graph_stream, "aclose"):
        return
    try:
        await graph_stream.aclose()
    except RuntimeError as exc:
        if str(exc) != "aclose(): asynchronous generator is already running":
            raise
        logging.getLogger(__name__).warning(
            "Suppressed benign graph-stream aclose() re-entrancy race: %s", exc
        )


# === PUBLIC API FUNCTIONS ===

async def plan_capabilities_with_graph(user_agent_task: str, context: Dict[str, Any]) -> ServiceCapabilityCache:
    """
    Public runner for planning-only capabilities.

    Returns a fresh ServiceCapabilityCache via the same coordinator-backed
    planner used by the tool-enhanced workflow entrypoint.
    """
    coordinator = context.get("_workflow_coordinator") if isinstance(context, dict) else None
    if coordinator is None:
        from ..runtime.workflow_coordinator import WorkflowCoordinator
        coordinator = WorkflowCoordinator()
    await coordinator._ensure_services_initialized()
    cache = await coordinator.service_method_planner.plan_service_capabilities()
    return cache


async def execute_tool_enhanced_workflow(user_agent_task: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Public runner for the streamlined tool-enhanced workflow.

    Executes the simplified 4-node pipeline:
    analyze_request -> plan_capabilities -> create_tools -> execute_todos_with_tools

    The agent creates execution steps dynamically during runtime - no pre-planning required.
    
    Returns a comprehensive result dictionary with tool execution results and performance metrics.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"🔧 DEBUG: execute_tool_enhanced_workflow STARTED with agent task: {user_agent_task}")
    graph_started_at = time.monotonic()
    cancel_event = context.get("cancel_event") if isinstance(context, dict) else None

    def _is_canceled() -> bool:
        return bool(cancel_event is not None and hasattr(cancel_event, "is_set") and cancel_event.is_set())

    if _is_canceled():
        raise asyncio.CancelledError()
    
    logger.info(f"🔧 DEBUG: About to build tool-enhanced graph")
    all_states = []
    async with _open_tool_enhanced_graph() as app:
        logger.info(f"🔧 DEBUG: Tool-enhanced graph built successfully")
        initial_state = PlanningState(user_agent_task=user_agent_task, context=context)
        logger.info(f"🔧 DEBUG: Initial state created, about to start astream")
        thread_id = _derive_thread_id(context, user_agent_task)
        graph_stream = app.astream(
            initial_state,
            config={"configurable": {"thread_id": thread_id}},
        )

        def _record_graph_event(event: Dict[str, Any]) -> None:
            all_states.append(event)
            _emit_runtime_trace(
                "agent_graph_node_completed",
                elapsed_seconds=time.monotonic() - graph_started_at,
                node_names=sorted(event.keys()),
            )

        next_event_task: Optional[asyncio.Task] = None
        cancel_task: Optional[asyncio.Task] = None
        try:
            if cancel_event is not None and hasattr(cancel_event, "wait"):
                while True:
                    if _is_canceled():
                        raise asyncio.CancelledError()
                    next_event_task = asyncio.create_task(graph_stream.__anext__())
                    cancel_task = asyncio.create_task(cancel_event.wait())
                    done, _pending = await asyncio.wait(
                        {next_event_task, cancel_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if cancel_task in done and cancel_task.result():
                        raise asyncio.CancelledError()
                    cancel_task.cancel()
                    try:
                        event = next_event_task.result()
                    except StopAsyncIteration:
                        break
                    _record_graph_event(event)
            else:
                async for event in graph_stream:
                    _record_graph_event(event)
        finally:
            await _settle_stream_tasks(next_event_task, cancel_task)
            await _close_graph_stream_safely(graph_stream)

    # Extract results from the final state
    final_results = {}
    
    for state in all_states:
        # Extract tool creation results
        if "create_tools" in state and "available_tools" in state["create_tools"]:
            tools_result = state["create_tools"]["available_tools"]
            final_results["available_tools"] = tools_result
            final_results["tools_created"] = len(tools_result.tools)
            final_results["tool_creation_errors"] = tools_result.errors
            final_results["tool_creation_warnings"] = getattr(
                tools_result, "optional_warnings", []
            ) or []
            final_results["tool_names"] = [tool.name for tool in tools_result.tools]
        
        # Note: Persistence of pre-planned todos removed - agent creates steps dynamically
        
        # Extract tool execution results
        if "execute_todos_with_tools" in state and "tool_execution_results" in state["execute_todos_with_tools"]:
            tool_execution_results = state["execute_todos_with_tools"]["tool_execution_results"]
            final_results["tool_execution_results"] = tool_execution_results
            final_results["todos_processed"] = len(tool_execution_results)
            
            # Handle both old step-based format and new dynamic agent format
            if tool_execution_results and isinstance(tool_execution_results[0], dict):
                first_result = tool_execution_results[0]
                
                # New Dynamic LangChain Agent format
                if "execution_method" in first_result and first_result["execution_method"] == "dynamic_langchain_agent":
                    # Agent executed dynamically
                    intermediate_steps = first_result.get("intermediate_steps", [])
                    dynamic_steps = first_result.get("dynamic_steps", [])
                    
                    final_results["steps_executed"] = len(dynamic_steps)
                    final_results["steps_completed"] = len([s for s in dynamic_steps if s.get("status") == "completed"])
                    final_results["steps_failed"] = len([s for s in dynamic_steps if s.get("status") == "failed"])
                    final_results["agent_output"] = first_result.get("agent_output", "")
                    final_results["tool_calls_made"] = first_result.get("total_tool_calls", 0)
                    final_results["execution_method"] = "dynamic_agent"
                elif "execution_method" in first_result and first_result["execution_method"] == "langchain_agent":
                    # Legacy agent format (fallback)
                    final_results["steps_executed"] = 1
                    final_results["steps_completed"] = 1 if first_result["status"] == "completed" else 0
                    final_results["steps_failed"] = 0 if first_result["status"] == "completed" else 1
                    final_results["agent_output"] = first_result.get("agent_output", "")
                else:
                    # Old step-based format (fallback)
                    total_steps = sum(result.get("steps_executed", 0) for result in tool_execution_results)
                    completed_steps = sum(result.get("steps_completed", 0) for result in tool_execution_results)
                    failed_steps = sum(result.get("steps_failed", 0) for result in tool_execution_results)
                    
                    final_results["steps_executed"] = total_steps
                    final_results["steps_completed"] = completed_steps
                    final_results["steps_failed"] = failed_steps
            else:
                # No results or empty results
                final_results["steps_executed"] = 0
                final_results["steps_completed"] = 0 
                final_results["steps_failed"] = 0
    
    # Pass-through envelope: if the node produced a final_envelope, forward it untouched
    try:
        for state in all_states:
            if "execute_todos_with_tools" in state:
                node_out = state["execute_todos_with_tools"] or {}
                if isinstance(node_out, dict) and "final_envelope" in node_out and isinstance(node_out["final_envelope"], dict):
                    final_results["final_envelope"] = node_out["final_envelope"]
                if isinstance(node_out, dict) and "workflow_result" in node_out and isinstance(node_out["workflow_result"], str):
                    final_results["workflow_result"] = node_out["workflow_result"]
    except Exception:
        # Envelope is optional; never recompute here
        pass

    # If no explicit final_envelope returned by the node, attempt to recover from intermediate_steps
    try:
        if "final_envelope" not in final_results:
            ter = final_results.get("tool_execution_results") or []
            if ter and isinstance(ter[0], dict):
                first_result = ter[0]
                intermediate_steps = first_result.get("intermediate_steps", [])
                import json as _json
                last_success_index = -1
                recovered_envelope = None
                for step in intermediate_steps:
                    if isinstance(step, tuple) and len(step) >= 2:
                        action, observation = step[0], step[1]
                        tool_name = getattr(action, "tool", None)
                        if tool_name == "finalize_agent_task_result" and observation is not None:
                            parsed = None
                            try:
                                parsed = _json.loads(observation if isinstance(observation, str) else str(observation))
                            except Exception:
                                if isinstance(observation, dict):
                                    parsed = observation
                            if isinstance(parsed, dict):
                                current_index = intermediate_steps.index(step)
                                if parsed.get("success") is True:
                                    recovered_envelope = parsed
                                    last_success_index = current_index
                                else:
                                    if recovered_envelope is None and last_success_index < 0:
                                        recovered_envelope = parsed
                if isinstance(recovered_envelope, dict):
                    final_results["final_envelope"] = recovered_envelope
                    if isinstance(recovered_envelope.get("summary_text"), str):
                        final_results["workflow_result"] = recovered_envelope["summary_text"]
    except Exception:
        # Best-effort recovery only
        pass

    return final_results
