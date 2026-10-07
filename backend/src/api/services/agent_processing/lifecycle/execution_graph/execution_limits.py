"""Active-time limit for one run of Basil's inner agent loop."""

from __future__ import annotations

AGENT_RUN_MAX_ACTIVE_SECONDS = 1200


def active_time_limit_message(budget_seconds: float | None = None) -> str:
    seconds = AGENT_RUN_MAX_ACTIVE_SECONDS if budget_seconds is None else budget_seconds
    minutes = max(1, int(round(float(seconds) / 60.0)))
    return (
        f"Basil stopped this task after {minutes} minute(s) of active work. "
        "Time spent waiting for approvals or your input was not counted."
    )
