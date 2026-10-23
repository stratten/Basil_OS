"""Pluggable capacity protection: restricts Companion work, never touches transcription."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, FrozenSet, Iterable, Optional, Protocol

from .gate import ALL_TRIGGERS, DEFERRED_TRIGGERS
from .models import CapacityState

_RANK = {"ok": 0, "deferred": 1, "paused": 2}


@dataclass(frozen=True)
class CapacityAssessment:
    state: CapacityState
    reason: Optional[str]
    lag_seconds: float


class CapacityGuard(Protocol):
    def assess(self, now: float) -> CapacityAssessment: ...


def allowed_triggers(state: CapacityState) -> FrozenSet[str]:
    if state == "ok":
        return ALL_TRIGGERS
    if state == "deferred":
        return DEFERRED_TRIGGERS
    return frozenset()


def prefetch_allowed(state: CapacityState) -> bool:
    return state == "ok"


def recorder_lag_provider(list_recorders: Callable[[], Iterable[Any]]) -> Callable[[], float]:
    """Largest ``transcription_lag_seconds`` across the live recorders; missing or invalid values read as zero."""

    def provider() -> float:
        largest = 0.0
        for recorder in list_recorders():
            try:
                value = float(getattr(recorder, "transcription_lag_seconds", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            largest = max(largest, value)
        return largest

    return provider


class LagCapacityGuard:
    """Maps transcription lag to ok, deferred or paused with hysteresis and a sustain window before escalating."""

    def __init__(
        self,
        lag_provider: Callable[[], float],
        *,
        defer_lag_seconds: float = 8.0,
        pause_lag_seconds: float = 25.0,
        recover_ratio: float = 0.6,
        sustain_seconds: float = 4.0,
    ) -> None:
        self._lag_provider = lag_provider
        self._defer = defer_lag_seconds
        self._pause = pause_lag_seconds
        self._recover_ratio = recover_ratio
        self._sustain = sustain_seconds
        self._state: CapacityState = "ok"
        self._candidate: Optional[CapacityState] = None
        self._candidate_since: Optional[float] = None

    def assess(self, now: float) -> CapacityAssessment:
        try:
            lag = max(0.0, float(self._lag_provider()))
        except Exception:
            lag = 0.0
        if lag >= self._pause:
            target: CapacityState = "paused"
        elif lag >= self._defer:
            target = "deferred"
        else:
            target = "ok"
        if _RANK[target] > _RANK[self._state]:
            if self._candidate != target:
                self._candidate = target
                self._candidate_since = now
            if self._candidate_since is not None and now - self._candidate_since >= self._sustain:
                self._state = target
                self._candidate = None
                self._candidate_since = None
        else:
            self._candidate = None
            self._candidate_since = None
            if self._state == "paused" and lag < self._pause * self._recover_ratio:
                self._state = "deferred" if lag >= self._defer * self._recover_ratio else "ok"
            elif self._state == "deferred" and lag < self._defer * self._recover_ratio:
                self._state = "ok"
        reason = None if self._state == "ok" else f"Transcription is running {lag:.0f}s behind real time"
        return CapacityAssessment(state=self._state, reason=reason, lag_seconds=lag)
