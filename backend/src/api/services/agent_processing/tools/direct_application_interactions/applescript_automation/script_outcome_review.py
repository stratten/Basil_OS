"""Structured outcome review helpers for generic script execution."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from api.services.agent_processing.shared.material_operation_receipts import (
    MaterialOperationContractError,
    extract_material_operation_envelope,
)

VALID_VERIFICATION_STATUSES = {
    "not_applicable",
    "verified",
    "unverified",
    "failed",
    "not_reported",
}


@dataclass
class ScriptOutcomeReview:
    """Material-outcome evidence reported by a generated or hand-written script."""

    material_write: bool = False
    verification_status: str = "not_reported"
    summary: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    expected: Dict[str, Any] = field(default_factory=dict)
    actual: Dict[str, Any] = field(default_factory=dict)
    discrepancies: List[str] = field(default_factory=list)
    material_operation: Optional[Dict[str, Any]] = None


def _normalize_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_discrepancies(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _normalize_verification_status(value: Any) -> str:
    if not isinstance(value, str):
        return "not_reported"
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in VALID_VERIFICATION_STATUSES else "not_reported"


def _extract_result_json_line(output: str) -> Optional[str]:
    for line in (output or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("RESULT_JSON:"):
            return stripped.removeprefix("RESULT_JSON:").strip()
    return None


def parse_script_outcome_review(output: str) -> ScriptOutcomeReview:
    """Parse the single structured outcome line emitted by script tools."""
    payload_text = _extract_result_json_line(output)
    if not payload_text:
        return ScriptOutcomeReview()

    try:
        payload = json.loads(payload_text)
    except Exception:
        return ScriptOutcomeReview(
            verification_status="not_reported",
            summary="RESULT_JSON was present but could not be parsed.",
            discrepancies=["Invalid RESULT_JSON payload"],
        )

    if not isinstance(payload, dict):
        return ScriptOutcomeReview(
            verification_status="not_reported",
            summary="RESULT_JSON payload was not an object.",
            discrepancies=["Invalid RESULT_JSON payload type"],
        )

    try:
        material_operation = extract_material_operation_envelope(payload)
    except MaterialOperationContractError as exc:
        return ScriptOutcomeReview(
            material_write=bool(payload.get("material_write", False)),
            verification_status="failed",
            summary="RESULT_JSON material operation receipt is invalid.",
            discrepancies=[str(exc)],
        )
    if material_operation:
        projection = material_operation.to_tool_result_fields()["outcome_review"]
        return ScriptOutcomeReview(
            material_write=True,
            verification_status=projection["verification_status"],
            summary=projection["summary"],
            evidence=projection["evidence"],
            expected=projection["expected"],
            actual=projection["actual"],
            discrepancies=[
                str(discrepancy)
                for discrepancy in projection["discrepancies"]
            ],
            material_operation=material_operation.to_dict(),
        )
    return ScriptOutcomeReview(
        material_write=bool(payload.get("material_write", False)),
        verification_status=_normalize_verification_status(payload.get("verification_status")),
        summary=str(payload.get("summary") or "").strip(),
        evidence=_normalize_dict(payload.get("evidence")),
        expected=_normalize_dict(payload.get("expected")),
        actual=_normalize_dict(payload.get("actual")),
        discrepancies=_normalize_discrepancies(payload.get("discrepancies")),
    )


def detect_semantic_script_error(output: str) -> Optional[str]:
    """Detect explicit script-reported failure envelopes in successful stdout."""
    normalized_output = (output or "").strip()
    if not normalized_output:
        return None

    first_line = normalized_output.splitlines()[0].strip()
    if re.match(r"^(ERROR|Error)\s+-?\d+\s*:", first_line):
        return normalized_output

    error_prefixes = ("ERROR:", "SCRIPT_ERROR:", "MAIN_ERROR:", "VERIFY_ERROR:")
    if first_line.startswith(error_prefixes):
        return normalized_output

    return None


def build_outcome_review_error(review: ScriptOutcomeReview) -> Optional[str]:
    """Return a tool error only when the script explicitly reports failed review."""
    if review.verification_status != "failed":
        return None

    summary = review.summary or "Script reported that the material outcome did not verify."
    if review.discrepancies:
        return f"Script outcome verification failed: {summary}; discrepancies: {', '.join(review.discrepancies)}"
    return f"Script outcome verification failed: {summary}"
