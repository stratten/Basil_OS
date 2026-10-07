"""Save a user-requested pause like a question checkpoint, under the durable status ``paused``."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .task_state_persistence import normalize_thinking_history

logger = logging.getLogger(__name__)


async def handle_user_pause_request(
    checkpoint_err: Any,
    state: Any,
    coordinator: Any,
    thinking_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    checkpoint_data = checkpoint_err.checkpoint_data
    context = state.context if isinstance(state.context, dict) else {}
    agent_task_id = context.get("agent_task_id")
    root_task_id = context.get("root_task_id")
    previous_task_id = context.get("previous_task_id")
    ws_manager = getattr(coordinator, "_websocket_manager", None) or context.get("websocket_manager")
    broadcast = getattr(ws_manager, "broadcast", None)
    logger.info("⏸️ Saving the user's pause for %s", agent_task_id)

    from ..runtime.user_interaction_timeline import record_user_interaction_asked

    await record_user_interaction_asked(
        agent_task_id,
        interaction_id=checkpoint_data.get("checkpoint_id"),
        kind="pause",
        prompt=str(checkpoint_data.get("prompt") or "Paused at your request"),
        broadcast=broadcast,
    )

    if agent_task_id:
        try:
            from api.dependencies import get_sqlite_knowledge_service

            knowledge_service = get_sqlite_knowledge_service()
            existing_data: Dict[str, Any] = {}
            try:
                existing = await knowledge_service.agent_task_service._queries.get_agent_task(agent_task_id)
                if existing and existing.result_data:
                    if isinstance(existing.result_data, str):
                        existing_data = json.loads(existing.result_data)
                    elif isinstance(existing.result_data, dict):
                        existing_data = dict(existing.result_data)
            except Exception:
                existing_data = {}
            existing_data.update({
                "checkpoint_data": checkpoint_data,
                "needs_user_input": True,
                "paused_by_user": True,
                "execution_method": "dynamic_langchain_agent",
            })
            paused_thinking_history = normalize_thinking_history(thinking_history)
            if paused_thinking_history:
                existing_data["thinking_history"] = paused_thinking_history
            await knowledge_service.agent_task_service.update_agent_task_status_if_active(
                agent_task_id=agent_task_id,
                status="paused",
                result_data=existing_data,
            )
        except Exception as db_error:
            logger.warning("⚠️ Failed to save the pause for %s: %s", agent_task_id, db_error)

    if broadcast is not None and agent_task_id:
        payload: Dict[str, Any] = {
            "event_type": "agent_task_paused",
            "agent_task_id": agent_task_id,
            "message": "Paused",
        }
        if root_task_id:
            payload["root_task_id"] = root_task_id
        if previous_task_id:
            payload["previous_task_id"] = previous_task_id
        try:
            await broadcast(payload)
        except Exception as ws_error:
            logger.warning("⚠️ Failed to announce the pause for %s: %s", agent_task_id, ws_error)

    return {
        "tool_execution_results": [{
            "execution_method": "dynamic_langchain_agent",
            "user_agent_task": state.user_agent_task,
            "status": "awaiting_user_input",
            "checkpoint_data": checkpoint_data,
            "needs_user_input": True,
            "paused_by_user": True,
        }]
    }
