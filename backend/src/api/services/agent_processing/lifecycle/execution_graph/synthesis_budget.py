"""Budgeted prompt construction for final agent-task synthesis."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from api.core.models.reasoning.streaming_contract import (
    GenerationBudget,
    resolve_generation_budget,
)
from api.services.agent_processing.shared.material_outcome_brief import (
    build_material_outcome_brief_from_intermediate_steps,
)
from api.services.agent_processing.shared.truncation_evidence import TruncationEvidence


@dataclass
class SynthesisInput:
    """Budgeted final-synthesis prompt plus truncation evidence."""

    messages: List[Dict[str, str]]
    budget: GenerationBudget
    truncation_evidence: List[Dict[str, Any]] = field(default_factory=list)
    input_token_estimate: int = 0


def build_budgeted_synthesis_input(
    *,
    llm_model: Any,
    system_prompt: str,
    user_agent_task: str,
    final_input: str,
    agent_output: Any,
    intermediate_steps: List[Any],
    context: Optional[Dict[str, Any]],
) -> SynthesisInput:
    """Build final-synthesis messages that fit the selected model profile."""
    preliminary_budget = resolve_generation_budget(
        llm_model,
        purpose="final_synthesis",
        input_token_estimate=0,
    )
    input_budget_tokens = preliminary_budget.input_budget_tokens or 16000
    input_budget_chars = max(4000, input_budget_tokens * 4)
    evidence: List[TruncationEvidence] = []

    ctx = context or {}
    active_app = ctx.get("active_app")
    if not active_app and isinstance(ctx.get("app_context"), dict):
        active_app = (ctx.get("app_context") or {}).get("app_name")

    ref_paths = ctx.get("reference_paths") or ctx.get("reference_paths_for_task")
    material_outcome_brief = (
        build_material_outcome_brief_from_intermediate_steps(intermediate_steps)
    )
    core_sections = [
        ("user_request", f"User request:\n{user_agent_task.strip()}"),
    ]
    if material_outcome_brief:
        core_sections.append(("material_outcome", material_outcome_brief))
    if final_input and final_input.strip() and final_input.strip() != user_agent_task.strip():
        core_sections.append(
            (
                "chain_context",
                f"Follow-up / chain context:\n{final_input.strip()}",
            )
        )
    if active_app:
        core_sections.append(("active_app", f"Active app at request time: {active_app}"))
    if ref_paths:
        core_sections.append(("reference_paths", _bounded_json_section("Reference paths / context", ref_paths, 4000, evidence)))

    handoff = normalize_agent_executor_output(agent_output).strip()
    core_sections.append(
        (
            "agent_handoff",
            "Agent execution handoff (what the tool agent reports it did):\n"
            + (handoff or "(empty)"),
        )
    )

    tool_trace, tool_evidence = _format_tool_trace_for_budget(intermediate_steps)
    evidence.extend(tool_evidence)
    tool_section_prefix = (
        "Tool trace (authoritative for facts only where not marked truncated or omitted):\n"
    )

    optional_sections: List[Tuple[str, str]] = [(name, body) for name, body in core_sections]
    optional_sections.append(("tool_trace", tool_section_prefix + tool_trace))
    optional_sections.extend(_context_diagnostic_sections(ctx, evidence))

    retained_sections: List[str] = []
    used_chars = len(system_prompt)
    for index, (name, section) in enumerate(optional_sections):
        section_len = len(section)
        reserved_material_outcome_chars = sum(
            len(future_section)
            for future_name, future_section in optional_sections[index + 1:]
            if future_name == "material_outcome"
        )
        available_chars = max(
            0,
            input_budget_chars - used_chars - reserved_material_outcome_chars,
        )
        if section_len <= available_chars:
            retained_sections.append(section)
            used_chars += section_len
            continue

        remaining = available_chars
        if remaining >= 500:
            retained_sections.append(section[:remaining] + "\n... [truncated for synthesis budget]")
            evidence.append(
                TruncationEvidence(
                    source=f"synthesis.{name}",
                    original_length=section_len,
                    retained_length=remaining,
                    affects_coverage=name == "tool_trace",
                    reason="synthesis_input_budget",
                )
            )
            used_chars += remaining
        else:
            evidence.append(
                TruncationEvidence(
                    source=f"synthesis.{name}",
                    original_length=section_len,
                    retained_length=0,
                    omitted_count=1,
                    affects_coverage=name == "tool_trace",
                    reason="synthesis_input_budget",
                )
            )

    evidence_dicts = [item.to_dict() for item in evidence]
    if evidence_dicts:
        retained_sections.append(
            "Truncation / coverage evidence:\n"
            + json.dumps(evidence_dicts, ensure_ascii=False)
        )

    user_content = "\n\n".join(section for section in retained_sections if section)
    final_budget = resolve_generation_budget(
        llm_model,
        purpose="final_synthesis",
        input_token_estimate=_estimate_tokens(user_content) + _estimate_tokens(system_prompt),
    )
    return SynthesisInput(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        budget=final_budget,
        truncation_evidence=evidence_dicts,
        input_token_estimate=_estimate_tokens(user_content) + _estimate_tokens(system_prompt),
    )


def _format_tool_trace_for_budget(intermediate_steps: List[Any]) -> Tuple[str, List[TruncationEvidence]]:
    lines: List[str] = []
    evidence: List[TruncationEvidence] = []
    for index, step in enumerate(intermediate_steps or []):
        if not isinstance(step, tuple) or len(step) < 2:
            continue
        action, observation = step[0], step[1]
        tool_name = getattr(action, "tool", None)
        if tool_name == "finalize_agent_task_result":
            continue
        lines.append(f"--- Tool: {tool_name} ---")
        tool_input = getattr(action, "tool_input", None)
        if tool_input is not None:
            input_text = _safe_json(tool_input)
            bounded, input_evidence = _bounded_text(
                input_text,
                4000,
                f"synthesis.tool_input.{index}",
                affects_coverage=False,
            )
            lines.append(f"Input: {bounded}")
            if input_evidence:
                evidence.append(input_evidence)
        observation_text = observation if isinstance(observation, str) else str(observation)
        bounded_obs, obs_evidence = _bounded_text(
            observation_text,
            12000,
            f"synthesis.tool_observation.{index}",
            affects_coverage=True,
        )
        lines.append(f"Observation: {bounded_obs}")
        lines.append("")
        if obs_evidence:
            evidence.append(obs_evidence)
    return "\n".join(lines).strip() or "(No tool calls recorded.)", evidence


def _context_diagnostic_sections(ctx: Dict[str, Any], evidence: List[TruncationEvidence]) -> List[Tuple[str, str]]:
    sections: List[Tuple[str, str]] = []
    for name, title in (
        ("tool_errors", "Tool wiring / setup issues"),
        ("staged_tool_loading_diagnostics", "Staged tool loading diagnostics"),
        ("truncation_evidence", "Prior truncation evidence"),
    ):
        value = ctx.get(name)
        if value:
            sections.append((name, _bounded_json_section(title, value, 4000, evidence)))
    return sections


def _bounded_json_section(
    title: str,
    value: Any,
    limit: int,
    evidence: List[TruncationEvidence],
) -> str:
    text = title + ":\n" + _safe_json(value)
    bounded, item = _bounded_text(text, limit, f"synthesis.{title.lower().replace(' ', '_')}", affects_coverage=False)
    if item:
        evidence.append(item)
    return bounded


def _bounded_text(
    value: str,
    limit: int,
    source: str,
    *,
    affects_coverage: bool,
) -> Tuple[str, Optional[TruncationEvidence]]:
    if len(value) <= limit:
        return value, None
    retained = value[:limit] + "\n... [truncated]"
    return retained, TruncationEvidence(
        source=source,
        original_length=len(value),
        retained_length=limit,
        affects_coverage=affects_coverage,
        reason="section_limit",
    )


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _estimate_tokens(text: str) -> int:
    return max(0, (len(text or "") + 3) // 4)


def normalize_agent_executor_output(output: Any) -> str:
    """Normalize LangChain/Claude output blocks without importing synthesis module."""
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        parts: List[str] = []
        for item in output:
            if isinstance(item, dict):
                text = item.get("text")
                if text is not None:
                    parts.append(str(text))
                elif "content" in item:
                    parts.append(str(item["content"]))
                else:
                    parts.append(_safe_json(item)[:8000])
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(output)


__all__ = ["SynthesisInput", "build_budgeted_synthesis_input"]
