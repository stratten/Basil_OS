"""Pure rules that turn a resource snapshot into advice. Rules only read; they never change a setting."""

from __future__ import annotations

import re
from typing import List, Optional

from .models import (
    ANALYSIS_LAG_SECONDS,
    CPU_PERCENT_THRESHOLD,
    LAG_ADVICE_SECONDS,
    LAG_CRITICAL_SECONDS,
    LARGE_MODEL_RAM_FRACTION,
    MEMORY_PERCENT_THRESHOLD,
    RULE_ORDER,
    SEVERITY_RANK,
    Advice,
    ResourceSnapshot,
)

_SIZE_PATTERN = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(KB|MB|GB|TB)\s*$", re.IGNORECASE)
_UNIT_GB = {"KB": 1.0 / (1024 * 1024), "MB": 1.0 / 1024, "GB": 1.0, "TB": 1024.0}


def parse_model_size_gb(size: object) -> Optional[float]:
    """Gigabytes for a registry size string such as ``1.93GB`` or ``640MB``; ``None`` when it cannot be read."""
    if not isinstance(size, str):
        return None
    match = _SIZE_PATTERN.match(size)
    if match is None:
        return None
    return float(match.group(1)) * _UNIT_GB[match.group(2).upper()]


def _lag_bucket(lag_seconds: float) -> int:
    return max(10, int(lag_seconds // 10) * 10)


def _thermal_advice(snapshot: ResourceSnapshot) -> Optional[Advice]:
    if snapshot.thermal_state not in ("serious", "critical"):
        return None
    return Advice(
        id="thermal",
        severity="critical" if snapshot.thermal_state == "critical" else "warning",
        title="Your Mac is running hot",
        detail="macOS is slowing the processor to cool down, which can make transcription fall behind. Move to a cooler spot or close busy apps.",
    )


def _lag_advice(snapshot: ResourceSnapshot) -> Optional[Advice]:
    if snapshot.lag_seconds < LAG_ADVICE_SECONDS:
        return None
    return Advice(
        id="transcription_lag",
        severity="critical" if snapshot.lag_seconds >= LAG_CRITICAL_SECONDS else "warning",
        title="Transcription is behind the meeting",
        detail=f"Transcription is more than {_lag_bucket(snapshot.lag_seconds)} seconds behind. Choose a smaller transcription model in Settings, or close busy apps.",
        action="open_settings",
    )


def _companion_capacity_advice(snapshot: ResourceSnapshot) -> Optional[Advice]:
    if snapshot.companion_capacity == "paused":
        reason = f" ({snapshot.companion_reason})" if snapshot.companion_reason else ""
        return Advice(
            id="companion_capacity",
            severity="warning",
            title="The Companion is paused",
            detail=f"It stopped until transcription catches up{reason}.",
        )
    if snapshot.companion_capacity == "deferred":
        return Advice(
            id="companion_capacity",
            severity="info",
            title="The Companion is answering less often",
            detail="It is skipping optional work until transcription catches up.",
        )
    return None


def _memory_advice(snapshot: ResourceSnapshot) -> Optional[Advice]:
    if snapshot.memory_percent < MEMORY_PERCENT_THRESHOLD:
        return None
    return Advice(
        id="memory_pressure",
        severity="warning",
        title="Your Mac is low on memory",
        detail="Memory use is above 90 percent, which can slow transcription. Quit apps you are not using.",
    )


def _cpu_advice(snapshot: ResourceSnapshot) -> Optional[Advice]:
    if snapshot.cpu_percent < CPU_PERCENT_THRESHOLD:
        return None
    return Advice(
        id="cpu_saturated",
        severity="warning",
        title="Your Mac is working at its limit",
        detail="Processor use is above 90 percent. Close busy apps, or choose a smaller model in Settings.",
        action="open_settings",
    )


def _analysis_advice(snapshot: ResourceSnapshot) -> Optional[Advice]:
    if not snapshot.analysis_running or snapshot.lag_seconds < ANALYSIS_LAG_SECONDS:
        return None
    return Advice(
        id="analysis_running",
        severity="info",
        title="An analysis is running during the recording",
        detail="Analyses compete with transcription for the processor. Let it finish before starting another.",
    )


def _large_model_advice(snapshot: ResourceSnapshot) -> Optional[Advice]:
    size = snapshot.companion_model_size_gb
    total = snapshot.total_memory_gb
    if size is None or total <= 0 or size < total * LARGE_MODEL_RAM_FRACTION:
        return None
    return Advice(
        id="companion_model_large",
        severity="info",
        title="The Companion model is large for this Mac",
        detail=f"The selected local model needs about {size:.1f} GB of {total:.0f} GB of memory. A smaller model leaves more room for transcription.",
    )


_RULES = (
    _thermal_advice,
    _lag_advice,
    _companion_capacity_advice,
    _memory_advice,
    _cpu_advice,
    _analysis_advice,
    _large_model_advice,
)


def evaluate_rules(snapshot: ResourceSnapshot) -> List[Advice]:
    """Every rule that currently holds, most severe first and then in a fixed rule order. Nothing applies unless recording."""
    if not snapshot.recording:
        return []
    found = [advice for rule in _RULES if (advice := rule(snapshot)) is not None]
    return sorted(found, key=lambda advice: (SEVERITY_RANK[advice.severity], RULE_ORDER.index(advice.id)))
