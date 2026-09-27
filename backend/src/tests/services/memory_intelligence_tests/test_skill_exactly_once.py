"""Regression coverage for durable, exactly-once skill mutations."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from api.routes.memory.router import (
    SkillCandidateApprovalRequest,
    approve_skill_candidate,
    delete_skill,
)
from api.services.memory import proposal_store as proposal_store_module
from api.services.memory.proposal_store import ProposalStore
from api.services.skills import skill_service as skill_service_module
from api.services.skills.skill_evaluator import SkillProposal
from api.services.skills.skill_service import SkillService
from api.services.skills.skill_store import SkillStore


def _procedure(marker: str) -> str:
    return (
        f"1. Review every {marker} input, surrounding context, and stated outcome before acting.\n"
        f"2. Apply the {marker} workflow carefully, documenting the important intermediate decisions.\n"
        f"3. Verify the {marker} result against the requested outcome before finishing the task.\n"
        f"4. Record any follow-up information that makes a later {marker} run safer and faster."
    )


def _proposal(title: str, marker: str) -> SkillProposal:
    return SkillProposal(
        title=title,
        when_to_use=f"Use when the user needs the {marker} workflow.",
        triggers=[marker, f"{marker} workflow"],
        procedure_markdown=_procedure(marker),
        expected_result=f"The {marker} workflow completes.",
        source_task_ids=["task-1"],
    )


@pytest.fixture
def isolated_skill_services(tmp_path):
    original_store = proposal_store_module._proposal_store_singleton
    original_service = skill_service_module._skill_service_singleton
    proposal_store = ProposalStore(path=tmp_path / "proposal_store.json")
    skill_service = SkillService(store=SkillStore(skills_dir=tmp_path / "skills"))
    proposal_store_module._proposal_store_singleton = proposal_store
    skill_service_module._skill_service_singleton = skill_service
    try:
        yield proposal_store, skill_service
    finally:
        proposal_store_module._proposal_store_singleton = original_store
        skill_service_module._skill_service_singleton = original_service


def test_origin_keyed_new_skill_returns_same_record_on_retry(isolated_skill_services) -> None:
    _, service = isolated_skill_services
    first = service.save_skill(
        title="Inspect PDF",
        body=_procedure("pdf inspection"),
        when_to_use="Use when inspecting a PDF.",
        triggers=["inspect pdf"],
        source_task_ids=["task-1"],
        creation_origin_key="agent-task:task-1",
    )
    second = service.save_skill(
        title="Inspect PDF",
        body=_procedure("pdf inspection"),
        when_to_use="Use when inspecting a PDF.",
        triggers=["inspect pdf"],
        source_task_ids=["task-1"],
        creation_origin_key="agent-task:task-1",
    )

    assert first.slug == second.slug
    assert first.metadata["updated_at"] == second.metadata["updated_at"]
    assert first.metadata["version"] == second.metadata["version"] == 1
    assert len(service.list_skills()) == 1
    assert second.metadata["creation_origin_key"] == "agent-task:task-1"


def test_distinct_origin_keys_preserve_distinct_user_intent(isolated_skill_services) -> None:
    _, service = isolated_skill_services
    first = service.save_skill(
        title="Inspect PDF",
        body=_procedure("pdf inspection"),
        when_to_use="Use when inspecting a PDF.",
        triggers=["inspect pdf"],
        creation_origin_key="agent-task:task-1",
    )
    second = service.save_skill(
        title="Inspect PDF",
        body=_procedure("pdf inspection"),
        when_to_use="Use when inspecting a PDF.",
        triggers=["inspect pdf"],
        creation_origin_key="agent-task:task-2",
    )

    assert first.slug != second.slug
    assert len(service.list_skills()) == 2


def test_named_enhancement_does_not_use_new_skill_idempotency(isolated_skill_services) -> None:
    _, service = isolated_skill_services
    saved = service.save_skill(
        title="Inspect PDF",
        body=_procedure("original inspection"),
        when_to_use="Use when inspecting a PDF.",
        triggers=["inspect pdf"],
    )
    updated = service.save_skill(
        title="Inspect PDF",
        body=_procedure("enhanced inspection"),
        when_to_use="Use when inspecting a PDF.",
        triggers=["inspect pdf"],
        slug=saved.slug,
    )

    assert updated.slug == saved.slug
    assert updated.metadata["version"] == 2
    assert len(service.list_skills()) == 1


def test_candidate_approval_replay_returns_existing_saved_skill(isolated_skill_services) -> None:
    proposal_store, service = isolated_skill_services
    [candidate] = proposal_store.enqueue_skill_candidates(
        [_proposal("Inspect PDF", "pdf inspection")],
        source="test",
    )

    first = asyncio.run(
        approve_skill_candidate(candidate.id, SkillCandidateApprovalRequest())
    )
    second = asyncio.run(
        approve_skill_candidate(candidate.id, SkillCandidateApprovalRequest())
    )

    assert first.id == second.id == candidate.id
    assert first.approved_skill_slug == second.approved_skill_slug
    assert len(service.list_skills()) == 1
    assert proposal_store.get_skill_candidate(candidate.id).status == "approved"


def test_candidate_terminal_conflict_returns_409_without_creating_skill(
    isolated_skill_services,
) -> None:
    proposal_store, service = isolated_skill_services
    [candidate] = proposal_store.enqueue_skill_candidates(
        [_proposal("Inspect PDF", "pdf inspection")],
        source="test",
    )
    proposal_store.mark_skill_candidate_status(candidate.id, "declined")

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            approve_skill_candidate(candidate.id, SkillCandidateApprovalRequest())
        )

    assert excinfo.value.status_code == 409
    assert service.list_skills() == []


def test_skill_delete_missing_returns_404(isolated_skill_services) -> None:
    _, service = isolated_skill_services
    saved = service.save_skill(
        title="Inspect PDF",
        body=_procedure("pdf inspection"),
        when_to_use="Use when inspecting a PDF.",
        triggers=["inspect pdf"],
    )

    assert asyncio.run(delete_skill(saved.slug)) == {"deleted": True}
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(delete_skill(saved.slug))

    assert excinfo.value.status_code == 404
