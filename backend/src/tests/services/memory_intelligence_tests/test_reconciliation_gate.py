"""Freeze-gate behavior for the Skill Reconciliation Workspace.

Covers the three enforcement surfaces described in the plan:
- the gate primitive itself (activate/deactivate/single-owner),
- the daily-sweep producer becoming a no-op while a session is active,
- the manual skill mutation routes returning HTTP 409 while active.
"""

import asyncio

import pytest
from fastapi import HTTPException

from api.routes.memory.router import (
    SkillCandidateApprovalRequest,
    SkillUpdateRequest,
    approve_skill_candidate,
    decline_skill_candidate,
    delete_skill,
    run_memory_intelligence_now,
    update_skill,
)
from api.services.memory.intelligence_scheduler import MemoryIntelligenceScheduler
from api.services.skills.reconciliation import reconciliation_gate


@pytest.fixture(autouse=True)
def _reset_gate():
    """Guarantee every test starts and ends with the gate released."""
    reconciliation_gate.deactivate()
    try:
        yield
    finally:
        reconciliation_gate.deactivate()


def test_gate_activate_and_deactivate_round_trip():
    assert reconciliation_gate.is_active() is False
    assert reconciliation_gate.active_session_id() is None

    reconciliation_gate.activate("recon-1")
    assert reconciliation_gate.is_active() is True
    assert reconciliation_gate.active_session_id() == "recon-1"

    # Re-activating the same session is a harmless no-op.
    reconciliation_gate.activate("recon-1")
    assert reconciliation_gate.active_session_id() == "recon-1"

    reconciliation_gate.deactivate()
    assert reconciliation_gate.is_active() is False
    # Deactivate is idempotent.
    reconciliation_gate.deactivate()
    assert reconciliation_gate.is_active() is False


def test_gate_rejects_a_second_distinct_session():
    reconciliation_gate.activate("recon-1")
    with pytest.raises(ValueError):
        reconciliation_gate.activate("recon-2")


def test_daily_sweep_is_a_no_op_while_gate_active():
    scheduler = MemoryIntelligenceScheduler()
    reconciliation_gate.activate("recon-sweep")

    result = asyncio.run(scheduler.run_now())

    # It short-circuited with a reconciliation notice and never marked itself
    # running (so the real orchestrator was never invoked).
    assert result.errors
    assert any("reconciliation" in err.lower() for err in result.errors)
    assert scheduler.get_status().is_running_now is False


@pytest.mark.parametrize(
    "call",
    [
        lambda: run_memory_intelligence_now(),
        lambda: approve_skill_candidate("missing", SkillCandidateApprovalRequest()),
        lambda: decline_skill_candidate("missing"),
        lambda: update_skill(
            "missing",
            SkillUpdateRequest(title="t", body="b", when_to_use="w"),
        ),
        lambda: delete_skill("missing"),
    ],
)
def test_mutation_routes_return_409_while_gate_active(call):
    reconciliation_gate.activate("recon-routes")

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(call())

    assert excinfo.value.status_code == 409


def test_mutation_routes_are_reachable_once_gate_released():
    # With the gate released, the guard no longer fires; the route proceeds to
    # its normal not-found handling for a missing referent (never a 409).
    reconciliation_gate.deactivate()
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(decline_skill_candidate("definitely-missing"))
    assert excinfo.value.status_code != 409
