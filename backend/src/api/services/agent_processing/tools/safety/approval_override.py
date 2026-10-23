"""Per-run approval-policy override (test-only).

Normal application flows never register an override, so approval behavior is
unchanged: every read falls back to the global ToolExecutionSettings from
load_preferences(). A test harness can register an override keyed by
agent_task_id -- via AgentTaskRequest.approval_policy_override over HTTP, or the
approval_policy_override= param of process_agent_task_direct in-process -- to run
one specific agent task under, e.g., ALWAYS_APPROVE without touching the user's
saved preferences or affecting any concurrent real task.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, Optional

from pydantic import BaseModel

from api.core.models.preferences import (
    ApprovalTimeoutBehavior,
    ExecutionApprovalMode,
    ToolExecutionSettings,
)
from api.core.preferences.preferences_io import load_preferences

_MAX_OVERRIDES = 256


class ApprovalOverride(BaseModel):
    """A partial, per-run override of tool-execution approval settings."""
    approval_mode: Optional[ExecutionApprovalMode] = None
    timeout_behavior: Optional[ApprovalTimeoutBehavior] = None
    approval_timeout_seconds: Optional[int] = None
    auto_approve_read_only: Optional[bool] = None
    safe_execution_mode: Optional[bool] = None


_OVERRIDES: "OrderedDict[str, ApprovalOverride]" = OrderedDict()


def register_override(agent_task_id: str, override: ApprovalOverride) -> None:
    if not agent_task_id:
        return
    _OVERRIDES[agent_task_id] = override
    _OVERRIDES.move_to_end(agent_task_id)
    while len(_OVERRIDES) > _MAX_OVERRIDES:
        _OVERRIDES.popitem(last=False)


def clear_override(agent_task_id: str) -> None:
    _OVERRIDES.pop(agent_task_id, None)


def get_override(agent_task_id: Optional[str]) -> Optional[ApprovalOverride]:
    if not agent_task_id:
        return None
    return _OVERRIDES.get(agent_task_id)


def resolve_tool_execution_settings(context: Optional[Dict[str, Any]] = None) -> ToolExecutionSettings:
    """Effective tool-execution settings for the current approval check.

    Falls back to the global saved settings unless the given context carries an
    agent_task_id with a registered per-run override, in which case the override
    fields are layered over a copy of the global settings (global is never mutated).
    """
    settings = load_preferences().tool_execution
    agent_task_id = (context or {}).get("agent_task_id")
    override = get_override(agent_task_id)
    if override is None:
        return settings
    updates = override.model_dump(exclude_none=True)
    if not updates:
        return settings
    return settings.model_copy(update=updates)
