from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ...tools.internal_basil_tools.checkpoint_tool import CheckpointRequest

if TYPE_CHECKING:
    from ..execution_graph.agent_progress_system import PlanningState

logger = logging.getLogger(__name__)


def normalize_thinking_history(raw: Any) -> List[Dict[str, Any]]:
    """Return the canonical persisted shape for emitted reasoning segments."""
    if not isinstance(raw, list):
        return []

    by_iteration: Dict[int, Dict[str, Any]] = {}
    for segment in raw:
        if not isinstance(segment, Mapping):
            continue
        iteration = segment.get("iteration")
        text = segment.get("text")
        is_complete = segment.get("is_complete")
        if (
            not isinstance(iteration, int)
            or isinstance(iteration, bool)
            or not isinstance(text, str)
            or not text.strip()
            or not isinstance(is_complete, bool)
        ):
            continue
        by_iteration[iteration] = {
            "iteration": iteration,
            "text": text,
            "is_complete": is_complete,
        }

    return [by_iteration[iteration] for iteration in sorted(by_iteration)]


async def _store_execution_context(
    agent_task_id: Optional[str],
    agent_output: str,
    enhanced_output: str,
    full_content: str,
    intermediate_steps: List[Any],
    dynamic_steps: List[Any],
    final_envelope: Optional[Dict],
    thinking_history: Optional[List[Dict]] = None,
    progress_steps: Optional[List[Dict]] = None,
    execution_timeline: Optional[List[Dict]] = None
) -> None:
    """Store complete agent execution context in database."""
    if not agent_task_id:
        return

    try:
        from api.dependencies import get_sqlite_knowledge_service
        from .execution_result_processing import _merge_execution_timelines

        knowledge_service = get_sqlite_knowledge_service()

        agent_execution_data = {
            "agent_output": agent_output,
            "enhanced_output": enhanced_output,
            "full_content": full_content,
            "intermediate_steps_count": len(intermediate_steps),
            "tool_calls": len(intermediate_steps),
            "dynamic_steps": dynamic_steps,
            "execution_method": "dynamic_langchain_agent",
            "finalizer_result": final_envelope if final_envelope else None,
            "thinking_history": normalize_thinking_history(thinking_history),
        }
        if final_envelope and isinstance(final_envelope, dict):
            summary = final_envelope.get("summary_text")
            if summary:
                agent_execution_data["message"] = summary

        final_status = "completed"
        if final_envelope and isinstance(final_envelope, dict):
            final_status = "completed" if final_envelope.get("success") else "failed"

        changed = await knowledge_service.agent_task_service.update_agent_task_status_if_active(
            agent_task_id=agent_task_id,
            status=final_status,
            result_data=agent_execution_data
        )
        if not changed:
            logger.info("🛑 Skipped final execution context because %s is terminal", agent_task_id)
            return

        # Store execution timeline in dedicated column (not inside result_data)
        if execution_timeline:
            existing_agent_task = await knowledge_service.get_agent_task(agent_task_id)
            merged_execution_timeline = _merge_execution_timelines(
                getattr(existing_agent_task, "execution_timeline", None),
                execution_timeline,
            )
            await knowledge_service.agent_task_service._mutations.update_execution_timeline(
                agent_task_id=agent_task_id,
                timeline=merged_execution_timeline
            )

        logger.info(f"💾 Stored agent execution context and finalizer result in database for agent task {agent_task_id}")
    except Exception as store_err:
        logger.warning(f"⚠️ Failed to store agent execution context: {store_err}")


async def handle_provider_delegation_wait_request(
    delegation_wait: Any,
    state: "PlanningState",
    coordinator: Any,
) -> Dict[str, Any]:
    """Return the nonterminal workflow result for one routed provider child."""
    agent_task_id = state.context.get("agent_task_id") if state.context else None
    root_task_id = state.context.get("root_task_id") if state.context else None
    if not agent_task_id or not root_task_id:
        raise RuntimeError("Provider delegation wait requires captured task and root identity.")
    status = "awaiting_provider_delegation"
    try:
        from api.dependencies import get_sqlite_knowledge_service

        generic_run = await get_sqlite_knowledge_service().delegated_agent_repository.get_run_for_child(
            delegation_wait.child_agent_task_id
        )
        if generic_run is not None:
            status = "awaiting_delegated_agents"
    except Exception:
        logger.warning("Unable to classify generic delegated-child wait state", exc_info=True)
    return {
        "tool_execution_results": [
            {
                "execution_method": "dynamic_langchain_agent",
                "status": status,
                "needs_provider_delegation": True,
                "delegation_id": delegation_wait.delegation_id,
                "child_agent_task_id": delegation_wait.child_agent_task_id,
            }
        ]
    }


async def handle_checkpoint_request(
    checkpoint_err: CheckpointRequest,
    state: "PlanningState",
    coordinator: Any
) -> Dict[str, Any]:
    """Handle checkpoint request (collaborative flow, NOT an error)."""
    logger.info(f"🤝 Agent requested user input (collaborative checkpoint): {checkpoint_err.checkpoint_data.get('prompt')}")

    checkpoint_data = checkpoint_err.checkpoint_data
    agent_task_id = state.context.get("agent_task_id")
    root_task_id = state.context.get("root_task_id")
    previous_task_id = state.context.get("previous_task_id")

    ws_manager = coordinator._websocket_manager or state.context.get("websocket_manager")
    if ws_manager and agent_task_id:
        try:
            broadcast_payload = {
                "event_type": "collaborative_checkpoint_request",
                "agent_task_id": agent_task_id,
                "checkpoint_data": {
                    "checkpoint_id": checkpoint_data.get("checkpoint_id"),
                    "prompt": checkpoint_data.get("prompt", "Agent needs your input"),
                    "input_type": checkpoint_data.get("input_type", "text"),
                    "options": checkpoint_data.get("options", []),
                    "context_summary": checkpoint_data.get("context_summary", ""),
                    "default_value": checkpoint_data.get("default_value", ""),
                    "metadata": checkpoint_data.get("metadata", {}),
                    "user_agent_task": state.user_agent_task
                }
            }
            if root_task_id:
                broadcast_payload["root_task_id"] = root_task_id
            if previous_task_id:
                broadcast_payload["previous_task_id"] = previous_task_id
            await ws_manager.broadcast(broadcast_payload)
            logger.info("✅ Sent collaborative_checkpoint_request to frontend via WebSocket")
        except Exception as ws_err:
            logger.warning(f"⚠️ Failed to send checkpoint via WebSocket: {ws_err}")

    if agent_task_id:
        try:
            from api.dependencies import get_sqlite_knowledge_service
            import json as _json
            knowledge_service = get_sqlite_knowledge_service()
            existing_data = {}
            try:
                existing_cmd = await knowledge_service.agent_task_service._queries.get_agent_task(agent_task_id)
                if existing_cmd and existing_cmd.result_data:
                    if isinstance(existing_cmd.result_data, str):
                        existing_data = _json.loads(existing_cmd.result_data)
                    elif isinstance(existing_cmd.result_data, dict):
                        existing_data = existing_cmd.result_data
            except Exception:
                existing_data = {}
            existing_data.update({
                "checkpoint_data": checkpoint_data,
                "needs_user_input": True,
                "execution_method": "dynamic_langchain_agent"
            })
            await knowledge_service.agent_task_service.update_agent_task_status(
                agent_task_id=agent_task_id,
                status="awaiting_user_input",
                result_data=existing_data
            )
            logger.info(f"💾 Marked agent task {agent_task_id} as awaiting_user_input in database (merged with existing data)")
        except Exception as db_err:
            logger.warning(f"⚠️ Failed to update database status: {db_err}")

    return {
        "tool_execution_results": [{
            "execution_method": "dynamic_langchain_agent",
            "user_agent_task": state.user_agent_task,
            "status": "awaiting_user_input",
            "checkpoint_data": checkpoint_data,
            "needs_user_input": True,
            "tools_available": [tool.name for tool in state.available_tools.tools] if state.available_tools else []
        }]
    }
