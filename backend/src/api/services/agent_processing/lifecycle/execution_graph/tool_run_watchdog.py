"""Progress-aware tool run tracking for Agent Task execution."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


ACTIVE_STATUSES = {"active", "approval_waiting", "service_running", "serializing", "returned"}


@dataclass
class ActiveToolRun:
    """Runtime-only state for one LangChain tool run."""

    run_id: str
    agent_task_id: str
    step_id: str
    tool_name: str
    description: str
    started_at_monotonic: float = field(default_factory=time.monotonic)
    last_progress_at_monotonic: float = field(default_factory=time.monotonic)
    status: str = "active"
    progress_kind: str = "started"
    expected_silence_seconds: float = 90.0
    hard_ceiling_seconds: float = 300.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def mark(self, status: str, progress_kind: str, **metadata: Any) -> None:
        self.status = status
        self.progress_kind = progress_kind
        self.last_progress_at_monotonic = time.monotonic()
        self.metadata.update({k: v for k, v in metadata.items() if v is not None})

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at_monotonic

    @property
    def silence_seconds(self) -> float:
        return time.monotonic() - self.last_progress_at_monotonic


@dataclass
class WatchdogAssessment:
    """Result of reconciling a tool run with progress facts."""

    status: str
    message: str
    should_continue: bool = True
    stale_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


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

    def mark_latest_for_tool(
        self,
        *,
        agent_task_id: Optional[str],
        tool_name: str,
        status: str,
        progress_kind: str,
        **metadata: Any,
    ) -> Optional[ActiveToolRun]:
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

        run = max(candidates, key=lambda item: item.started_at_monotonic)
        run.mark(status, progress_kind, **metadata)
        return run

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

        if run.status == "returned":
            if run.silence_seconds > 15.0:
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

        if run.elapsed_seconds > run.hard_ceiling_seconds:
            return WatchdogAssessment(
                status="stale",
                message=f"Tool run exceeded safety ceiling: {run.description}",
                should_continue=False,
                stale_reason="hard_ceiling_exceeded",
                metadata=dict(run.metadata),
            )

        if run.silence_seconds > run.expected_silence_seconds:
            return WatchdogAssessment(
                status="stale",
                message=f"Tool run has not reported progress: {run.description}",
                should_continue=False,
                stale_reason="progress_silence_exceeded",
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
