"""Tests for enhancement-aware application of skill proposals.

A stub evaluator stands in for the reasoning model so the deterministic routing
and backstop wiring can be verified without any model call. Critically, these
tests assert that no content is ever merged deterministically: merges only
happen when the (stub) model returns a merged proposal, and genuinely distinct
proposals never trigger the backstop at all.
"""

import asyncio

from api.services.memory.proposal_store import ProposalStore
from api.services.skills.skill_evaluator import SkillProposal
from api.services.skills.skill_proposal_applier import apply_skill_proposals
from api.services.skills.skill_service import SkillService
from api.services.skills.skill_store import SkillStore


def _valid_procedure(topic: str) -> str:
    return (
        f"1. Open the {topic} source material and review its structure.\n"
        f"2. Apply the {topic} transformation steps carefully and consistently.\n"
        f"3. Verify the {topic} output matches the expected result before finishing."
        " Repeat the verification pass to ensure nothing was dropped or corrupted."
    )


def _proposal(title: str, topic: str, *, task_ids, **overrides) -> SkillProposal:
    base = dict(
        title=title,
        when_to_use=f"Use when the user wants to {topic} as part of their workflow today.",
        triggers=[topic, f"{topic} request"],
        procedure_markdown=_valid_procedure(topic),
        expected_result=f"The {topic} completes successfully.",
        source_task_ids=list(task_ids),
    )
    base.update(overrides)
    return SkillProposal(**base)


class _NoCallEvaluator:
    """Evaluator stub that must never have its merge pass invoked."""

    def __init__(self) -> None:
        self.calls = 0

    async def confirm_or_merge_overlap(self, new_proposal, target):
        self.calls += 1
        raise AssertionError("confirm_or_merge_overlap should not be called")


class _MergingEvaluator:
    """Evaluator stub that merges by folding the new proposal into the target."""

    def __init__(self) -> None:
        self.calls = 0

    async def confirm_or_merge_overlap(self, new_proposal, target):
        self.calls += 1
        return new_proposal.model_copy(update={"enhances_candidate_id": target.id})


class _DistinctEvaluator:
    """Evaluator stub that confirms the two candidates are distinct."""

    def __init__(self) -> None:
        self.calls = 0

    async def confirm_or_merge_overlap(self, new_proposal, target):
        self.calls += 1
        return None


def _store(tmp_path) -> ProposalStore:
    return ProposalStore(path=tmp_path / "proposal_store.json")


def _service(tmp_path) -> SkillService:
    return SkillService(store=SkillStore(skills_dir=tmp_path / "skills"))


def test_enhances_candidate_replaces_in_place(tmp_path) -> None:
    store = _store(tmp_path)
    service = _service(tmp_path)
    [existing] = store.enqueue_skill_candidates(
        [_proposal("Convert PDF", "convert pdf markdown", task_ids=["t1"])],
        source="test",
    )
    new_proposal = _proposal(
        "Convert PDF With Tables",
        "convert pdf markdown tables",
        task_ids=["t2"],
        enhances_candidate_id=existing.id,
    )
    evaluator = _NoCallEvaluator()

    applied = asyncio.run(
        apply_skill_proposals(
            [new_proposal], evaluator=evaluator, source="test", store=store, skill_service=service
        )
    )

    pending = store.list_pending_skill_candidates()
    assert applied == 1
    assert evaluator.calls == 0
    assert len(pending) == 1
    assert pending[0].id == existing.id
    assert pending[0].title == "Convert PDF With Tables"
    assert "tables" in pending[0].procedure_markdown


def test_enhances_skill_stages_candidate_without_touching_live_skill(tmp_path) -> None:
    store = _store(tmp_path)
    service = _service(tmp_path)
    saved = service.save_skill(
        title="PDF Helper",
        body=_valid_procedure("convert pdf markdown original"),
        when_to_use="Use when converting pdf files into markdown for the user.",
        triggers=["convert pdf", "pdf to markdown"],
        source_task_ids=["saved-task"],
    )
    new_proposal = _proposal(
        "PDF Helper Plus",
        "convert pdf markdown tables",
        task_ids=["t9"],
        enhances_skill_slug=saved.slug,
    )
    evaluator = _NoCallEvaluator()

    applied = asyncio.run(
        apply_skill_proposals(
            [new_proposal], evaluator=evaluator, source="test", store=store, skill_service=service
        )
    )

    pending = store.list_pending_skill_candidates()
    assert applied == 1
    assert evaluator.calls == 0
    assert len(pending) == 1
    assert pending[0].enhances_skill_slug == saved.slug
    # The live skill body is untouched until the user approves the staged candidate.
    assert service.load_skill(saved.slug, mark_used=False).body == saved.body


def test_new_proposal_with_no_pending_is_appended(tmp_path) -> None:
    store = _store(tmp_path)
    service = _service(tmp_path)
    evaluator = _NoCallEvaluator()

    applied = asyncio.run(
        apply_skill_proposals(
            [_proposal("Brand New Skill", "summarize spreadsheets", task_ids=["t1"])],
            evaluator=evaluator,
            source="test",
            store=store,
            skill_service=service,
        )
    )

    assert applied == 1
    assert evaluator.calls == 0
    assert len(store.list_pending_skill_candidates()) == 1


def test_backstop_merges_model_missed_overlap(tmp_path) -> None:
    store = _store(tmp_path)
    service = _service(tmp_path)
    [existing] = store.enqueue_skill_candidates(
        [_proposal("Convert PDF", "convert pdf markdown", task_ids=["shared"])],
        source="test",
    )
    # Model returned a "new" proposal (no enhance flags) that actually overlaps
    # via a shared source task; the deterministic backstop must route it to the
    # model, which merges it in place.
    new_proposal = _proposal(
        "Convert PDF Variant",
        "convert pdf markdown tables",
        task_ids=["shared"],
    )
    evaluator = _MergingEvaluator()

    applied = asyncio.run(
        apply_skill_proposals(
            [new_proposal], evaluator=evaluator, source="test", store=store, skill_service=service
        )
    )

    pending = store.list_pending_skill_candidates()
    assert applied == 1
    assert evaluator.calls == 1
    assert len(pending) == 1
    assert pending[0].id == existing.id
    assert pending[0].title == "Convert PDF Variant"


def test_backstop_confirms_distinct_keeps_both(tmp_path) -> None:
    store = _store(tmp_path)
    service = _service(tmp_path)
    store.enqueue_skill_candidates(
        [_proposal("Convert PDF", "convert pdf markdown", task_ids=["shared"])],
        source="test",
    )
    new_proposal = _proposal(
        "Convert PDF Variant",
        "convert pdf markdown tables",
        task_ids=["shared"],
    )
    evaluator = _DistinctEvaluator()

    applied = asyncio.run(
        apply_skill_proposals(
            [new_proposal], evaluator=evaluator, source="test", store=store, skill_service=service
        )
    )

    assert applied == 1
    assert evaluator.calls == 1
    assert len(store.list_pending_skill_candidates()) == 2


def test_distinct_proposal_never_triggers_backstop(tmp_path) -> None:
    store = _store(tmp_path)
    service = _service(tmp_path)
    scheduling_candidate = SkillProposal(
        title="Schedule Calendar Meeting",
        when_to_use="Invoke whenever somebody asks to book a calendar slot with several colleagues.",
        triggers=["book meeting", "calendar slot"],
        procedure_markdown=(
            "1. Collect the attendee emails and preferred dates directly from the requester.\n"
            "2. Check each colleague's availability inside the shared calendar grid thoroughly.\n"
            "3. Send the invitation and confirm acceptance from everyone who was involved."
        ),
        expected_result="A confirmed meeting appears on the calendar.",
        source_task_ids=["task-c"],
    )
    store.enqueue_skill_candidates([scheduling_candidate], source="test")
    # Genuinely distinct: different vocabulary and no shared source task. The
    # merging stub would merge if invoked, so calls staying at 0 proves the
    # deterministic layer never merges on its own.
    new_proposal = SkillProposal(
        title="Convert PDF Into Markdown",
        when_to_use="Trigger this for turning a downloaded document file into formatted text output.",
        triggers=["pdf conversion", "markdown export"],
        procedure_markdown=(
            "1. Load the binary report and extract its raw textual layers for parsing.\n"
            "2. Reconstruct headings, tables, and bulleted lists as clean rendered syntax.\n"
            "3. Save the rewritten artifact and compare it against the original page layout."
        ),
        expected_result="A faithful markdown rendering is produced.",
        source_task_ids=["task-p"],
    )
    evaluator = _MergingEvaluator()

    applied = asyncio.run(
        apply_skill_proposals(
            [new_proposal], evaluator=evaluator, source="test", store=store, skill_service=service
        )
    )

    assert applied == 1
    assert evaluator.calls == 0
    assert len(store.list_pending_skill_candidates()) == 2
