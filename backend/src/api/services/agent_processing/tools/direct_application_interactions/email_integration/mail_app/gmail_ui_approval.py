"""The approval card shown before Basil takes over Mail's windows to archive or move a Gmail message.

Mail's scripting cannot remove the Inbox label on a Gmail account, so the only working route clicks Mail's own menus. That brings Mail to the front and takes over the screen for several seconds per message, so it always needs the user's explicit approval: the request sets ``require_explicit_approval``, which "always approve" mode, read-only auto-approval, and remembered patterns all respect.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context

from .gmail_inbox_ui import NO_APPROVAL_CHANNEL_REASON, ApprovalRequester

logger = logging.getLogger(__name__)

SECONDS_PER_MESSAGE = 10
"""Measured live: one archive or move through Mail's menus takes roughly 8 to 14 seconds."""


def _verb(operation: str) -> str:
    return "archive" if operation == "archive" else "move"


def build_approval_command(summary: Dict[str, Any]) -> str:
    """The one-line command text stored with the approval and shown as its title."""
    count = int(summary.get("message_count") or 0)
    noun = "message" if count == 1 else "messages"
    return f"Take over Mail's windows to {_verb(str(summary.get('operation')))} {count} Gmail {noun}"


def build_approval_description(summary: Dict[str, Any]) -> str:
    """Plain-language explanation of what will happen on the user's screen."""
    count = int(summary.get("message_count") or 0)
    verb = _verb(str(summary.get("operation")))
    accounts = ", ".join(summary.get("accounts") or []) or "your Gmail account"
    subjects = "; ".join(f'"{subject}"' for subject in (summary.get("subjects") or [])[:5])
    targets = ", ".join(summary.get("target_mailboxes") or [])
    destination = f" into {targets}" if targets else ""
    return (
        f"To {verb} {count} message(s){destination} in {accounts}, Basil has to open a temporary Mail window and click Mail's own menus, "
        f"because Mail's scripting cannot remove the Inbox label on Gmail. Mail will come to the front and your screen will be in use for roughly "
        f"{max(count, 1) * SECONDS_PER_MESSAGE} seconds, so please do not type or click in Mail until it finishes. "
        f"Mail acts on whole conversations. Conversations: {subjects or 'unknown'}."
    )


def _denial_reason(operation: str, status: str, detail: str) -> str:
    verb = _verb(operation)
    if status == "user_denied":
        return f"The user declined to let Basil take over Mail's windows to {verb} this Gmail message, so nothing was changed. Tell the user it needs to be done in Mail directly, or ask whether they want to allow it and try again."
    if status == "approval_timed_out":
        return f"The user did not answer the request to let Basil take over Mail's windows to {verb} this Gmail message in time, so nothing was changed. Tell the user it needs to be done in Mail directly, or ask whether they want to allow it and try again."
    return detail or NO_APPROVAL_CHANNEL_REASON


async def request_mail_ui_approval(approval_service: Optional[Any], summary: Dict[str, Any]) -> Tuple[bool, str]:
    """Ask the user, through the shared execution-approval card, and return (approved, reason when not approved)."""
    if approval_service is None:
        return False, NO_APPROVAL_CHANNEL_REASON
    agent_task_id = get_current_agent_context().get("agent_task_id")
    if not isinstance(agent_task_id, str) or not agent_task_id.strip():
        return False, NO_APPROVAL_CHANNEL_REASON
    operation = str(summary.get("operation"))
    context: Dict[str, Any] = {
        "source": "email_service",
        "description": build_approval_description(summary),
        "execution_type": "applescript",
        "risk_level": "high",
        "reason": "Archiving or moving a Gmail message in Apple Mail takes over the visible Mail window and menus.",
        "require_explicit_approval": True,
        "agent_task_id": agent_task_id.strip(),
    }
    outcome = await approval_service.request_approval_with_outcome(build_approval_command(summary), context)
    if outcome.approved:
        return True, ""
    logger.info("Mail window takeover was not approved: status=%s", outcome.status)
    return False, _denial_reason(operation, outcome.status, outcome.reason)


def once_per_call(approval_service: Optional[Any]) -> ApprovalRequester:
    """One requester per organize call, so the archive fallback after a move reuses the answer instead of asking twice."""
    answer: Dict[str, Tuple[bool, str]] = {}

    async def request(summary: Dict[str, Any]) -> Tuple[bool, str]:
        if "result" not in answer:
            answer["result"] = await request_mail_ui_approval(approval_service, summary)
        return answer["result"]

    return request
