"""Fields that explain an execution approval to the user.

The same dictionary is persisted in the approval's ``render_context`` and sent in the ``execution_approval_request`` event, so an approval recovered after a reload looks identical to the live one.
"""

from typing import Any, Dict, Mapping

from .connected_tool_remember import normalize_tool_policy_scope, tool_policy_scope_of_record
from .whitelist_eligibility import (
    REMEMBERABLE_EXECUTION_TYPE,
    WhitelistEligibility,
    assess_whitelist_eligibility,
    MAX_BASIL_PURPOSE_CHARS,
    MAX_PURPOSE_CHARS,
    normalize_purpose,
    normalize_whitelist_advice,
)
from .whitelist_pattern_selection import is_broad_pattern

_PASSTHROUGH_TEXT_FIELDS = ("script_path", "script_sha256", "script_notice")

PURPOSE_SOURCE_AGENT = "agent"
PURPOSE_SOURCE_BASIL = "basil"
"""Who wrote an approval's explanation. Text the agent supplied is labeled as the agent's; a caller that composes the sentence from facts it holds (the To-Do being closed, the address being connected) sets ``purpose_source`` to ``basil`` so the card does not attribute Basil's own wording to the agent."""


def context_whitelist_eligibility(command: str, generalized_pattern: str, context: Mapping[str, Any]) -> WhitelistEligibility:
    """Eligibility for an approval being requested with the given caller context."""
    execution_type = context.get("execution_type", REMEMBERABLE_EXECUTION_TYPE)
    return assess_whitelist_eligibility(command, generalized_pattern, execution_type=str(execution_type))


def record_whitelist_eligibility(record: Mapping[str, Any]) -> WhitelistEligibility:
    """Eligibility for a persisted approval record, used when the user's decision arrives."""
    if tool_policy_scope_of_record(record) is not None:
        # Remembered through the tool's policy, not as a command pattern, so the pattern rules do not apply.
        return WhitelistEligibility(True)
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
    purpose = normalize_purpose(context.get("purpose"), MAX_BASIL_PURPOSE_CHARS if context.get("purpose_source") == PURPOSE_SOURCE_BASIL else MAX_PURPOSE_CHARS)
    tool_policy = normalize_tool_policy_scope(context.get("remember_tool_policy"))
    fields: Dict[str, Any] = {
        "whitelist": {
            "eligible": eligibility.eligible,
            "reason": eligibility.reason,
            "advice": normalize_whitelist_advice(context.get("whitelist_advice"), eligibility, purpose=purpose),
            # What remembering would store, and whether it would also approve commands unlike this one (a single word the command goes on beyond).
            "pattern": generalized_pattern,
            "broad": eligibility.eligible and is_broad_pattern(generalized_pattern, command),
        }
    }
    if tool_policy is not None:
        # A connected tool is remembered as that one tool's policy, not as a command pattern, so there is no pattern to show and no agent advice about one.
        fields["whitelist"] = {
            "eligible": True,
            "reason": "",
            "advice": None,
            "pattern": "",
            "broad": False,
            "tool_policy": tool_policy,
        }
    if purpose is not None:
        fields["purpose"] = purpose
        fields["purpose_source"] = PURPOSE_SOURCE_BASIL if context.get("purpose_source") == PURPOSE_SOURCE_BASIL else PURPOSE_SOURCE_AGENT
    else:
        # Every approval card must say what the user is approving, so a card that reaches the user without an explanation says so instead of looking complete. Callers that can ask the agent for one set ``purpose_required``, which makes the approval service ask once before the card is shown.
        fields["purpose_missing"] = True
    for key in _PASSTHROUGH_TEXT_FIELDS:
        value = context.get(key)
        if isinstance(value, str) and value:
            fields[key] = value
    return fields
