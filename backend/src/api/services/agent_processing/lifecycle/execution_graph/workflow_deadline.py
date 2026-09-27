"""Shared end-to-end deadline accounting for agent workflows."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class WorkflowDeadline:
    """Monotonic end-to-end deadline for one workflow run."""

    started_at: float
    total_seconds: float
    finalization_reserve_seconds: float = 60.0

    @classmethod
    def start(
        cls,
        *,
        total_seconds: float,
        finalization_reserve_seconds: float = 60.0,
    ) -> "WorkflowDeadline":
        return cls(
            started_at=time.monotonic(),
            total_seconds=float(total_seconds),
            finalization_reserve_seconds=float(finalization_reserve_seconds),
        )

    @property
    def expires_at(self) -> float:
        return self.started_at + self.total_seconds

    def remaining_seconds(self) -> float:
        return max(0.0, self.expires_at - time.monotonic())

    def execution_seconds_available(self, *, per_pass_cap_seconds: float) -> float:
        available = self.remaining_seconds() - self.finalization_reserve_seconds
        return max(0.0, min(float(per_pass_cap_seconds), available))

    def can_start_execution(
        self,
        *,
        per_pass_cap_seconds: float,
        minimum_seconds: float = 5.0,
    ) -> bool:
        return self.execution_seconds_available(per_pass_cap_seconds=per_pass_cap_seconds) >= minimum_seconds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "started_at_monotonic": self.started_at,
            "total_seconds": self.total_seconds,
            "remaining_seconds": self.remaining_seconds(),
            "finalization_reserve_seconds": self.finalization_reserve_seconds,
        }


def deadline_from_context(context: Optional[Dict[str, Any]]) -> Optional[WorkflowDeadline]:
    candidate = (context or {}).get("_workflow_deadline")
    return candidate if isinstance(candidate, WorkflowDeadline) else None


def deadline_evidence(deadline: Optional[WorkflowDeadline], *, reason: str) -> Dict[str, Any]:
    if deadline is None:
        return {"reason": reason, "deadline_available": False}
    return {
        "reason": reason,
        "deadline_available": True,
        "deadline": deadline.to_dict(),
    }


__all__ = ["WorkflowDeadline", "deadline_evidence", "deadline_from_context"]
