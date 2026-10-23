"""Approval handling for external_catalog tool calls."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def request_external_catalog_user_approval(record, tool_name: str, arguments: Dict[str, Any]) -> bool:
    """Use ExecutionApprovalService to gate an always_ask tool call.

    The synthesized command string is what the user will see in the
    approval prompt; we make it readable rather than precise so the
    user can recognize what's being asked at a glance.
    """
    try:
        from api.services.agent_processing.tools.safety.execution_approval_service import (
            ExecutionApprovalService,
        )
    except Exception as exc:
        logger.warning("ExecutionApprovalService unavailable; defaulting always_ask -> denied (%s)", exc)
        return False

    runtime_context: Dict[str, Any] = {}
    try:
        from api.services.agent_processing.shared.agent_runtime_context import (
            get_current_agent_context,
        )

        current_context = get_current_agent_context()
        if isinstance(current_context, dict):
            runtime_context = current_context
    except Exception as exc:
        logger.debug("Could not read agent runtime context for external approval: %s", exc)

    websocket_manager = runtime_context.get("websocket_manager")
    agent_task_id = runtime_context.get("agent_task_id")
    approval_service = ExecutionApprovalService(websocket_manager=websocket_manager)
    args_summary = json.dumps(arguments, separators=(",", ":"))[:300]
    synthetic_command = f"mcp:{record.friendly_name}:{tool_name}({args_summary})"
    approval_context = {
        "source": "external_catalog",
        "connection_id": record.id,
        "friendly_name": record.friendly_name,
        "server_url": record.server_url,
        "tool_name": tool_name,
        "arguments": arguments,
    }
    if agent_task_id:
        approval_context["agent_task_id"] = agent_task_id
    try:
        approved, _remember, _ptype = await approval_service.request_approval(
            synthetic_command,
            context=approval_context,
        )
        return bool(approved)
    except Exception as exc:
        logger.warning("Approval flow raised; defaulting to denied: %s", exc)
        return False
