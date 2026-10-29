"""Renders a CandidateRow matrix as a human-readable text table or JSON."""

from __future__ import annotations

import json
from typing import List, Optional

from .matrix import CandidateRow
from .scenarios import SCENARIOS

_SCENARIO_HEADERS = {
    "assistant_session": "AsstSession",
    "meeting_analysis": "Meeting",
    "agent_task": "AgentTask",
    "setup_wizard": "SetupWiz",
}

_VERDICT_GLYPH = {"PASS": "PASS", "FAIL": "FAIL!!", "SKIP": "skip", "N/A": "n/a"}


def _scenario_label(scenario: str) -> str:
    return _SCENARIO_HEADERS.get(scenario, scenario)


def _scenario_order(rows: List[CandidateRow]) -> List[str]:
    return list(
        dict.fromkeys(
            scenario
            for row in rows
            for scenario in row.outcomes
        )
    )


def render(rows: List[CandidateRow], scenario_order: List[str] = None) -> str:
    scenario_order = scenario_order or _scenario_order(rows) or list(SCENARIOS)
    lines: List[str] = []

    id_width = max([len("Model")] + [len(row.candidate.model_id) for row in rows]) if rows else len("Model")
    channel_width = max([len("Channel")] + [len(row.channel) for row in rows]) if rows else len("Channel")
    col_widths = {
        scenario: max(len(_scenario_label(scenario)), 6) for scenario in scenario_order
    }

    header = f"{'Model'.ljust(id_width)}  {'Channel'.ljust(channel_width)}  " + "  ".join(
        _scenario_label(s).ljust(col_widths[s]) for s in scenario_order
    )
    lines.append(header)
    lines.append("-" * len(header))

    for row in rows:
        channel = row.channel or "-"
        if row.availability_reason:
            cells = "  ".join("SKIP".ljust(col_widths[s]) for s in scenario_order)
            lines.append(f"{row.candidate.model_id.ljust(id_width)}  {channel.ljust(channel_width)}  {cells}")
            continue
        cells = "  ".join(
            _VERDICT_GLYPH[row.outcomes[s].verdict].ljust(col_widths[s]) if s in row.outcomes else "-".ljust(col_widths[s])
            for s in scenario_order
        )
        lines.append(f"{row.candidate.model_id.ljust(id_width)}  {channel.ljust(channel_width)}  {cells}")

    lines.append("")
    lines.append("Details:")
    for row in rows:
        if row.availability_reason:
            lines.append(f"  {row.candidate.model_id}: SKIP (all scenarios) -- {row.availability_reason}")
            continue
        for scenario in scenario_order:
            outcome = row.outcomes.get(scenario)
            if outcome is None:
                continue
            if outcome.verdict in {"PASS", "N/A"} and not outcome.detail:
                continue
            lines.append(
                f"  {row.candidate.model_id} / {_scenario_label(scenario)}: {outcome.verdict} -- {outcome.detail}"
            )

    total = sum(len(row.outcomes) for row in rows)
    fails = sum(1 for row in rows for outcome in row.outcomes.values() if outcome.verdict == "FAIL")
    passes = sum(1 for row in rows for outcome in row.outcomes.values() if outcome.verdict == "PASS")
    skips = sum(1 for row in rows for outcome in row.outcomes.values() if outcome.verdict == "SKIP")
    nas = sum(1 for row in rows for outcome in row.outcomes.values() if outcome.verdict == "N/A")
    lines.append("")
    lines.append(f"Totals: {total} cells -- {passes} PASS, {fails} FAIL, {skips} SKIP, {nas} N/A")

    return "\n".join(lines)


def any_fail(rows: List[CandidateRow]) -> bool:
    return any(row.any_fail for row in rows)


def render_json(rows: List[CandidateRow], scenario_order: Optional[List[str]] = None) -> str:
    """Render the same matrix as machine-readable JSON for CI/diffing.

    Mirrors the text report's data exactly (per-cell verdict + detail, channel,
    availability reason, and aggregate totals) so ``--json`` and the default
    table never disagree about outcomes.
    """
    scenario_order = scenario_order or _scenario_order(rows) or list(SCENARIOS)

    model_entries = []
    for row in rows:
        scenarios = {
            scenario: {
                "verdict": row.outcomes[scenario].verdict,
                "detail": row.outcomes[scenario].detail,
            }
            for scenario in scenario_order
            if scenario in row.outcomes
        }
        model_entries.append(
            {
                "model_id": row.candidate.model_id,
                "provider": row.candidate.provider,
                "location": row.candidate.location,
                "handler": row.candidate.handler,
                "channel_key": row.candidate.channel_key,
                "channel": row.channel or None,
                "is_custom": row.candidate.is_custom,
                "supports_function_calling": row.candidate.supports_function_calling,
                "supports_openrouter_proxy": row.candidate.supports_openrouter_proxy,
                "availability_reason": row.availability_reason,
                "scenarios": scenarios,
            }
        )

    all_outcomes = [outcome for row in rows for outcome in row.outcomes.values()]
    totals = {
        "cells": len(all_outcomes),
        "pass": sum(1 for o in all_outcomes if o.verdict == "PASS"),
        "fail": sum(1 for o in all_outcomes if o.verdict == "FAIL"),
        "skip": sum(1 for o in all_outcomes if o.verdict == "SKIP"),
        "na": sum(1 for o in all_outcomes if o.verdict == "N/A"),
    }

    return json.dumps(
        {"models": model_entries, "totals": totals, "any_fail": any_fail(rows)},
        indent=2,
    )
