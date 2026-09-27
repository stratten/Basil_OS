"""Tests for skill-candidate approval, including the enhance-an-existing-skill path."""

import asyncio

import pytest

from api.routes.memory.router import approve_skill_candidate, SkillCandidateApprovalRequest
from api.services.memory import proposal_store as proposal_store_module
from api.services.memory.proposal_store import ProposalStore
from api.services.skills import skill_service as skill_service_module
from api.services.skills.skill_evaluator import SkillProposal
from api.services.skills.skill_service import SkillService
from api.services.skills.skill_store import SkillNotFoundError, SkillStore


def _valid_procedure(marker: str) -> str:
    return (
        f"1. Begin the {marker} procedure by reviewing the inputs.\n"
        f"2. Perform the {marker} transformation steps in order.\n"
        f"3. Validate the {marker} result before completing the task."
        " Re-check the output to confirm correctness and completeness."
    )


def _proposal(title: str, marker: str, **overrides) -> SkillProposal:
    base = dict(
        title=title,
        when_to_use=f"Use when the user needs the {marker} workflow during their day.",
        triggers=[marker, f"{marker} request"],
        procedure_markdown=_valid_procedure(marker),
        expected_result=f"The {marker} workflow finishes.",
        source_task_ids=["task-1"],
    )
    base.update(overrides)
    return SkillProposal(**base)


@pytest.fixture
def temp_skill_singletons(tmp_path):
    original_store = proposal_store_module._proposal_store_singleton
    original_service = skill_service_module._skill_service_singleton

    store = ProposalStore(path=tmp_path / "proposal_store.json")
    service = SkillService(store=SkillStore(skills_dir=tmp_path / "skills"))
    proposal_store_module._proposal_store_singleton = store
    skill_service_module._skill_service_singleton = service
    try:
        yield store, service
    finally:
        proposal_store_module._proposal_store_singleton = original_store
        skill_service_module._skill_service_singleton = original_service


def test_approving_normal_candidate_creates_new_skill(temp_skill_singletons) -> None:
    store, service = temp_skill_singletons
    [record] = store.enqueue_skill_candidates(
        [_proposal("Convert PDF To Markdown", "convert-pdf")],
        source="test",
    )

    asyncio.run(approve_skill_candidate(record.id, SkillCandidateApprovalRequest()))

    skills = service.list_skills()
    assert len(skills) == 1
    assert skills[0].slug == "convert-pdf-to-markdown"
    assert "convert-pdf" in skills[0].body
    approved = store.get_skill_candidate(record.id)
    assert approved.approved_skill_slug == skills[0].slug


def test_approving_enhances_candidate_overwrites_target_skill(temp_skill_singletons) -> None:
    store, service = temp_skill_singletons
    saved = service.save_skill(
        title="PDF Helper",
        body=_valid_procedure("original-pdf"),
        when_to_use="Use when converting pdf files into markdown for the user.",
        triggers=["convert pdf"],
        source_task_ids=["saved-task"],
    )
    [record] = store.enqueue_skill_candidates(
        [_proposal("PDF Helper Enhanced", "enhanced-pdf", enhances_skill_slug=saved.slug)],
        source="test",
    )

    asyncio.run(approve_skill_candidate(record.id, SkillCandidateApprovalRequest()))

    skills = service.list_skills()
    # No duplicate skill was created; the target slug was overwritten in place.
    assert len(skills) == 1
    assert skills[0].slug == saved.slug
    overwritten = service.load_skill(saved.slug, mark_used=False)
    assert "enhanced-pdf" in overwritten.body
    assert "original-pdf" not in overwritten.body

    # A "pdf-helper-enhanced" slug must NOT have been generated from the title.
    with pytest.raises(SkillNotFoundError):
        service.load_skill("pdf-helper-enhanced", mark_used=False)
