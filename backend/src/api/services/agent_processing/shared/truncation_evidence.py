"""Shared JSON-safe truncation and coverage evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class TruncationEvidence:
    """Evidence that an input/output was shortened or only partially covered."""

    source: str
    original_length: Optional[int] = None
    retained_length: Optional[int] = None
    omitted_count: Optional[int] = None
    has_more: Optional[bool] = None
    affects_coverage: bool = True
    reason: str = "limit"
    continuation_hint: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return {key: value for key, value in data.items() if value is not None and value != {}}


def normalize_truncation_evidence(raw: Any) -> List[Dict[str, Any]]:
    """Coerce truncation evidence-like values into JSON-safe dictionaries."""
    if raw is None:
        return []
    if isinstance(raw, TruncationEvidence):
        return [raw.to_dict()]
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        out: List[Dict[str, Any]] = []
        for item in raw:
            out.extend(normalize_truncation_evidence(item))
        return out
    return []


def append_truncation_evidence(target: Dict[str, Any], evidence: Any) -> Dict[str, Any]:
    """Append evidence to ``target['truncation_evidence']`` without mutating callers unexpectedly."""
    merged = dict(target or {})
    existing = normalize_truncation_evidence(merged.get("truncation_evidence"))
    additions = normalize_truncation_evidence(evidence)
    if existing or additions:
        merged["truncation_evidence"] = [*existing, *additions]
    return merged


def context_with_truncation_evidence(context: Dict[str, Any], evidence: Any) -> Dict[str, Any]:
    """Append evidence to a context dictionary in place and return it."""
    if context is None:
        return {}
    existing = normalize_truncation_evidence(context.get("truncation_evidence"))
    additions = normalize_truncation_evidence(evidence)
    if existing or additions:
        context["truncation_evidence"] = [*existing, *additions]
    return context


__all__ = [
    "TruncationEvidence",
    "append_truncation_evidence",
    "context_with_truncation_evidence",
    "normalize_truncation_evidence",
]
