"""Progress-aware tool run tracking for Agent Task execution.

The registry only declares a run stale when it can reconcile that verdict: either the tool already returned (and only the callback is missing), or the tool declared its own timeout, overran it well past its own bound, and exposed a cancel handle the heartbeat can use to stop it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

WAIT_STATUSES = {"approval_waiting", "input_waiting", "waiting"}
ACTIVE_STATUSES = {
    "active",
    "approval_waiting",
    "input_waiting",
    "waiting",
    "service_running",
    "serializing",
    "returned",
}
DECLARED_TIMEOUT_MULTIPLIER = 2.0
DECLARED_TIMEOUT_GRACE_SECONDS = 30.0
RETURNED_WITHOUT_CALLBACK_SECONDS = 15.0

_monotonic = time.monotonic


def _now() -> float:
    return _monotonic()


class ToolRunWatchdogStopped(RuntimeError):
    """Raised inside the tool wrapper when the watchdog canceled the service call."""


@dataclass
class ActiveToolRun:
    """Runtime-only state for one LangChain tool run."""

    run_id: str
    agent_task_id: str
    step_id: str
    tool_name: str
    description: str
    started_at_monotonic: float = field(default_factory=_now)
    last_progress_at_monotonic: float = field(default_factory=_now)
    status: str = "active"
    progress_kind: str = "started"
    expected_silence_seconds: float = 90.0
    hard_ceiling_seconds: float = 300.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    excluded_wait_seconds: float = 0.0
    wait_started_at_monotonic: Optional[float] = None
    declared_timeout_seconds: Optional[float] = None
    cancel_handle: Optional[Any] = field(default=None, repr=False)
    force_cancel_reason: Optional[str] = None

    def mark(self, status: str, progress_kind: str, **metadata: Any) -> None:
        now = _monotonic()
        if status in WAIT_STATUSES:
            if self.wait_started_at_monotonic is None:
                self.wait_started_at_monotonic = now
        elif self.wait_started_at_monotonic is not None:
            self.excluded_wait_seconds += max(0.0, now - self.wait_started_at_monotonic)
            self.wait_started_at_monotonic = None
        declared_timeout = metadata.get("timeout_seconds")
        if isinstance(declared_timeout, (int, float)) and not isinstance(declared_timeout, bool) and declared_timeout > 0:
            self.declared_timeout_seconds = float(declared_timeout)
        self.status = status
        self.progress_kind = progress_kind
        self.last_progress_at_monotonic = now
        self.metadata.update({k: v for k, v in metadata.items() if v is not None})

    @property
    def elapsed_seconds(self) -> float:
        return _monotonic() - self.started_at_monotonic

    @property
    def silence_seconds(self) -> float:
        return _monotonic() - self.last_progress_at_monotonic

    @property
    def active_elapsed_seconds(self) -> float:
        now = _monotonic()
        open_wait = now - self.wait_started_at_monotonic if self.wait_started_at_monotonic is not None else 0.0
        return max(0.0, (now - self.started_at_monotonic) - self.excluded_wait_seconds - max(0.0, open_wait))

    @property
    def declared_ceiling_seconds(self) -> Optional[float]:
        if self.declared_timeout_seconds is None:
            return None
        return self.declared_timeout_seconds * DECLARED_TIMEOUT_MULTIPLIER + DECLARED_TIMEOUT_GRACE_SECONDS


@dataclass
class WatchdogAssessment:
    """Result of reconciling a tool run with progress facts."""

    status: str
    message: str
    should_continue: bool = True
    stale_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def _format_quiet_duration(seconds: float) -> str:
    whole = int(max(0.0, seconds))
    if whole < 120:
        return f"{whole}s"
    return f"{whole // 60}m"


class ActiveToolRunRegistry:
    """Process-local registry shared by callbacks and service wrappers."""

    def __init__(self) -> None:
        self._runs_by_id: Dict[str, ActiveToolRun] = {}

    def register(
        self,
        *,
        run_id: str,
        agent_task_id: str,
        step_id: str,
        tool_name: str,
        description: str,
        expected_silence_seconds: Optional[float] = None,
        hard_ceiling_seconds: Optional[float] = None,
    ) -> ActiveToolRun:
        tool_lower = (tool_name or "").lower()
        silence = expected_silence_seconds
        ceiling = hard_ceiling_seconds
        if silence is None:
            silence = 120.0 if "shell" in tool_lower else 90.0
        if ceiling is None:
            ceiling = 420.0 if "applescript" in tool_lower else 300.0

        run = ActiveToolRun(
            run_id=str(run_id),
            agent_task_id=agent_task_id,
            step_id=step_id,
            tool_name=tool_name,
            description=description,
            expected_silence_seconds=silence,
            hard_ceiling_seconds=ceiling,
        )
        self._runs_by_id[run.run_id] = run
        return run

    def get(self, run_id: str) -> Optional[ActiveToolRun]:
        return self._runs_by_id.get(str(run_id))

    def mark_completed(self, run_id: str, **metadata: Any) -> None:
        run = self.get(run_id)
        if run:
            run.mark("completed", "callback_completed", **metadata)
            self._runs_by_id.pop(str(run_id), None)

    def mark_failed(self, run_id: str, **metadata: Any) -> None:
        run = self.get(run_id)
        if run:
            run.mark("failed", "callback_failed", **metadata)
            self._runs_by_id.pop(str(run_id), None)

    def discard(self, run_id: str) -> None:
        self._runs_by_id.pop(str(run_id), None)

    def latest_active_run(self, *, agent_task_id: Optional[str], tool_name: str) -> Optional[ActiveToolRun]:
        if not agent_task_id:
            return None
        candidates = [
            run
            for run in self._runs_by_id.values()
            if run.agent_task_id == agent_task_id
            and run.tool_name == tool_name
            and run.status in ACTIVE_STATUSES
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.started_at_monotonic)

    def mark_latest_for_tool(
        self,
        *,
        agent_task_id: Optional[str],
        tool_name: str,
        status: str,
        progress_kind: str,
        **metadata: Any,
    ) -> Optional[ActiveToolRun]:
        run = self.latest_active_run(agent_task_id=agent_task_id, tool_name=tool_name)
        if run is None:
            return None
        run.mark(status, progress_kind, **metadata)
        return run

    def attach_cancel_handle(
        self,
        *,
        agent_task_id: Optional[str],
        tool_name: str,
        handle: Any,
    ) -> Optional[ActiveToolRun]:
        run = self.latest_active_run(agent_task_id=agent_task_id, tool_name=tool_name)
        if run is not None:
            run.cancel_handle = handle
            run.force_cancel_reason = None
        return run

    def detach_cancel_handle(self, run: Optional[ActiveToolRun]) -> None:
        if run is not None:
            run.cancel_handle = None

    def force_cancel(self, run_id: str, *, reason: str) -> bool:
        """Cancel the service call behind ``run_id``; True when a live handle was canceled."""
        run = self.get(run_id)
        if run is None:
            return False
        handle = run.cancel_handle
        done = getattr(handle, "done", None)
        cancel = getattr(handle, "cancel", None)
        if handle is None or not callable(cancel) or (callable(done) and done()):
            return False
        run.force_cancel_reason = str(reason)
        cancel()
        return True

    def assess(self, run_id: str) -> WatchdogAssessment:
        run = self.get(run_id)
        if run is None:
            return WatchdogAssessment(
                status="missing",
                message="Tool run is no longer active.",
                should_continue=False,
            )

        if run.status == "approval_waiting":
            return WatchdogAssessment(
                status="approval_waiting",
                message=f"Waiting for approval: {run.description}",
                metadata=dict(run.metadata),
            )

        if run.status == "input_waiting":
            return WatchdogAssessment(
                status="input_waiting",
                message=f"Waiting for your input: {run.description}",
                metadata=dict(run.metadata),
            )

        if run.status == "waiting":
            return WatchdogAssessment(
                status="waiting",
                message=f"Waiting before checking again: {run.description}",
                metadata=dict(run.metadata),
            )

        if run.status == "returned":
            if run.silence_seconds > RETURNED_WITHOUT_CALLBACK_SECONDS:
                return WatchdogAssessment(
                    status="stale",
                    message="Tool returned; waiting for agent result propagation.",
                    should_continue=False,
                    stale_reason="tool_returned_without_callback",
                    metadata=dict(run.metadata),
                )
            return WatchdogAssessment(
                status="returned",
                message="Tool returned; waiting for agent result propagation...",
                metadata=dict(run.metadata),
            )

        declared_ceiling = run.declared_ceiling_seconds
        if declared_ceiling is not None and run.active_elapsed_seconds > declared_ceiling:
            if run.cancel_handle is not None:
                return WatchdogAssessment(
                    status="stale",
                    message=f"Tool run exceeded its own time limit and was stopped: {run.description}",
                    should_continue=False,
                    stale_reason="declared_timeout_exceeded",
                    metadata=dict(run.metadata),
                )
            return WatchdogAssessment(
                status="unresponsive",
                message=f"Still working past its time limit ({_format_quiet_duration(run.active_elapsed_seconds)}): {run.description}",
                metadata={**run.metadata, "unresponsive": True},
            )

        if run.silence_seconds > run.expected_silence_seconds:
            return WatchdogAssessment(
                status="quiet",
                message=f"Still working (no progress reported for {_format_quiet_duration(run.silence_seconds)}): {run.description}",
                metadata=dict(run.metadata),
            )

        return WatchdogAssessment(
            status=run.status,
            message=f"Still working: {run.description}",
            metadata=dict(run.metadata),
        )

    def stale_runs(self) -> list[ActiveToolRun]:
        stale: list[ActiveToolRun] = []
        for run in list(self._runs_by_id.values()):
            assessment = self.assess(run.run_id)
            if assessment.status == "stale":
                stale.append(run)
        return stale

    def clear_agent_task(self, agent_task_id: str) -> None:
        for run_id, run in list(self._runs_by_id.items()):
            if run.agent_task_id == agent_task_id:
                self._runs_by_id.pop(run_id, None)


_GLOBAL_TOOL_RUN_REGISTRY = ActiveToolRunRegistry()


def get_tool_run_registry() -> ActiveToolRunRegistry:
    return _GLOBAL_TOOL_RUN_REGISTRY


def record_tool_progress(
    *,
    agent_task_id: Optional[str],
    tool_name: str,
    status: str,
    progress_kind: str,
    **metadata: Any,
) -> Optional[ActiveToolRun]:
    return _GLOBAL_TOOL_RUN_REGISTRY.mark_latest_for_tool(
        agent_task_id=agent_task_id,
        tool_name=tool_name,
        status=status,
        progress_kind=progress_kind,
        **metadata,
    )


def attach_tool_cancel_handle(
    *,
    agent_task_id: Optional[str],
    tool_name: str,
    handle: Any,
) -> Optional[ActiveToolRun]:
    return _GLOBAL_TOOL_RUN_REGISTRY.attach_cancel_handle(
        agent_task_id=agent_task_id,
        tool_name=tool_name,
        handle=handle,
    )


def detach_tool_cancel_handle(run: Optional[ActiveToolRun]) -> None:
    _GLOBAL_TOOL_RUN_REGISTRY.detach_cancel_handle(run)
