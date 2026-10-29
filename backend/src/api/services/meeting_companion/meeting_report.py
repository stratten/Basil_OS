"""Per-meeting efficacy summaries read from a saved ``companion.json``, so many meetings can be compared side by side.

Everything here is a pure function of the stored events. Nothing is written and no model is called.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

from .models import TimelineEvent
from .timeline import reduce_timeline


def percentile(values: Sequence[float], fraction: float) -> Optional[int]:
    """Nearest-rank percentile of ``values`` rounded to an integer; ``None`` when there are no values."""
    ordered = sorted(values)
    if not ordered:
        return None
    rank = max(1, math.ceil(fraction * len(ordered)))
    return int(round(ordered[min(rank, len(ordered)) - 1]))


def _payloads(events: Sequence[TimelineEvent], kind: str) -> List[Dict[str, Any]]:
    return [event.payload for event in events if event.kind == kind]


def _evaluation_summary(payloads: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    outcomes: Counter[str] = Counter()
    waits: Counter[str] = Counter()
    latencies: List[float] = []
    silent = 0
    errors = 0
    discarded = 0
    for payload in payloads:
        if payload.get("error"):
            errors += 1
        if payload.get("discarded"):
            discarded += 1
        if payload.get("latency_ms") is not None and not payload.get("error"):
            latencies.append(float(payload["latency_ms"]))
        if not payload.get("kept") and not payload.get("error") and not payload.get("discarded"):
            silent += 1
        for candidate in payload.get("candidates") or []:
            outcomes[str(candidate.get("outcome") or "unknown")] += 1
        for reason, count in (payload.get("gate_waits") or {}).items():
            waits[str(reason)] += int(count)
    return {
        "logged": len(payloads),
        "silent": silent,
        "errors": errors,
        "discarded": discarded,
        "candidates": sum(outcomes.values()),
        "candidate_outcomes": dict(outcomes),
        "gate_waits": dict(waits),
        "latency_p50_ms": percentile(latencies, 0.5),
        "latency_p95_ms": percentile(latencies, 0.95),
    }


def _investigation_summary(payloads: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    statuses: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    shown = 0
    for payload in payloads:
        statuses[str(payload.get("status") or "unknown")] += 1
        if payload.get("shown"):
            shown += 1
        elif payload.get("reason"):
            reasons[str(payload["reason"])] += 1
    return {"total": len(payloads), "shown": shown, "statuses": dict(statuses), "withheld_reasons": dict(reasons)}


def _audit_summary(derived: Any) -> Optional[Dict[str, Any]]:
    audit = derived.audit
    if audit is None:
        return None
    marks = Counter(moment.mark or "unmarked" for moment in audit.moments)
    return {
        "scope": audit.scope,
        "moments": len(audit.moments),
        "agreed": marks.get("agree", 0),
        "disagreed": marks.get("disagree", 0),
        "unmarked": marks.get("unmarked", 0),
        "evaluations_at_audit": audit.evaluations,
        "spoke_at_audit": audit.spoke,
    }


def summarize_meeting(meeting_id: str, events: Sequence[TimelineEvent], saved_at: str = "") -> Dict[str, Any]:
    """One row of numbers describing how the Companion behaved in a single meeting."""
    ordered = sorted(events, key=lambda event: event.seq)
    derived = reduce_timeline(ordered)
    duration = max((event.meeting_time for event in ordered), default=0.0)
    runs = _payloads(ordered, "run")
    visible = [item for item in derived.items if item.kind != "proposal"]
    proposals = [item for item in derived.items if item.proposal is not None]
    feedback = Counter(str(payload.get("action")) for payload in _payloads(ordered, "feedback") if not str(payload.get("action", "")).startswith("audit_"))
    status_states = Counter(str(payload.get("capacity") or "ok") for payload in _payloads(ordered, "status"))
    errors = Counter(str(payload.get("code") or "unknown") for payload in _payloads(ordered, "error"))
    hours = duration / 3600.0
    return {
        "meeting_id": meeting_id,
        "saved_at": saved_at,
        "duration_seconds": int(round(duration)),
        "sessions": len(runs),
        "run": runs[-1] if runs else None,
        "notes": len(visible),
        "notes_per_hour": round(len(visible) / hours, 1) if hours >= 0.05 else None,
        "researched_notes": sum(1 for item in visible if item.researched),
        "proposals": {
            "total": len(proposals),
            "by_state": dict(Counter(item.proposal.state for item in proposals if item.proposal)),
        },
        "evaluation_total": derived.evaluation_total,
        "evaluations": _evaluation_summary(_payloads(ordered, "evaluation")),
        "feedback": dict(feedback),
        "capacity_states": dict(status_states),
        "errors": dict(errors),
        "investigations": _investigation_summary(_payloads(ordered, "investigation")),
        "audit": _audit_summary(derived),
    }


def _cell(value: Any) -> str:
    return "-" if value is None or value == "" else str(value)


def _duration_label(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"


def format_table(rows: Sequence[Dict[str, Any]]) -> str:
    """A fixed-width comparison across meetings, oldest first, with a one-line legend."""
    header = ["meeting", "len", "evals", "silent", "notes", "/hr", "floor", "dismiss", "useful", "inv shown/total", "audit +/-/?", "p50ms", "p95ms", "err", "prompt"]
    lines: List[List[str]] = [header]
    for row in rows:
        evaluations = row["evaluations"]
        audit = row["audit"]
        run = row["run"] or {}
        feedback = row["feedback"]
        investigations = row["investigations"]
        lines.append(
            [
                row["meeting_id"][:24],
                _duration_label(row["duration_seconds"]),
                _cell(row["evaluation_total"]),
                _cell(evaluations["silent"]),
                _cell(row["notes"]),
                _cell(row["notes_per_hour"]),
                _cell(evaluations["candidate_outcomes"].get("confidence_floor", 0)),
                _cell(feedback.get("dismissed", 0)),
                _cell(feedback.get("useful", 0)),
                f"{investigations['shown']}/{investigations['total']}",
                f"{audit['agreed']}/{audit['disagreed']}/{audit['unmarked']}" if audit else "-",
                _cell(evaluations["latency_p50_ms"]),
                _cell(evaluations["latency_p95_ms"]),
                _cell(sum(row["errors"].values())),
                _cell(run.get("prompt_hash")),
            ]
        )
    widths = [max(len(line[column]) for line in lines) for column in range(len(header))]
    body = ["  ".join(cell.ljust(widths[column]) for column, cell in enumerate(line)).rstrip() for line in lines]
    legend = "silent = evaluations that kept nothing; floor = candidates dropped under the confidence floor; audit = agreed/disagreed/unmarked findings; err = error events."
    return "\n".join(body + ["", legend])
