"""User approval for an Agent Task closing out a To-Do (completing, dismissing, or canceling it)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Statuses an agent may set only after the user approves. Every other status the agent can set is a working state that the user can see and change back.
APPROVAL_REQUIRED_TODO_STATUSES = frozenset({"completed", "dismissed", "canceled"})

_STATUS_VERBS = {"completed": "complete", "dismissed": "dismiss", "canceled": "cancel"}
_TITLE_PREVIEW_CHARS = 120
APPROVAL_EXECUTION_TYPE = "todo_status"


def todo_status_approval_command(todo_id: str, title: str, status: str) -> str:
    """The readable line the user sees on the approval card, naming the To-Do and what will happen to it."""
    verb = _STATUS_VERBS.get(status, status)
    shown_title = " ".join(title.split())[:_TITLE_PREVIEW_CHARS]
    return f'Basil To-Do: {verb} "{shown_title}" ({todo_id})'


async def request_todo_status_approval(
    *, todo_id: str, title: str, status: str, agent_task_id: Optional[str],
) -> Tuple[bool, str]:
    """Ask the user to approve closing out a To-Do; returns whether it was approved and a reason the agent can report.

    This uses the same approval service and card as command approvals, so the user's approval settings, countdown, and timeout behavior apply. The decision is never remembered, because the execution type is not a rememberable one.
    """
    try:
        from api.services.agent_processing.tools.safety.execution_approval_service import ExecutionApprovalService
    except Exception as exc:
        logger.warning("ExecutionApprovalService unavailable; denying To-Do status change (%s)", exc)
        return False, "Approval is unavailable, so the To-Do was not changed."

    runtime_context: Dict[str, Any] = {}
    try:
        from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context

        current_context = get_current_agent_context()
        if isinstance(current_context, dict):
            runtime_context = current_context
    except Exception as exc:
        logger.debug("Could not read agent runtime context for To-Do approval: %s", exc)

    approval_service = ExecutionApprovalService(websocket_manager=runtime_context.get("websocket_manager"))
    verb = _STATUS_VERBS.get(status, status)
    context: Dict[str, Any] = {
        "source": "todo_tools",
        "execution_type": APPROVAL_EXECUTION_TYPE,
        "description": f"The agent wants to {verb} a To-Do",
        "purpose": f'The agent wants to {verb} your To-Do "{" ".join(title.split())[:_TITLE_PREVIEW_CHARS]}". Nothing changes on the To-Do unless you approve.',
        "purpose_source": "basil",
    }
    task_id = agent_task_id or runtime_context.get("agent_task_id")
    if task_id:
        context["agent_task_id"] = task_id
    try:
        outcome = await approval_service.request_approval_with_outcome(
            todo_status_approval_command(todo_id, title, status), context,
        )
    except Exception as exc:
        logger.warning("To-Do approval flow raised; denying: %s", exc)
        return False, "Approval could not be requested, so the To-Do was not changed."
    if outcome.approved:
        return True, "The user approved."
    return False, f"The user did not approve ({outcome.status}), so the To-Do was not changed."
