"""Pieces the replay script uses to compare a baseline with tuning candidates: recorded model responses and the comparison table."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from .replay import ReplayReport
from .replay_scoring import ReplayScore, improves


class RecordingCaller:
    """Wraps the real structured-model call and keeps each parsed response, so a later replay can reuse them without calling a model."""

    def __init__(self, inner: Callable[..., Awaitable[Any]]) -> None:
        self._inner = inner
        self.responses: List[Dict[str, Any]] = []

    async def __call__(self, model: Any, *, prompt: str, response_model: Any, max_tokens: int) -> Any:
        response = await self._inner(model, prompt=prompt, response_model=response_model, max_tokens=max_tokens)
        self.responses.append(response.value.model_dump(mode="json"))
        return response

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.responses, indent=2), encoding="utf-8")


class RecordedCaller:
    """Answers evaluations from saved responses in order. Valid only where the gate fires at the same moments as when they were recorded and the prompt is unchanged, which holds for a confidence-floor candidate but not for gate or prompt changes."""

    def __init__(self, responses: Sequence[Dict[str, Any]]) -> None:
        self._responses = list(responses)
        self._next = 0

    @classmethod
    def load(cls, path: Path) -> "RecordedCaller":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"{path} must hold a JSON list of recorded responses")
        return cls(data)

    async def __call__(self, model: Any, *, prompt: str, response_model: Any, max_tokens: int) -> Any:
        if self._next >= len(self._responses):
            raise RuntimeError("The recorded responses ran out before the replay did")
        raw = self._responses[self._next]
        self._next += 1
        return SimpleNamespace(value=response_model.model_validate(raw), finish_reason=None)


@dataclass
class ComparisonRow:
    name: str
    evaluations: int
    score: ReplayScore


def row_for(name: str, report: ReplayReport, score: ReplayScore) -> ComparisonRow:
    return ComparisonRow(name=name, evaluations=len(report.steps), score=score)


def format_comparison(rows: Sequence[ComparisonRow]) -> str:
    """One line per variant; every candidate after the first row is judged against the first, the baseline."""
    if not rows:
        return "nothing to compare"
    baseline = rows[0]
    header = f"{'variant':<16} {'evals':>5} {'notes':>5} {'agreed hit':>11} {'silence broken':>15} {'other notes':>11}  verdict"
    lines = [header]
    for row in rows:
        score = row.score
        verdict = "baseline" if row is baseline else ("APPLY: more agreed moments, no more notes on 'not needed'" if improves(baseline.score, score) else "do not apply")
        lines.append(
            f"{row.name:<16} {row.evaluations:>5} {score.items:>5} {f'{score.agreed_matched}/{score.agreed_total}':>11} "
            f"{f'{score.disagreed_hit}/{score.disagreed_total}':>15} {score.unmatched_items:>11}  {verdict}"
        )
    if baseline.score.agreed_total == 0:
        lines.append("No finding in this meeting is marked Good catch yet, so no candidate can be shown to help. Run an audit, mark its findings, and replay again.")
    return "\n".join(lines)


def load_marked_moments(snapshot: Optional[Any]) -> List[Any]:
    """The audit findings saved with a meeting; empty when there is no audit."""
    audit = getattr(snapshot, "audit", None)
    return list(audit.moments) if audit is not None else []
