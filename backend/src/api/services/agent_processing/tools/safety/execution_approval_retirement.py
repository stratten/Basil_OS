"""Retire pending execution approvals that belong to tasks which will never resume them."""

from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)


async def retire_pending_execution_approvals(
    approval_repository: Any,
    agent_task_ids: Iterable[str],
) -> int:
    """Clear attention, stop local waiters, and durably cancel every pending approval for the tasks.

    Returns the number of durable rows canceled. Attention clearing and waiter cancellation are best-effort per approval; the durable cancel always runs.
    """
    from api.services.agent_processing.tools.safety.interactive_approval import (
        InteractiveApprovalManager,
    )
    from api.services.conversation.conversation_agent_turn_lifecycle import (
        clear_conversation_agent_attention,
    )

    task_ids = [str(task_id).strip() for task_id in agent_task_ids if str(task_id or "").strip()]
    if not task_ids:
        return 0
    for task_id in task_ids:
        approvals = await approval_repository.list_pending_approvals_for_agent_task(task_id)
        for approval in approvals or []:
            approval_id = str(approval["id"])
            try:
                await clear_conversation_agent_attention(task_id, approval_id)
            except Exception:
                logger.exception("Failed to clear approval attention for %s", approval_id)
            InteractiveApprovalManager.cancel_pending_future(approval_id)
    return int(await approval_repository.cancel_pending_approvals_for_tasks(task_ids) or 0)


__all__ = ["retire_pending_execution_approvals"]
