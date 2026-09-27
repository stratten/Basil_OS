"""Compact, claim-safe evidence briefs for material-operation receipts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

from .material_operation_receipts import extract_material_operation_envelope


_MAX_EFFECTS_PER_STATUS = 6


@dataclass(frozen=True)
class MaterialEffectSummary:
    """Distinct material effects grouped by their observed verification outcome."""

    verified_effects: Tuple[str, ...]
    unverified_effects: Tuple[str, ...]
    failed_effects: Tuple[Tuple[str, str], ...]
    verified_effects_omitted: bool = False
    unverified_effects_omitted: bool = False
    failed_effects_omitted: bool = False

    @property
    def has_material_writes(self) -> bool:
        return bool(
            self.verified_effects
            or self.unverified_effects
            or self.failed_effects
        )

    @property
    def has_unresolved(self) -> bool:
        return bool(self.unverified_effects or self.failed_effects)

    @property
    def has_failed_effects(self) -> bool:
        return bool(self.failed_effects)


def summarize_material_effects(
    steps: Iterable[Dict[str, Any]],
) -> MaterialEffectSummary:
    """Return capped, deduplicated receipt effects without exposing entity identities."""
    effect_states: Dict[str, Tuple[str, str]] = {}

    for step in steps:
        envelope = extract_material_operation_envelope(_step_result_payload(step))
        if envelope is None:
            continue

        for receipt in envelope.receipts:
            effect = _format_json(receipt.requested_effect)
            if receipt.verification_status == "verified":
                effect_states[effect] = ("verified", "")
            elif receipt.verification_status == "unverified":
                effect_states[effect] = ("unverified", "")
            elif receipt.verification_status == "failed":
                effect_states[effect] = (
                    "failed",
                    _format_json(receipt.discrepancy),
                )

    verified_effects, verified_effects_omitted = _collect_effects(
        effect_states,
        "verified",
    )
    unverified_effects, unverified_effects_omitted = _collect_effects(
        effect_states,
        "unverified",
    )
    failed_effects, failed_effects_omitted = _collect_failed_effects(effect_states)

    return MaterialEffectSummary(
        verified_effects=verified_effects,
        unverified_effects=unverified_effects,
        failed_effects=failed_effects,
        verified_effects_omitted=verified_effects_omitted,
        unverified_effects_omitted=unverified_effects_omitted,
        failed_effects_omitted=failed_effects_omitted,
    )


def build_material_outcome_brief(
    steps: Iterable[Dict[str, Any]],
) -> Optional[str]:
    """Render writer/evaluator claim constraints for material changes, if present."""
    summary = summarize_material_effects(steps)
    if not summary.has_material_writes:
        return None

    lines = [
        "Material change evidence (receipt-grounded claim constraints):",
    ]
    if summary.verified_effects:
        lines.append(
            "Verified changes you may state as done: "
            + _format_effects(
                summary.verified_effects,
                summary.verified_effects_omitted,
            )
        )
    if summary.unverified_effects:
        lines.append(
            "Changes not confirmed: do not state these as completed. If relevant, "
            "describe them as attempted or uncertain: "
            + _format_effects(
                summary.unverified_effects,
                summary.unverified_effects_omitted,
            )
        )
    if summary.failed_effects:
        lines.append(
            "Changes that failed: state these plainly if relevant: "
            + _format_failed_effects(
                summary.failed_effects,
                summary.failed_effects_omitted,
            )
        )
    lines.append(
        "Write naturally. Mention unresolved changes only where they matter to the "
        "request; do not enumerate entities or present counters."
    )
    return "\n".join(lines)


def build_material_outcome_brief_from_intermediate_steps(
    intermediate_steps: Iterable[Any],
) -> Optional[str]:
    """Build the same brief from LangChain-style ``(action, observation)`` tuples."""
    steps: list[Dict[str, Any]] = []
    for intermediate_step in intermediate_steps:
        if (
            not isinstance(intermediate_step, tuple)
            or len(intermediate_step) < 2
        ):
            continue
        observation = intermediate_step[1]
        steps.append({"result": _parse_observation(observation)})
    return build_material_outcome_brief(steps)


def _step_result_payload(step: Dict[str, Any]) -> Dict[str, Any]:
    result = step.get("result")
    if isinstance(result, dict) and isinstance(result.get("result"), dict):
        return result["result"]
    return result if isinstance(result, dict) else {}


def _parse_observation(observation: Any) -> Dict[str, Any]:
    if isinstance(observation, dict):
        return observation
    if not isinstance(observation, str):
        return {}
    try:
        value = json.loads(observation)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _collect_effects(
    effect_states: Dict[str, Tuple[str, str]],
    status: str,
) -> Tuple[Tuple[str, ...], bool]:
    effects = [
        effect
        for effect, (current_status, _) in effect_states.items()
        if current_status == status
    ]
    return tuple(effects[:_MAX_EFFECTS_PER_STATUS]), len(effects) > _MAX_EFFECTS_PER_STATUS


def _collect_failed_effects(
    effect_states: Dict[str, Tuple[str, str]],
) -> Tuple[Tuple[Tuple[str, str], ...], bool]:
    effects = [
        (effect, discrepancy)
        for effect, (status, discrepancy) in effect_states.items()
        if status == "failed"
    ]
    return tuple(effects[:_MAX_EFFECTS_PER_STATUS]), len(effects) > _MAX_EFFECTS_PER_STATUS


def _format_effects(effects: Tuple[str, ...], omitted: bool) -> str:
    rendered = "; ".join(effects)
    return rendered + ("; and other changes" if omitted else "")


def _format_failed_effects(
    effects: Tuple[Tuple[str, str], ...],
    omitted: bool,
) -> str:
    rendered = "; ".join(
        effect if discrepancy == "{}" else f"{effect} (reason: {discrepancy})"
        for effect, discrepancy in effects
    )
    return rendered + ("; and other changes" if omitted else "")


def _format_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
