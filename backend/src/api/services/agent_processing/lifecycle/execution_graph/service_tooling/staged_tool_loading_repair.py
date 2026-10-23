"""Post-pass interpretation for staged Agent Task tool loading."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .tool_family_catalog import (
    BASELINE_FALLBACK_FAMILY_NAMES,
    extract_loaded_families_from_steps,
    extract_repair_families_from_steps,
    extract_suggested_families_from_loader_observation,
    family_names_for_tool_name,
)


@dataclass(frozen=True)
class StagedToolLoadDecision:
    """Decision produced after one staged-tool executor pass."""

    new_families: list[str]
    requested_families: list[str]
    repair_families: list[str]
    suggested_families: list[str]
    invalid_loader_requests: list[str]
    should_continue: bool
    had_non_loader_activity: bool = False
    diagnostic: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _dedupe_names(names: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for name in names:
        normalized = str(name).strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _loader_observation_payloads(intermediate_steps: Sequence[Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for step in intermediate_steps or []:
        if not isinstance(step, tuple) or len(step) < 2:
            continue
        action, observation = step[0], step[1]
        if getattr(action, "tool", None) != "load_tool_family":
            continue
        try:
            payload = json.loads(observation if isinstance(observation, str) else str(observation))
        except Exception:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _had_non_loader_activity(intermediate_steps: Sequence[Any]) -> bool:
    for step in intermediate_steps or []:
        if not isinstance(step, tuple) or len(step) < 2:
            continue
        tool_name = str(getattr(step[0], "tool", "") or "")
        if tool_name and tool_name != "load_tool_family":
            return True
    return False


def _invalid_loader_requests(intermediate_steps: Sequence[Any]) -> list[str]:
    invalid: list[str] = []
    for payload in _loader_observation_payloads(intermediate_steps):
        invalid.extend(payload.get("invalid_families") or [])
    return _dedupe_names(invalid)


def _loader_mapping_details(intermediate_steps: Sequence[Any]) -> dict[str, list[str]]:
    mappings: dict[str, list[str]] = {}
    for payload in _loader_observation_payloads(intermediate_steps):
        raw_mappings = payload.get("mapped_family_inputs") or {}
        if not isinstance(raw_mappings, dict):
            continue
        for source_name, family_names in raw_mappings.items():
            if not isinstance(family_names, list):
                continue
            mappings[str(source_name)] = _dedupe_names(family_names)
    return mappings


def collect_new_tool_families_from_steps(
    intermediate_steps: Sequence[Any],
    loaded_families: Iterable[str] | None = None,
) -> StagedToolLoadDecision:
    """Collect the next staged families to load from one executor pass."""
    already_loaded = set(_dedupe_names(loaded_families or [])) | set(BASELINE_FALLBACK_FAMILY_NAMES)
    requested_families = extract_loaded_families_from_steps(intermediate_steps)
    repair_families = extract_repair_families_from_steps(
        intermediate_steps,
        loaded_families=already_loaded,
    )
    suggested_families = extract_suggested_families_from_loader_observation(
        intermediate_steps,
        loaded_families=already_loaded,
    )
    invalid_requests = _invalid_loader_requests(intermediate_steps)

    new_families = [
        family_name
        for family_name in _dedupe_names([*requested_families, *repair_families, *suggested_families])
        if family_name not in already_loaded
    ]

    diagnostic = None
    mapping_details = _loader_mapping_details(intermediate_steps)
    if invalid_requests or mapping_details:
        diagnostic_parts = []
        if mapping_details:
            diagnostic_parts.append(f"mapped loader inputs: {mapping_details}")
        if invalid_requests:
            diagnostic_parts.append(f"unresolved loader inputs: {invalid_requests}")
        if new_families:
            diagnostic_parts.append(f"continuing with families: {new_families}")
        else:
            diagnostic_parts.append("no additional tool family could be resolved")
        diagnostic = "; ".join(diagnostic_parts)

    return StagedToolLoadDecision(
        new_families=new_families,
        requested_families=requested_families,
        repair_families=repair_families,
        suggested_families=suggested_families,
        invalid_loader_requests=invalid_requests,
        should_continue=bool(new_families),
        had_non_loader_activity=_had_non_loader_activity(intermediate_steps),
        diagnostic=diagnostic,
        details={
            "requested_families": requested_families,
            "repair_families": repair_families,
            "suggested_families": suggested_families,
            "invalid_loader_requests": invalid_requests,
            "mapped_family_inputs": mapping_details,
            "new_families": new_families,
        },
    )


SCRIPTING_FLOOR_FAMILIES: frozenset[str] = frozenset({"automation", "shell"})


def _scripting_attempted(intermediate_steps: Sequence[Any]) -> bool:
    for step in intermediate_steps or []:
        if not isinstance(step, tuple) or len(step) < 2:
            continue
        tool_name = str(getattr(step[0], "tool", "") or "")
        if not tool_name:
            continue
        if SCRIPTING_FLOOR_FAMILIES.intersection(family_names_for_tool_name(tool_name)):
            return True
    return False


def _step_reported_failure(observation: Any) -> bool:
    """True only when a tool's own structured result reports ``success == False``
    (the same flag ``_parse_observation_for_step`` feeds the finalizer), or the
    model attempted a tool that is not bound.

    It intentionally does NOT scan arbitrary tool output for words like "error":
    whether a step succeeded is determined by the tool/finalizer layer, not by
    keyword-matching content that may legitimately mention errors (e.g. a log
    summary). A tool that fails reports it structurally; content does not."""
    if isinstance(observation, dict):
        return observation.get("success") is False
    text = observation if isinstance(observation, str) else str(observation)
    lowered = text.lower()
    # An attempt to call an unbound tool is surfaced by LangChain as plain text,
    # not a tool envelope. That is a genuine structural failure (the method the
    # model reached for does not exist), not a content keyword.
    if (
        "not a valid tool" in lowered
        or "invalid tool" in lowered
        or "available tools" in lowered
    ):
        return True
    try:
        data = json.loads(text)
    except Exception:
        return False
    return isinstance(data, dict) and data.get("success") is False


def _blocked_signal(intermediate_steps: Sequence[Any]) -> bool:
    for step in intermediate_steps or []:
        if not isinstance(step, tuple) or len(step) < 2:
            continue
        action, observation = step[0], step[1]
        tool_name = str(getattr(action, "tool", "") or "")
        if not tool_name or tool_name == "load_tool_family":
            continue
        if _step_reported_failure(observation):
            return True
    return False


def scripting_floor_owed(intermediate_steps: Sequence[Any]) -> bool:
    """A last-resort scripting attempt is owed when a non-loader tool/method was
    tried and failed (or was unavailable) yet no automation/shell tool was ever
    invoked. Deterministic and free on the success path."""
    return _blocked_signal(intermediate_steps) and not _scripting_attempted(intermediate_steps)
