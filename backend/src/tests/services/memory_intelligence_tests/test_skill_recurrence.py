"""Tests for the skill recurrence / frequency counter and saved-skill versioning.

Covers the materialized ``observation_count`` on candidates and saved skills
(defined as the count of distinct source task ids), integer ``version`` on saved
skills (bumped only on body change), idempotent observation recording, legacy
record backfill, reconciliation threshold exclusion, and settings validation.
"""

import asyncio
import json

import pytest

from api.routes.settings_routes.memory_intelligence_routes import _validate_min_instances
from api.services.memory.proposal_store import ProposalStore
from api.services.skills.reconciliation import reconciliation_engine as engine_module
from api.services.skills.reconciliation.reconciliation_engine import ReconciliationEngine
from api.services.skills.reconciliation.reconciliation_session import (
    ReconciliationSessionStore,
    SessionSnapshot,
)
from api.services.skills.skill_evaluator import SkillProposal
from api.services.skills.skill_service import SkillService
from api.services.skills.skill_store import SkillStore


def _procedure(marker: str) -> str:
    return (
        f"1. Begin the {marker} procedure by carefully reviewing all of the "
        "provided inputs and the surrounding context before doing anything.\n"
        f"2. Perform each of the {marker} transformation steps in the correct "
        "order, checking assumptions as you go and recording intermediate state.\n"
        f"3. Validate the {marker} result thoroughly before completing the task, "
        "and re-check the output to confirm correctness and completeness."
    )


def _proposal(title: str, marker: str, **overrides) -> SkillProposal:
    base = dict(
        title=title,
        when_to_use=f"Use when the user needs the {marker} workflow during their day.",
        triggers=[marker, f"{marker} request"],
        procedure_markdown=_procedure(marker),
        expected_result=f"The {marker} workflow finishes.",
        source_task_ids=["task-1"],
    )
    base.update(overrides)
    return SkillProposal(**base)


@pytest.fixture
def stores(tmp_path):
    store = ProposalStore(path=tmp_path / "proposal_store.json")
    service = SkillService(store=SkillStore(skills_dir=tmp_path / "skills"))
    return store, service


# --- Candidate counting -----------------------------------------------------


def test_enqueue_sets_observation_count_from_distinct_sources(stores):
    store, _ = stores
    [single] = store.enqueue_skill_candidates(
        [_proposal("Single Sighting", "single", source_task_ids=["t1"])], source="test"
    )
    [multi] = store.enqueue_skill_candidates(
        [_proposal("Multi Sighting", "multi", source_task_ids=["t1", "t2"])], source="test"
    )
    assert single.observation_count == 1
    assert multi.observation_count == 2


def test_replace_unions_and_recounts_and_is_idempotent(stores):
    store, _ = stores
    [record] = store.enqueue_skill_candidates(
        [_proposal("Growing Skill", "grow", source_task_ids=["t1"])], source="test"
    )
    assert record.observation_count == 1

    grown = store.replace_skill_candidate_content(
        record.id,
        title="Growing Skill",
        when_to_use="Use when growing.",
        triggers=["grow"],
        procedure_markdown=_procedure("grow"),
        expected_result="Done.",
        source_task_ids=["t2"],
    )
    assert grown.observation_count == 2
    assert grown.source_task_ids == ["t1", "t2"]

    # Re-adding a task id already present must not inflate the count.
    again = store.replace_skill_candidate_content(
        record.id,
        title="Growing Skill",
        when_to_use="Use when growing.",
        triggers=["grow"],
        procedure_markdown=_procedure("grow"),
        expected_result="Done.",
        source_task_ids=["t2"],
    )
    assert again.observation_count == 2


def test_legacy_candidate_without_count_backfills(stores, tmp_path):
    store, _ = stores
    # Simulate a record persisted before observation_count existed.
    payload = {
        "memory_proposals": [],
        "skill_candidates": [
            {
                "id": "skill-candidate-legacy",
                "title": "Legacy",
                "when_to_use": "Use it.",
                "triggers": ["legacy"],
                "procedure_markdown": _procedure("legacy"),
                "expected_result": "Done.",
                "source_task_ids": ["a", "b", "c"],
                "source": "test",
                "created_at": "t",
                "status": "pending",
            }
        ],
    }
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps(payload), encoding="utf-8")

    candidate = store.get_skill_candidate("skill-candidate-legacy")
    assert candidate.observation_count == 3
    [listed] = store.list_pending_skill_candidates()
    assert listed.observation_count == 3


# --- Saved-skill counting + versioning --------------------------------------


def test_new_skill_starts_version_1_and_counts_sources(stores):
    _, service = stores
    saved = service.save_skill(
        title="Fresh Skill",
        body=_procedure("fresh"),
        when_to_use="Use when fresh.",
        triggers=["fresh"],
        source_task_ids=["a", "b"],
    )
    assert saved.metadata["version"] == 1
    assert saved.metadata["observation_count"] == 2


def test_enhancement_bumps_version_unions_sources_and_preserves_counters(stores):
    _, service = stores
    saved = service.save_skill(
        title="Enhance Me",
        body=_procedure("original"),
        when_to_use="Use when enhancing.",
        triggers=["enhance"],
        source_task_ids=["a"],
    )
    # Accumulate usage counters that must survive the enhancement.
    service.record_skill_success(saved.slug)
    service.load_skill(saved.slug, mark_used=True)

    enhanced = service.save_skill(
        slug=saved.slug,
        title="Enhance Me",
        body=_procedure("enhanced-body-that-differs"),
        when_to_use="Use when enhancing.",
        triggers=["enhance"],
        source_task_ids=["b"],
    )
    assert enhanced.metadata["version"] == 2
    assert enhanced.metadata["observation_count"] == 2  # a + b
    assert set(enhanced.metadata["source_task_ids"]) == {"a", "b"}
    assert enhanced.metadata["success_count"] == 1
    assert enhanced.metadata["last_used"] is not None


def test_enhancement_same_body_keeps_version(stores):
    _, service = stores
    saved = service.save_skill(
        title="Stable",
        body=_procedure("stable"),
        when_to_use="Use when stable.",
        triggers=["stable"],
        source_task_ids=["a"],
    )
    unchanged = service.save_skill(
        slug=saved.slug,
        title="Stable",
        body=_procedure("stable"),
        when_to_use="Use when stable.",
        triggers=["stable"],
        source_task_ids=["b"],
    )
    assert unchanged.metadata["version"] == 1
    assert unchanged.metadata["observation_count"] == 2


def test_record_skill_observation_is_idempotent_and_no_version_bump(stores):
    _, service = stores
    saved = service.save_skill(
        title="Observed",
        body=_procedure("observed"),
        when_to_use="Use when observed.",
        triggers=["observed"],
        source_task_ids=["a"],
    )
    assert saved.metadata["observation_count"] == 1

    bumped = service.record_skill_observation(saved.slug, source_task_ids=["b"])
    assert bumped.metadata["observation_count"] == 2
    assert bumped.metadata["version"] == 1  # observation is not a content edit
    assert bumped.body.strip() == saved.body.strip()

    # Re-observing the same task id is a no-op.
    again = service.record_skill_observation(saved.slug, source_task_ids=["b"])
    assert again.metadata["observation_count"] == 2


# --- Reconciliation threshold exclusion -------------------------------------


def test_analysis_excludes_below_threshold_candidates(stores, monkeypatch):
    store, service = stores
    [recurring] = store.enqueue_skill_candidates(
        [_proposal("Recurring", "recurring", source_task_ids=["t1", "t2"])],
        source="test",
    )
    [single] = store.enqueue_skill_candidates(
        [_proposal("Single", "single", source_task_ids=["t9"])],
        source="test",
    )
    assert recurring.observation_count == 2
    assert single.observation_count == 1

    session_store = ReconciliationSessionStore()
    engine = ReconciliationEngine(
        session_store=session_store,
        proposal_store=store,
        skill_service=service,
        evaluator_factory=lambda: object(),
    )

    from dataclasses import asdict

    snapshot = SessionSnapshot(
        captured_at="t",
        pending_candidates=[
            asdict(store.get_skill_candidate(recurring.id)),
            asdict(store.get_skill_candidate(single.id)),
        ],
        saved_skills=[],
        min_observations=2,
    )
    session = session_store.create(snapshot)

    captured = {}

    async def fake_run_analysis(*, pending, saved_skills, evaluator, on_progress=None):
        captured["pending_ids"] = [record.id for record in pending]
        if False:  # make this an async generator that yields nothing
            yield  # pragma: no cover

    monkeypatch.setattr(engine_module, "run_analysis", fake_run_analysis)

    asyncio.run(engine._run_analysis(session.id))

    assert captured["pending_ids"] == [recurring.id]


# --- Settings validation ----------------------------------------------------


def test_validate_min_instances_accepts_positive_ints():
    _validate_min_instances(1)
    _validate_min_instances(5)


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "2"])
def test_validate_min_instances_rejects_invalid(value):
    with pytest.raises(ValueError):
        _validate_min_instances(value)
