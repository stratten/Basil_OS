"""Regression coverage for smoke-matrix scenario selection."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from model_scenario_smoke_core import matrix
from model_scenario_smoke_core.report import render
from model_scenario_smoke_core.scenarios import ScenarioOutcome


@pytest.mark.asyncio
async def test_matrix_defaults_to_core_scenarios_only(monkeypatch) -> None:
    candidate = SimpleNamespace(model_id="local-test-model")
    executed_scenarios: list[str] = []

    monkeypatch.setattr(matrix, "enumerate_candidates", lambda **_kwargs: [candidate])
    monkeypatch.setattr(
        matrix,
        "check_availability",
        lambda _candidate: _available_model(),
    )
    monkeypatch.setattr(
        matrix,
        "applicability_for",
        lambda _candidate: {},
    )
    monkeypatch.setattr(matrix, "release_if_local", _release_model)

    async def run_scenario(scenario, _candidate, _model):
        executed_scenarios.append(scenario)
        return ScenarioOutcome.ok()

    monkeypatch.setattr(matrix, "_run_one", run_scenario)

    rows = await matrix.run_matrix()

    assert executed_scenarios == [
        "assistant_session",
        "meeting_analysis",
        "agent_task",
        "setup_wizard",
    ]
    assert "SetupWiz" in render(rows)


async def _available_model():
    return SimpleNamespace(available=True, model=object(), reason=None)


async def _release_model(_candidate) -> None:
    return None
