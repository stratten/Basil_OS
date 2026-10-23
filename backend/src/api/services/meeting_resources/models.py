"""Models and thresholds for the Notetaker resource advisor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict

AdviceSeverity = Literal["info", "warning", "critical"]
AdviceAction = Literal["open_settings", "none"]

SAMPLE_INTERVAL_SECONDS = 5.0
SUSTAIN_SECONDS = 20.0
CLEAR_SECONDS = 20.0
THERMAL_REPORT_TTL_SECONDS = 120.0
LAG_ADVICE_SECONDS = 15.0
LAG_CRITICAL_SECONDS = 45.0
ANALYSIS_LAG_SECONDS = 8.0
MEMORY_PERCENT_THRESHOLD = 90.0
CPU_PERCENT_THRESHOLD = 90.0
LARGE_MODEL_RAM_FRACTION = 0.5
MAX_ADVICE_SHOWN = 3
VALID_THERMAL_STATES = ("nominal", "fair", "serious", "critical")

SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}
RULE_ORDER = (
    "thermal",
    "transcription_lag",
    "companion_capacity",
    "memory_pressure",
    "cpu_saturated",
    "analysis_running",
    "companion_model_large",
)


class Advice(BaseModel):
    """One piece of advice shown to the user while recording."""

    model_config = ConfigDict(extra="forbid")

    id: str
    severity: AdviceSeverity
    title: str
    detail: str
    action: AdviceAction = "none"
    raised_at: float = 0.0


class ResourceAdviceState(BaseModel):
    """The advice currently visible, with a revision that increases whenever the visible set changes."""

    model_config = ConfigDict(extra="forbid")

    revision: int = 0
    advice: List[Advice] = []


@dataclass(frozen=True)
class ResourceSnapshot:
    """Everything the rules read at one sampling instant."""

    recording: bool = False
    lag_seconds: float = 0.0
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    total_memory_gb: float = 0.0
    thermal_state: Optional[str] = None
    analysis_running: bool = False
    companion_capacity: Optional[str] = None
    companion_reason: Optional[str] = None
    companion_model_size_gb: Optional[float] = None
