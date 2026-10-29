"""Shared end-to-end deadline accounting for agent workflows.

The budget counts only active time. Intervals spent waiting on someone else (execution approvals, command-input relays, deliberate agent waits) are excluded, bounded by an absolute wall-clock ceiling so a forgotten pause cannot keep a workflow alive indefinitely.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Dict, Iterator, List, Optional, TypeVar

T = TypeVar("T")

ABSOLUTE_CEILING_MULTIPLIER = 3.0
_CANCEL_SETTLE_SECONDS = 5.0

_monotonic = time.monotonic


@dataclass
class WorkflowDeadline:
    """Pause-aware monotonic deadline for one workflow run."""

    started_at: float
    total_seconds: float
    finalization_reserve_seconds: float = 60.0
    absolute_ceiling_seconds: Optional[float] = None
    _paused_total_seconds: float = field(default=0.0, repr=False)
    _pause_started_at: Optional[float] = field(default=None, repr=False)
    _pause_depth: int = field(default=0, repr=False)
    _pause_reasons: List[str] = field(default_factory=list, repr=False)

    @classmethod
    def start(
        cls,
        *,
        total_seconds: float,
        finalization_reserve_seconds: float = 60.0,
        absolute_ceiling_seconds: Optional[float] = None,
    ) -> "WorkflowDeadline":
        total = float(total_seconds)
        ceiling = (
            float(absolute_ceiling_seconds)
            if absolute_ceiling_seconds is not None
            else total * ABSOLUTE_CEILING_MULTIPLIER
        )
        return cls(
            started_at=_monotonic(),
            total_seconds=total,
            finalization_reserve_seconds=float(finalization_reserve_seconds),
            absolute_ceiling_seconds=max(total, ceiling),
        )

    @property
    def expires_at(self) -> float:
        """Monotonic instant the active budget expires if no further pause occurs."""
        return self.started_at + self.total_seconds + self.paused_seconds()

    @property
    def is_paused(self) -> bool:
        return self._pause_depth > 0

    @property
    def pause_reasons(self) -> List[str]:
        return list(self._pause_reasons)

    def paused_seconds(self, now: Optional[float] = None) -> float:
        current = _monotonic() if now is None else now
        open_pause = (
            current - self._pause_started_at if self._pause_started_at is not None else 0.0
        )
        return self._paused_total_seconds + max(0.0, open_pause)

    def active_elapsed_seconds(self, now: Optional[float] = None) -> float:
        current = _monotonic() if now is None else now
        return max(0.0, (current - self.started_at) - self.paused_seconds(current))

    def begin_pause(self, reason: str) -> None:
        if self._pause_depth == 0:
            self._pause_started_at = _monotonic()
        self._pause_depth += 1
        self._pause_reasons.append(str(reason))

    def end_pause(self, reason: str) -> None:
        if self._pause_depth == 0:
            return
        self._pause_depth -= 1
        with contextlib.suppress(ValueError):
            self._pause_reasons.remove(str(reason))
        if self._pause_depth == 0 and self._pause_started_at is not None:
            self._paused_total_seconds += max(0.0, _monotonic() - self._pause_started_at)
            self._pause_started_at = None

    @contextlib.contextmanager
    def paused(self, reason: str) -> Iterator[None]:
        self.begin_pause(reason)
        try:
            yield
        finally:
            self.end_pause(reason)

    def remaining_seconds(self) -> float:
        now = _monotonic()
        active_remaining = self.total_seconds - self.active_elapsed_seconds(now)
        ceiling = (
            self.absolute_ceiling_seconds
            if self.absolute_ceiling_seconds is not None
            else self.total_seconds
        )
        ceiling_remaining = ceiling - (now - self.started_at)
        return max(0.0, min(active_remaining, ceiling_remaining))

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
            "absolute_ceiling_seconds": self.absolute_ceiling_seconds,
            "active_elapsed_seconds": self.active_elapsed_seconds(),
            "paused_seconds": self.paused_seconds(),
            "is_paused": self.is_paused,
            "pause_reasons": self.pause_reasons,
        }


async def run_within_workflow_deadline(
    awaitable: Awaitable[T],
    deadline: WorkflowDeadline,
    *,
    poll_seconds: float = 1.0,
) -> T:
    """Await ``awaitable`` until the pause-aware deadline is exhausted.

    Raises ``asyncio.TimeoutError`` (the same type ``asyncio.wait_for`` raised before) after canceling the inner work. Paused intervals do not consume the budget; the absolute ceiling still applies while paused.
    """
    task = asyncio.ensure_future(awaitable)
    try:
        while True:
            remaining = deadline.remaining_seconds()
            if remaining <= 0:
                task.cancel()
                await asyncio.wait({task}, timeout=_CANCEL_SETTLE_SECONDS)
                raise asyncio.TimeoutError()
            done, _pending = await asyncio.wait({task}, timeout=min(remaining, poll_seconds))
            if task in done:
                return task.result()
    except asyncio.CancelledError:
        if not task.done():
            task.cancel()
            await asyncio.wait({task}, timeout=_CANCEL_SETTLE_SECONDS)
        raise


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


__all__ = [
    "ABSOLUTE_CEILING_MULTIPLIER",
    "WorkflowDeadline",
    "deadline_evidence",
    "deadline_from_context",
    "run_within_workflow_deadline",
]
