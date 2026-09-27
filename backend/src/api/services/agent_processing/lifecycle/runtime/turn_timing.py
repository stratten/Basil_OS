"""Per-turn stage timing for agent tasks.

Records wall-clock spans for each pipeline stage of a single agent turn and
emits one structured summary line so latency is measurable without hand-
grepping the log. Dependency-free and failure-isolated: timing must never
affect task execution.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)

TURN_TIMING_CONTEXT_KEY = "turn_timing"


@dataclass
class TurnTiming:
    agent_task_id: Optional[str] = None
    root_task_id: Optional[str] = None
    created_at: float = field(default_factory=time.monotonic)
    _open: Dict[str, float] = field(default_factory=dict)
    spans_ms: Dict[str, float] = field(default_factory=dict)

    def start(self, stage: str) -> None:
        self._open[stage] = time.monotonic()

    def stop(self, stage: str) -> None:
        started = self._open.pop(stage, None)
        if started is None:
            return
        self.spans_ms[stage] = round((time.monotonic() - started) * 1000.0, 1)

    def mark_point(self, name: str) -> None:
        """Record ms since turn creation (for one-off milestones, e.g. first token).

        First write wins so repeated calls keep the earliest occurrence.
        """
        if name in self.spans_ms:
            return
        self.spans_ms[name] = round((time.monotonic() - self.created_at) * 1000.0, 1)

    def total_ms(self) -> float:
        return round((time.monotonic() - self.created_at) * 1000.0, 1)

    def summary_dict(self) -> Dict[str, float]:
        data = dict(self.spans_ms)
        data["total"] = self.total_ms()
        return data

    def emit(self) -> None:
        try:
            parts = " ".join(f"{k}={v}ms" for k, v in self.summary_dict().items())
            logger.info(
                "TURN_TIMING agent_task_id=%s root=%s %s",
                self.agent_task_id, self.root_task_id, parts,
            )
        except Exception:
            pass


def get_or_create_turn_timing(context: Optional[dict]) -> Optional["TurnTiming"]:
    if not isinstance(context, dict):
        return None
    existing = context.get(TURN_TIMING_CONTEXT_KEY)
    if isinstance(existing, TurnTiming):
        return existing
    timing = TurnTiming(
        agent_task_id=context.get("agent_task_id"),
        root_task_id=context.get("root_task_id"),
    )
    context[TURN_TIMING_CONTEXT_KEY] = timing
    return timing
