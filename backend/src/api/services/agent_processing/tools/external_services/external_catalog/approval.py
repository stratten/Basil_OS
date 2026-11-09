"""Approval handling for external_catalog tool calls."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


_PROMPT_SUMMARY_MAX_CHARS = 120


class ExplanationRequired(Exception):
    """The approval card needs the agent's explanation first, and nothing was shown to the user or denied.

    Raised from ``request_external_catalog_user_approval`` so its boolean return keeps meaning approved or not. The dispatcher turns it into an envelope that asks the agent to repeat the same call with ``purpose``.
    """


def _arguments_for_prompt(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Return the arguments with a plain-language ``summary`` first, so the prompt's cut-off keeps it.

    Some connectors (Gmail) identify things by opaque ids, which tell the user nothing. Those tools
    take an optional ``summary`` argument naming the item in words; it leads the prompt text and is
    capped so it cannot crowd out the arguments that follow.
    """
    summary = arguments.get("summary") if isinstance(arguments, dict) else None
    if not isinstance(summary, str) or not summary.strip():
        return arguments
    ordered: Dict[str, Any] = {"summary": summary.strip()[:_PROMPT_SUMMARY_MAX_CHARS]}
    ordered.update({key: value for key, value in arguments.items() if key != "summary"})
    return ordered


async def request_external_catalog_user_approval(
    record,
    tool_name: str,
    arguments: Dict[str, Any],
    purpose: Optional[str] = None,
) -> bool:
    """Use ExecutionApprovalService to gate an always_ask tool call.

    The synthesized command string is what the user will see in the
    approval prompt; we make it readable rather than precise so the
    user can recognize what's being asked at a glance. ``purpose`` is
    the agent's own plain-language account of what the call does and
    why. It is shown above the command and is never sent to the remote
    tool. Without it the approval service asks the agent once for it
    (raising ``ExplanationRequired``) before any card is shown.
    """
    try:
        from api.services.agent_processing.tools.safety.execution_approval_service import (
            ExecutionApprovalService,
        )
        from api.services.agent_processing.tools.safety.connected_tool_remember import (
            build_tool_policy_scope,
            server_marks_tool_destructive,
        )
        from api.services.agent_processing.tools.safety.explanation_gate import EXPLANATION_REQUIRED_STATUS
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
    args_summary = json.dumps(_arguments_for_prompt(arguments), separators=(",", ":"))[:300]
    synthetic_command = f"mcp:{record.friendly_name}:{tool_name}({args_summary})"
    approval_context = {
        "source": "external_catalog",
        "connection_id": record.id,
        "friendly_name": record.friendly_name,
        "server_url": record.server_url,
        "tool_name": tool_name,
        "arguments": arguments,
        "purpose": purpose,
        "purpose_required": True,
        # Remembering this approval sets this one tool to always_allow on this one connection; it is never a command pattern.
        "remember_tool_policy": build_tool_policy_scope(
            record.id,
            record.friendly_name,
            tool_name,
            server_marked_destructive=server_marks_tool_destructive(record, tool_name),
        ),
    }
    if agent_task_id:
        approval_context["agent_task_id"] = agent_task_id
    try:
        approved, _remember, pattern_type = await approval_service.request_approval(
            synthetic_command,
            context=approval_context,
        )
    except Exception as exc:
        logger.warning("Approval flow raised; defaulting to denied: %s", exc)
        return False
    if not approved and pattern_type == EXPLANATION_REQUIRED_STATUS:
        raise ExplanationRequired()
    return bool(approved)
