"""Asks the user to approve a setting change an agent wants to make, and waits for the answer."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from api.core.preferences import preferences_io
from api.services.agent_processing.lifecycle.runtime.user_interaction_timeline import (
    build_response_time_limit,
    record_user_interaction_asked,
    record_user_interaction_resolved,
)
from api.services.agent_processing.shared.workflow_budget_pause import pause_workflow_budget

logger = logging.getLogger(__name__)

ApprovalOutcome = Literal["approved", "denied", "timed_out", "unavailable", "busy"]

MAX_PENDING_APPROVALS = 3

WHITELIST_NOTICE = "Settings changes are approved one at a time and cannot be remembered."


@dataclass
class SettingsChangeApprovalRequest:
    """What the approval card shows. Each item in `changes` has key, label, before, after."""

    tier: str
    reason: str
    changes: List[Dict[str, Any]]
    agent_task_id: Optional[str] = None
    websocket_manager: Any = field(default=None, repr=False)

    @property
    def summary(self) -> str:
        parts = [f"{change['label']}: {change['before']} to {change['after']}" for change in self.changes[:3]]
        extra = len(self.changes) - len(parts)
        text = "; ".join(parts) + (f"; and {extra} more" if extra > 0 else "")
        return f"Change Basil settings. {text}"


class SettingsChangeApprovalManager:
    """Tracks approval prompts that are waiting for the user. The wait is not counted against the agent's time budget."""

    _pending: Dict[str, "asyncio.Future[bool]"] = {}
    _pending_task_ids: Dict[str, Optional[str]] = {}

    async def request(self, request: SettingsChangeApprovalRequest) -> ApprovalOutcome:
        manager = request.websocket_manager
        if manager is None:
            return "unavailable"

        if len(SettingsChangeApprovalManager._pending) >= MAX_PENDING_APPROVALS or (
            request.agent_task_id is not None and request.agent_task_id in SettingsChangeApprovalManager._pending_task_ids.values()
        ):
            return "busy"

        approval_id = str(uuid.uuid4())
        future: "asyncio.Future[bool]" = asyncio.get_running_loop().create_future()
        SettingsChangeApprovalManager._pending[approval_id] = future
        SettingsChangeApprovalManager._pending_task_ids[approval_id] = request.agent_task_id
        try:
            approval_timeout = preferences_io.load_preferences().tool_execution.approval_timeout_seconds
            try:
                time_limit = build_response_time_limit(approval_timeout, "deny")
            except ValueError:
                time_limit = None
            event: Dict[str, Any] = {
                "event_type": "execution_approval_request",
                "approval_id": approval_id,
                "command": request.summary,
                "reason": request.reason or "An agent wants to change how Basil looks or behaves.",
                "risk_level": "medium",
                "generalized_pattern": "settings_change:" + ",".join(sorted(change["key"] for change in request.changes)),
                "execution_type": "settings_change",
                "context": {
                    "source": "app_settings",
                    "description": "An agent is asking to change Basil settings",
                    "whitelist": {"eligible": False, "reason": WHITELIST_NOTICE, "advice": None},
                    **({"time_limit": time_limit} if time_limit else {}),
                },
                "options": {
                    "risk_level": "medium",
                    "reason": "Settings changes need your approval",
                    "show_remember": False,
                },
                "settings_change": {
                    "tier": request.tier,
                    "changes": [
                        {"key": change["key"], "label": change["label"], "before": str(change["before"]), "after": str(change["after"])}
                        for change in request.changes
                    ],
                },
            }
            if request.agent_task_id:
                event["agent_task_id"] = request.agent_task_id

            await manager.broadcast(event)
            await record_user_interaction_asked(
                request.agent_task_id,
                interaction_id=approval_id,
                kind="approval",
                prompt=event["command"],
                input_type="settings_change",
                broadcast=manager.broadcast,
                time_limit=time_limit,
            )
            try:
                with pause_workflow_budget("settings_change_approval"):
                    approved = await asyncio.wait_for(future, timeout=float(approval_timeout))
            except asyncio.TimeoutError:
                logger.warning("Settings change approval %s timed out", approval_id)
                await record_user_interaction_resolved(
                    request.agent_task_id,
                    interaction_id=approval_id,
                    status="timed_out",
                    broadcast=manager.broadcast,
                )
                return "timed_out"
            await record_user_interaction_resolved(
                request.agent_task_id,
                interaction_id=approval_id,
                status="approved" if approved else "denied",
                broadcast=manager.broadcast,
            )
            return "approved" if approved else "denied"
        finally:
            SettingsChangeApprovalManager._pending.pop(approval_id, None)
            SettingsChangeApprovalManager._pending_task_ids.pop(approval_id, None)

    @classmethod
    async def resolve(cls, approval_id: str, approved: bool) -> bool:
        """Deliver the user's answer. False when the prompt is unknown or was already answered."""
        future = cls._pending.get(approval_id)
        if future is None or future.done():
            return False
        future.set_result(bool(approved))
        return True


_MANAGER = SettingsChangeApprovalManager()


def get_settings_change_approval_manager() -> SettingsChangeApprovalManager:
    return _MANAGER
