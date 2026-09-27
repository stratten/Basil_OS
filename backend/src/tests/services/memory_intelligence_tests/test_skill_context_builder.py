"""Tests for the shared evaluator-context builder.

Verifies that pending candidates and saved skills are assembled together and
that full bodies are attached only for items relevant to the task (unrelated
items remain metadata-only).
"""

import pytest

from api.services.memory import proposal_store as proposal_store_module
from api.services.memory.proposal_store import ProposalStore
from api.services.skills import skill_context_builder, skill_service as skill_service_module
from api.services.skills.skill_evaluator import SkillProposal
from api.services.skills.skill_service import SkillService
from api.services.skills.skill_store import SkillStore


def _valid_procedure(topic: str) -> str:
    return (
        f"1. Open the {topic} source material and review its structure.\n"
        f"2. Apply the {topic} transformation steps carefully and consistently.\n"
        f"3. Verify the {topic} output matches the expected result before finishing."
        " Repeat the verification pass to ensure nothing was dropped or corrupted."
    )


def _proposal(title: str, topic: str, task_id: str) -> SkillProposal:
    return SkillProposal(
        title=title,
        when_to_use=f"Use when the user wants to {topic} as part of their workflow today.",
        triggers=[topic, f"{topic} request"],
        procedure_markdown=_valid_procedure(topic),
        expected_result=f"The {topic} completes successfully.",
        source_task_ids=[task_id],
    )


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


def test_context_attaches_bodies_only_to_related_items(temp_skill_singletons) -> None:
    store, service = temp_skill_singletons

    store.enqueue_skill_candidates(
        [_proposal("Convert PDF To Markdown", "convert pdf markdown", "pdf-task")],
        source="test",
    )
    store.enqueue_skill_candidates(
        [_proposal("Schedule Team Meeting", "schedule calendar meeting", "cal-task")],
        source="test",
    )

    service.save_skill(
        title="PDF Cleanup Helper",
        body=_valid_procedure("convert pdf markdown"),
        when_to_use="Use when cleaning up converted pdf markdown output for the user.",
        triggers=["convert pdf markdown", "pdf cleanup"],
        source_task_ids=["saved-pdf-task"],
    )
    service.save_skill(
        title="Calendar Scheduler",
        body=_valid_procedure("schedule calendar meeting"),
        when_to_use="Use when scheduling calendar meetings with multiple attendees.",
        triggers=["schedule calendar meeting", "calendar invite"],
        source_task_ids=["saved-cal-task"],
    )

    context = skill_context_builder.build_existing_skill_context(
        "convert this pdf file into clean markdown"
    )

    pending_by_title = {c.title: c for c in context.pending_candidates}
    saved_by_title = {s.title: s for s in context.saved_skills}

    assert pending_by_title["Convert PDF To Markdown"].procedure_markdown is not None
    assert pending_by_title["Schedule Team Meeting"].procedure_markdown is None

    assert saved_by_title["PDF Cleanup Helper"].body is not None
    assert saved_by_title["PDF Cleanup Helper"].source_task_ids == ["saved-pdf-task"]
    assert saved_by_title["Calendar Scheduler"].body is None


def test_context_handles_empty_stores(temp_skill_singletons) -> None:
    context = skill_context_builder.build_existing_skill_context("anything at all")
    assert context.pending_candidates == []
    assert context.saved_skills == []
