"""Turn case results into a stored JSON document, a readable table, and a before/after comparison.

The stored document holds only route tokens, verdicts, and task ids, never prompt output or file contents, so a baseline file carries no account data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .route_tokens import FAIL, INCOMPLETE, PASS, PASS_ALT, VERDICTS
from .runner import CaseResult

SCHEMA_VERSION = 1
# Higher is better. INCOMPLETE is unscored, so it never counts as a regression or an improvement.
_RANK = {PASS: 2, PASS_ALT: 1, FAIL: 0}


def build_document(results: Iterable[CaseResult], window_size: int, label: str = "") -> dict[str, Any]:
    models: dict[str, dict[str, Any]] = {}
    for result in results:
        models.setdefault(result.model_id, {})[result.case_id] = {
            "category": result.category,
            "verdict": result.verdict.verdict,
            "reason": result.verdict.reason,
            "route": list(result.verdict.route),
            "first_call": list(result.verdict.first_call),
            "load_calls": result.verdict.load_calls,
            "substantive_calls": result.verdict.substantive_calls,
            "final_status": result.final_status,
            "seconds": round(result.seconds, 1),
            "task_id": result.task_id,
            "error": result.error,
            "auto_approved": result.auto_approved,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label": label,
        "window_size": window_size,
        "models": models,
    }


def summarize(cases: dict[str, Any]) -> dict[str, Any]:
    counts = {verdict: 0 for verdict in VERDICTS}
    for entry in cases.values():
        counts[entry["verdict"]] += 1
    scored = counts[PASS] + counts[PASS_ALT] + counts[FAIL]
    return {
        **counts,
        "scored": scored,
        "accuracy": round((counts[PASS] + counts[PASS_ALT]) / scored, 3) if scored else None,
        "strict_accuracy": round(counts[PASS] / scored, 3) if scored else None,
    }


def render_text(document: dict[str, Any]) -> str:
    lines: list[str] = []
    for model_id, cases in document["models"].items():
        summary = summarize(cases)
        lines.append(f"Model {model_id}: {summary[PASS]} PASS, {summary[PASS_ALT]} PASS_ALT, {summary[FAIL]} FAIL, {summary[INCOMPLETE]} INCOMPLETE (accuracy {_pct(summary['accuracy'])}, strict {_pct(summary['strict_accuracy'])})")
        for case_id, entry in cases.items():
            route = " > ".join(entry["route"]) or "(no tools)"
            detail = entry["error"] or entry["reason"]
            lines.append(f"  {entry['verdict']:<10} {case_id:<28} {route}")
            if entry["verdict"] != PASS:
                lines.append(f"             {detail}")
        lines.append("")
    return "\n".join(lines)


def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


@dataclass(frozen=True)
class Change:
    model_id: str
    case_id: str
    kind: str  # regression | improvement | route_changed
    before: str
    after: str
    before_route: tuple[str, ...]
    after_route: tuple[str, ...]


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> list[Change]:
    """Every case that got worse, got better, or kept its verdict but took a different route. Only cases scored in both runs are compared."""
    changes: list[Change] = []
    for model_id, cases in current["models"].items():
        before_cases = baseline["models"].get(model_id, {})
        for case_id, after in cases.items():
            before = before_cases.get(case_id)
            if before is None or before["verdict"] not in _RANK or after["verdict"] not in _RANK:
                continue
            before_route, after_route = tuple(before["route"]), tuple(after["route"])
            delta = _RANK[after["verdict"]] - _RANK[before["verdict"]]
            if delta < 0:
                kind = "regression"
            elif delta > 0:
                kind = "improvement"
            elif before_route != after_route:
                kind = "route_changed"
            else:
                continue
            changes.append(Change(model_id, case_id, kind, before["verdict"], after["verdict"], before_route, after_route))
    return changes


def has_regression(changes: Iterable[Change]) -> bool:
    return any(change.kind == "regression" for change in changes)


def render_comparison(changes: list[Change], baseline_label: str) -> str:
    if not changes:
        return f"No routing changes against baseline {baseline_label}."
    lines = [f"Changes against baseline {baseline_label}:"]
    for kind in ("regression", "improvement", "route_changed"):
        for change in (c for c in changes if c.kind == kind):
            before = " > ".join(change.before_route) or "(no tools)"
            after = " > ".join(change.after_route) or "(no tools)"
            lines.append(f"  {kind.upper():<13} {change.model_id} / {change.case_id}: {change.before} -> {change.after}")
            lines.append(f"                before: {before}")
            lines.append(f"                after:  {after}")
    return "\n".join(lines)


def save_document(document: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_document(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{path} has schema version {document.get('schema_version')}, expected {SCHEMA_VERSION}")
    return document
