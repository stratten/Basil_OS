"""Active-time limits for one run of Basil's inner agent loop.

Cloud models keep the 20 minute active budget. A local model is slower per step and costs the user nothing per token, so it gets a 4 hour active budget. The Stop button and the repetition guard are unaffected by either budget.
"""

from __future__ import annotations

from typing import Any, Optional

AGENT_RUN_MAX_ACTIVE_SECONDS = 1200
LOCAL_AGENT_RUN_MAX_ACTIVE_SECONDS = 4 * 60 * 60
WORKFLOW_WALLCLOCK_LIMIT_SECONDS = 1500
# The wall-clock guard must outlast the active budget plus the finalization reserve, otherwise it would cut a long local run short.
LOCAL_WORKFLOW_WALLCLOCK_LIMIT_SECONDS = LOCAL_AGENT_RUN_MAX_ACTIVE_SECONDS + 300


def is_local_model_id(model_id: Optional[Any]) -> bool:
    """True when the registry lists the model as running on this machine; an unknown or missing id is treated as not local."""
    if not isinstance(model_id, str) or not model_id:
        return False
    try:
        from api.core.models.models_registry.schema import get_model

        return (get_model(model_id) or {}).get("location") == "local"
    except Exception:
        return False


def agent_run_max_active_seconds(model_id: Optional[Any] = None) -> int:
    return LOCAL_AGENT_RUN_MAX_ACTIVE_SECONDS if is_local_model_id(model_id) else AGENT_RUN_MAX_ACTIVE_SECONDS


def workflow_wallclock_limit_seconds(model_id: Optional[Any] = None) -> int:
    return LOCAL_WORKFLOW_WALLCLOCK_LIMIT_SECONDS if is_local_model_id(model_id) else WORKFLOW_WALLCLOCK_LIMIT_SECONDS


def active_time_limit_message(budget_seconds: float | None = None) -> str:
    seconds = AGENT_RUN_MAX_ACTIVE_SECONDS if budget_seconds is None else budget_seconds
    if seconds >= 3600:
        hours = float(seconds) / 3600.0
        amount = f"{hours:g} hour(s)"
    else:
        amount = f"{max(1, int(round(float(seconds) / 60.0)))} minute(s)"
    return (
        f"Basil stopped this task after {amount} of active work. "
        "Time spent waiting for approvals or your input was not counted."
    )
