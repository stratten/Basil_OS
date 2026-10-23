"""The evaluation ledger: a durable record of every Companion evaluation, including the silent ones.

Without it a quiet Companion is indistinguishable from a broken one. Each evaluation writes one ``evaluation`` timeline event holding what the model said it weighed, every candidate it produced with the reason it was kept or dropped, and how often the gate held the evaluation back since the previous one.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

CANDIDATE_TEXT_CHARS = 160
MAX_CONSIDERED_CHARS = 200
MAX_LEDGER_CANDIDATES = 6
# Gate outcomes that mean "nothing to evaluate", which would only add noise to the wait counts.
IGNORED_WAIT_REASONS = frozenset({"idle", ""})

DROP_CONFIDENCE_FLOOR = "confidence_floor"
DROP_DUPLICATE = "duplicate"
DROP_OVER_CAP = "over_cap"
DROP_EMPTY = "empty"
KEPT = "kept"


@dataclass(frozen=True)
class CandidateRecord:
    """One item the model produced and what became of it."""

    kind: str
    text: str
    confidence: float
    outcome: str

    def payload(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text[:CANDIDATE_TEXT_CHARS],
            "confidence": round(self.confidence, 3),
            "outcome": self.outcome,
        }


class GateWaitCounter:
    """Counts why the gate declined to fire between two evaluations."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()

    def note(self, reason: str) -> None:
        if reason in IGNORED_WAIT_REASONS:
            return
        self._counts[reason] += 1

    def take(self) -> Dict[str, int]:
        """The counts since the last call, then reset."""
        counts = dict(self._counts)
        self._counts.clear()
        return counts


def clean_considered(text: Optional[str]) -> str:
    """The model's stated rationale, single-spaced and capped."""
    return " ".join((text or "").split())[:MAX_CONSIDERED_CHARS]


def build_evaluation_payload(
    *,
    trigger: str,
    new_lines: int,
    considered: str,
    candidates: Sequence[CandidateRecord],
    kept: int,
    latency_ms: int,
    finish_reason: Optional[str],
    model_id: Optional[str],
    error: Optional[str],
    gate_waits: Dict[str, int],
    discarded: Optional[str] = None,
) -> Dict[str, Any]:
    """The persisted payload of one ``evaluation`` event. ``discarded`` is set when the result was thrown away (for example ``stale``)."""
    return {
        "trigger": trigger,
        "new_lines": int(new_lines),
        "considered": clean_considered(considered),
        "candidates": [candidate.payload() for candidate in list(candidates)[:MAX_LEDGER_CANDIDATES]],
        "kept": int(kept),
        "latency_ms": int(latency_ms),
        "finish_reason": finish_reason,
        "model_id": model_id,
        "error": (error or None) and str(error)[:300],
        "gate_waits": dict(gate_waits),
        "discarded": discarded,
    }
