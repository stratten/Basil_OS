"""Decide whether Basil may bring the browser to the front, following the user's foreground policy."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ForegroundDecision:
    allowed: bool
    reason: str
    policy: str
    message: str

    def to_result(self) -> Dict[str, Any]:
        return {
            "foreground_blocked": not self.allowed,
            "foreground_policy": self.policy,
            "reason": self.reason,
            "message": self.message,
        }


async def authorize_browser_foreground(*, purpose: str, details: str, browser: str) -> ForegroundDecision:
    """Return whether bringing `browser` to the front is allowed right now, asking the user when the policy says to."""

    from api.core.models.preferences import BrowserForegroundControlPolicy
    from api.core.preferences.preferences_io import load_preferences

    policy = load_preferences().browser_automation.foreground_control_policy
    if policy == BrowserForegroundControlPolicy.BACKGROUND_ONLY:
        return ForegroundDecision(
            False,
            "blocked_by_policy",
            policy.value,
            "Foreground browser control is turned off in Basil's Browser Automation settings.",
        )
    if policy == BrowserForegroundControlPolicy.ALLOW_FOREGROUND_WHEN_NEEDED:
        return ForegroundDecision(True, "allowed_by_policy", policy.value, "Foreground control is allowed by the user's setting.")

    from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context
    from api.services.agent_processing.tools.safety import ExecutionApprovalService

    context = get_current_agent_context()
    websocket_manager = context.get("websocket_manager")
    if websocket_manager is None:
        return ForegroundDecision(
            False,
            "no_approval_channel",
            policy.value,
            "Foreground browser control needs your approval, but no approval card can be shown from here.",
        )
    approval_context: Dict[str, Any] = {
        "source": "browser_foreground",
        "description": f"Allow Basil to bring {browser} to the front: {purpose}",
        "script_content": details,
        "execution_type": "browser_foreground_control",
        "risk_level": "high",
        "reason": "Basil wants to bring its browser window to the front so you can see or complete a step.",
        "purpose": f"Basil wants to bring {browser} to the front of your screen: {purpose}",
        "purpose_source": "basil",
    }
    agent_task_id = context.get("agent_task_id")
    if isinstance(agent_task_id, str) and agent_task_id.strip():
        approval_context["agent_task_id"] = agent_task_id
    approved, _remember, _pattern_type = await ExecutionApprovalService(
        websocket_manager=websocket_manager
    ).request_approval(f"Browser foreground control: {purpose}", context=approval_context)
    if approved:
        return ForegroundDecision(True, "approved", policy.value, "The user approved foreground control.")
    return ForegroundDecision(False, "denied", policy.value, "The user declined foreground browser control.")
