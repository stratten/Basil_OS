"""Matrix orchestration: for every candidate, gate availability once, then
run each applicable scenario and collect a PASS/FAIL/SKIP/N/A cell."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .availability import check_availability, release_if_local
from .registry_enumeration import ModelCandidate, enumerate_candidates, select_channel_samples
from .scenarios import (
    ScenarioOutcome,
    applicability_for,
    run_agent_task,
    run_assistant_session,
    run_meeting_analysis,
    run_setup_wizard,
)
from .tool_scenarios import TOOL_SCENARIO_SPECS, run_tool_scenario

logger = logging.getLogger("model_scenario_smoke.matrix")

_ASSISTANT_SESSION = "assistant_session"
_DEFAULT_SCENARIOS = (
    _ASSISTANT_SESSION,
    "meeting_analysis",
    "agent_task",
    "setup_wizard",
)

# Progress callback: receives short human-readable status strings as the
# matrix advances (candidate start, availability outcome, per-scenario
# start/finish). A no-op default keeps run_matrix silent for pytest/library
# callers; the CLI passes a printer so long sweeps aren't silent for minutes.
ProgressFn = Callable[[str], None]


def _noop_progress(_message: str) -> None:
    return None


@dataclass
class CandidateRow:
    candidate: ModelCandidate
    availability_reason: Optional[str] = None
    channel: str = ""
    outcomes: Dict[str, ScenarioOutcome] = field(default_factory=dict)

    @property
    def any_fail(self) -> bool:
        return any(outcome.verdict == "FAIL" for outcome in self.outcomes.values())


async def run_matrix(
    *,
    id_filter: Optional[str] = None,
    provider_filter: Optional[str] = None,
    location_filter: Optional[str] = None,
    scenario_filter: Optional[str] = None,
    sample_channels: bool = False,
    on_event: Optional[ProgressFn] = None,
) -> List[CandidateRow]:
    progress = on_event or _noop_progress
    candidates = enumerate_candidates(
        id_filter=id_filter, provider_filter=provider_filter, location_filter=location_filter
    )
    if sample_channels:
        before = len(candidates)
        candidates = select_channel_samples(candidates)
        progress(f"Sampling one model per channel: {len(candidates)} of {before} candidates.")
    scenarios_to_run = [scenario_filter] if scenario_filter else list(_DEFAULT_SCENARIOS)

    rows: List[CandidateRow] = []
    total = len(candidates)
    for index, candidate in enumerate(candidates, start=1):
        row = CandidateRow(candidate=candidate)
        rows.append(row)

        progress(f"[{index}/{total}] {candidate.model_id}: checking availability…")
        availability = await check_availability(candidate)
        if not availability.available:
            row.availability_reason = availability.reason
            for scenario in scenarios_to_run:
                row.outcomes[scenario] = ScenarioOutcome.skip(availability.reason or "unavailable")
            progress(f"[{index}/{total}] {candidate.model_id}: SKIP (unavailable) — {availability.reason}")
            continue

        row.channel = type(availability.model).__name__
        progress(f"[{index}/{total}] {candidate.model_id}: available via {row.channel}")
        applicability = applicability_for(candidate)

        try:
            for scenario in scenarios_to_run:
                na_reason = applicability.get(scenario)
                if na_reason:
                    row.outcomes[scenario] = ScenarioOutcome.na(na_reason)
                    continue
                progress(f"[{index}/{total}] {candidate.model_id}: running {scenario}…")
                outcome = await _run_one(scenario, candidate, availability.model)
                row.outcomes[scenario] = outcome
                progress(f"[{index}/{total}] {candidate.model_id}: {scenario} → {outcome.verdict}")
        finally:
            await release_if_local(candidate)

    return rows


async def _run_one(scenario: str, candidate: ModelCandidate, model) -> ScenarioOutcome:
    try:
        if scenario == _ASSISTANT_SESSION:
            return await run_assistant_session(model, candidate)
        if scenario == "meeting_analysis":
            return await run_meeting_analysis(candidate)
        if scenario == "agent_task":
            return await run_agent_task(candidate)
        if scenario == "setup_wizard":
            return await run_setup_wizard(candidate)
        if scenario in TOOL_SCENARIO_SPECS:
            return await run_tool_scenario(candidate, TOOL_SCENARIO_SPECS[scenario])
    except Exception as exc:  # last-resort net: one candidate's bug must never abort the matrix
        logger.exception("Unhandled exception running scenario %s for %s", scenario, candidate.model_id)
        return ScenarioOutcome.fail(f"unhandled exception: {exc}")
    raise ValueError(f"Unknown scenario id: {scenario}")
