"""Per-call and per-mode timing capture for meeting analysis runs."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from api.core.models.reasoning.model_runtime_profile import (
    resolve_runtime_model_profile,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalysisCallLabel:
    """Identifies which analysis step a model call belongs to."""

    mode: str
    kind: Literal["chunk", "reduction"]
    chunk_index: Optional[int] = None
    chunk_total: Optional[int] = None


class AnalysisCallTiming(BaseModel):
    """One structured model call made while analyzing a meeting."""

    mode: str
    kind: Literal["chunk", "reduction"]
    chunk_index: Optional[int] = None
    chunk_total: Optional[int] = None
    attempt: int = 1
    model_id: str
    max_tokens: int
    estimated_input_tokens: int
    estimated_output_tokens: Optional[int] = None
    provider_usage: Optional[Dict[str, int]] = None
    queued_seconds: float
    started_offset_seconds: float
    duration_seconds: float
    finish_reason: Optional[str] = None
    enforcement: Optional[str] = None
    outcome: Literal["ok", "error"]
    error_category: Optional[str] = None


class AnalysisModeTiming(BaseModel):
    """Wall-clock span of one analysis mode within the run."""

    mode: str
    started_offset_seconds: float
    duration_seconds: float
    call_count: int
    outcome: Literal["ok", "error"]


class AnalysisTimingReport(BaseModel):
    """Saved with the analysis so a run can be compared against a baseline."""

    concurrency_limit: int
    total_seconds: float
    modes: List[AnalysisModeTiming] = Field(default_factory=list)
    calls: List[AnalysisCallTiming] = Field(default_factory=list)


def describe_model_id(model: Any) -> str:
    """Return the registry identity of a model, never raising."""
    try:
        return str(resolve_runtime_model_profile(model).model_id)
    except Exception:
        return str(getattr(model, "model_name", None) or "unknown")


class AnalysisTimingRecorder:
    """Collects call and mode timings for one analysis run."""

    def __init__(self) -> None:
        self._origin = time.monotonic()
        self._calls: List[AnalysisCallTiming] = []
        self._mode_started: Dict[str, float] = {}
        self._mode_finished: Dict[str, Tuple[float, str]] = {}

    def offset(self) -> float:
        """Seconds since the recorder was created."""
        return time.monotonic() - self._origin

    def record_call(self, timing: AnalysisCallTiming) -> None:
        self._calls.append(timing)

    def begin_mode(self, mode: str) -> None:
        self._mode_started.setdefault(mode, self.offset())

    def end_mode(self, mode: str, outcome: Literal["ok", "error"]) -> None:
        self._mode_finished[mode] = (self.offset(), outcome)

    def build_report(self, *, concurrency_limit: int) -> AnalysisTimingReport:
        now = self.offset()
        modes: List[AnalysisModeTiming] = []
        for mode, started in self._mode_started.items():
            finished, outcome = self._mode_finished.get(mode, (now, "error"))
            modes.append(
                AnalysisModeTiming(
                    mode=mode,
                    started_offset_seconds=round(started, 3),
                    duration_seconds=round(max(0.0, finished - started), 3),
                    call_count=sum(1 for call in self._calls if call.mode == mode),
                    outcome=outcome,
                )
            )
        return AnalysisTimingReport(
            concurrency_limit=concurrency_limit,
            total_seconds=round(now, 3),
            modes=modes,
            calls=list(self._calls),
        )


def summarize_report_for_log(report: AnalysisTimingReport) -> str:
    """One-line human summary written to the backend log after each run."""
    parts = [
        f"{mode.mode}={mode.duration_seconds:.1f}s/{mode.call_count}calls/{mode.outcome}"
        for mode in report.modes
    ]
    return (
        f"total={report.total_seconds:.1f}s concurrency={report.concurrency_limit} "
        + " ".join(parts)
    )
