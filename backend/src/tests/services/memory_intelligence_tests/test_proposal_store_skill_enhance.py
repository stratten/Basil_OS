"""Tests for skill-candidate enhancement support in the proposal store."""

from api.services.memory.proposal_store import ProposalStore
from api.services.skills.skill_evaluator import SkillProposal


def _valid_procedure(topic: str) -> str:
    return (
        f"1. Open the {topic} source material and review its structure.\n"
        f"2. Apply the {topic} transformation steps carefully and consistently.\n"
        f"3. Verify the {topic} output matches the expected result before finishing."
        " Repeat the verification pass to ensure nothing was dropped or corrupted."
    )


def _proposal(**overrides) -> SkillProposal:
    base = dict(
        title="Convert PDF To Markdown",
        when_to_use="Use when the user wants to convert a pdf into markdown today.",
        triggers=["convert pdf", "pdf to markdown"],
        procedure_markdown=_valid_procedure("convert pdf markdown"),
        expected_result="The markdown is produced.",
        source_task_ids=["task-1"],
    )
    base.update(overrides)
    return SkillProposal(**base)


def test_enqueue_persists_enhances_skill_slug(tmp_path) -> None:
    store = ProposalStore(path=tmp_path / "proposal_store.json")
    store.enqueue_skill_candidates(
        [_proposal(enhances_skill_slug="pdf-to-markdown")],
        source="test",
    )
    pending = store.list_pending_skill_candidates()
    assert len(pending) == 1
    assert pending[0].enhances_skill_slug == "pdf-to-markdown"


def test_enqueue_defaults_enhances_skill_slug_to_none(tmp_path) -> None:
    store = ProposalStore(path=tmp_path / "proposal_store.json")
    store.enqueue_skill_candidates([_proposal()], source="test")
    assert store.list_pending_skill_candidates()[0].enhances_skill_slug is None


def test_replace_skill_candidate_content_unions_and_stays_pending(tmp_path) -> None:
    store = ProposalStore(path=tmp_path / "proposal_store.json")
    [record] = store.enqueue_skill_candidates(
        [
            _proposal(
                triggers=["convert pdf", "pdf to markdown"],
                source_task_ids=["task-1"],
            )
        ],
        source="test",
    )

    updated = store.replace_skill_candidate_content(
        record.id,
        title="Convert PDF To Markdown With Tables",
        when_to_use="Use when converting a pdf into markdown, including table layout, today.",
        triggers=["pdf to markdown", "preserve tables"],
        procedure_markdown=_valid_procedure("convert pdf markdown tables"),
        expected_result="The markdown with tables is produced.",
        source_task_ids=["task-2"],
    )

    assert updated.status == "pending"
    assert updated.updated_at is not None
    assert updated.title == "Convert PDF To Markdown With Tables"
    assert "tables" in updated.procedure_markdown
    # Triggers and source ids are unioned (existing first, then new, deduped).
    assert updated.triggers == ["convert pdf", "pdf to markdown", "preserve tables"]
    assert updated.source_task_ids == ["task-1", "task-2"]

    # The change is durable and the candidate is still the only pending one.
    reloaded = store.list_pending_skill_candidates()
    assert len(reloaded) == 1
    assert reloaded[0].id == record.id
    assert reloaded[0].source_task_ids == ["task-1", "task-2"]
