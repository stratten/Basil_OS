"""Fields that explain an execution approval to the user.

The same dictionary is persisted in the approval's ``render_context`` and sent in the ``execution_approval_request`` event, so an approval recovered after a reload looks identical to the live one.
"""

from typing import Any, Dict, Mapping

from .whitelist_eligibility import (
    REMEMBERABLE_EXECUTION_TYPE,
    WhitelistEligibility,
    assess_whitelist_eligibility,
    normalize_purpose,
    normalize_whitelist_advice,
)

_PASSTHROUGH_TEXT_FIELDS = ("script_path", "script_sha256", "script_notice")


def context_whitelist_eligibility(command: str, generalized_pattern: str, context: Mapping[str, Any]) -> WhitelistEligibility:
    """Eligibility for an approval being requested with the given caller context."""
    execution_type = context.get("execution_type", REMEMBERABLE_EXECUTION_TYPE)
    return assess_whitelist_eligibility(command, generalized_pattern, execution_type=str(execution_type))


def record_whitelist_eligibility(record: Mapping[str, Any]) -> WhitelistEligibility:
    """Eligibility for a persisted approval record, used when the user's decision arrives."""
    return assess_whitelist_eligibility(
        str(record.get("command") or ""),
        str(record.get("generalized_pattern") or "") or None,
        execution_type=str(record.get("execution_type") or REMEMBERABLE_EXECUTION_TYPE),
    )


def approval_presentation_fields(
    command: str,
    generalized_pattern: str,
    context: Mapping[str, Any],
) -> Dict[str, Any]:
    """Build the explanation, remember eligibility, and script metadata for one approval card."""
    eligibility = context_whitelist_eligibility(command, generalized_pattern, context)
    purpose = normalize_purpose(context.get("purpose"))
    fields: Dict[str, Any] = {
        "whitelist": {
            "eligible": eligibility.eligible,
            "reason": eligibility.reason,
            "advice": normalize_whitelist_advice(context.get("whitelist_advice"), eligibility, purpose=purpose),
        }
    }
    if purpose is not None:
        fields["purpose"] = purpose
    elif context.get("purpose_required"):
        fields["purpose_missing"] = True
    for key in _PASSTHROUGH_TEXT_FIELDS:
        value = context.get(key)
        if isinstance(value, str) and value:
            fields[key] = value
    return fields
