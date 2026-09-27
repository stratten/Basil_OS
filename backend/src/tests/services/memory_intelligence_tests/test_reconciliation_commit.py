"""Reconciliation commit: per-kind application, backups, drift-skips, idempotency."""

from pathlib import Path

import pytest

from api.services.memory.memory_evaluator import MemoryProposal
from api.services.memory.proposal_store import ProposalStore
from api.services.skills.reconciliation.reconciliation_commit import ReconciliationCommitter
from api.services.skills.reconciliation.reconciliation_session import (
    DECISION_ACCEPTED,
    DECISION_REJECTED,
    KIND_DELETE_SAVED_SKILL,
    KIND_DUPLICATE_OF_SAVED_SKILL,
    KIND_ENHANCE_SAVED_SKILL,
    KIND_KEEP_NEW,
    KIND_MERGE_CANDIDATES,
    ProposedAction,
    ReconciliationSessionStore,
    SessionSnapshot,
)
from api.services.skills.skill_evaluator import SkillProposal
from api.services.skills.skill_service import SkillService
from api.services.skills.skill_store import SkillNotFoundError, SkillStore


def _procedure(marker: str) -> str:
    # Long enough (>=200 chars) to satisfy SkillProposal validation regardless
    # of the marker length.
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


def _action(kind: str, **kwargs) -> ProposedAction:
    action = ProposedAction(id=f"action-{kind}", kind=kind, **kwargs)
    action.decision = DECISION_ACCEPTED
    return action


@pytest.fixture
def env(tmp_path):
    """Isolated proposal store, skill service, session store, and backup root."""
    store = ProposalStore(path=tmp_path / "proposal_store.json")
    service = SkillService(store=SkillStore(skills_dir=tmp_path / "skills"))
    session_store = ReconciliationSessionStore()
    backup_root = tmp_path / "backups"

    def committer() -> ReconciliationCommitter:
        return ReconciliationCommitter(
            session_store=session_store,
            proposal_store=store,
            skill_service=service,
            backup_root=backup_root,
        )

    def start(actions):
        session = session_store.create(
            SessionSnapshot(captured_at="t", pending_candidates=[], saved_skills=[])
        )
        for action in actions:
            session_store.append_action(action)
        return session

    return {
        "store": store,
        "service": service,
        "session_store": session_store,
        "backup_root": backup_root,
        "committer": committer,
        "start": start,
    }


def test_keep_new_creates_skill_and_approves_candidate(env):
    [record] = env["store"].enqueue_skill_candidates(
        [_proposal("Convert PDF", "convert-pdf")], source="test"
    )
    env["start"]([
        _action(
            KIND_KEEP_NEW,
            source_candidate_ids=[record.id],
            merged_title="Convert PDF",
            merged_when_to_use="Use when converting pdf files for the user.",
            merged_triggers=["convert pdf"],
            merged_procedure_markdown=_procedure("convert-pdf"),
            merged_expected_result="Done.",
            merged_source_task_ids=["task-1"],
        )
    ])

    report = env["committer"]().commit()

    assert len(report["applied"]) == 1
    assert report["skipped"] == []
    assert len(env["service"].list_skills()) == 1
    assert env["store"].get_skill_candidate(record.id).status == "approved"


def test_enhance_overwrites_skill_writes_backup_and_approves(env):
    saved = env["service"].save_skill(
        title="PDF Helper",
        body=_procedure("original-pdf"),
        when_to_use="Use when converting pdf files into markdown for the user.",
        triggers=["convert pdf"],
        source_task_ids=["saved-task"],
    )
    [record] = env["store"].enqueue_skill_candidates(
        [_proposal("PDF Helper Enhanced", "enhanced-pdf")], source="test"
    )
    env["start"]([
        _action(
            KIND_ENHANCE_SAVED_SKILL,
            source_candidate_ids=[record.id],
            target_skill_slug=saved.slug,
            merged_title="PDF Helper",
            merged_when_to_use="Use when converting pdf files into markdown for the user.",
            merged_triggers=["convert pdf"],
            merged_procedure_markdown=_procedure("enhanced-pdf"),
            merged_expected_result="Done.",
            merged_source_task_ids=["saved-task", "task-1"],
        )
    ])

    report = env["committer"]().commit()

    assert len(report["applied"]) == 1
    overwritten = env["service"].load_skill(saved.slug, mark_used=False)
    assert "enhanced-pdf" in overwritten.body
    assert "original-pdf" not in overwritten.body
    assert env["store"].get_skill_candidate(record.id).status == "approved"
    # A pre-image backup of the original skill was written.
    backup_dir = env["backup_root"] / report["session_id"] / saved.slug
    assert backup_dir.is_dir()
    assert any(backup_dir.iterdir())


def test_merge_replaces_survivor_and_declines_others(env):
    [c1, c2] = env["store"].enqueue_skill_candidates(
        [_proposal("Dup One", "dup"), _proposal("Dup Two", "dup")], source="test"
    )
    env["start"]([
        _action(
            KIND_MERGE_CANDIDATES,
            source_candidate_ids=[c1.id, c2.id],
            merged_title="Merged Dup",
            merged_when_to_use="Use the merged workflow when needed.",
            merged_triggers=["dup"],
            merged_procedure_markdown=_procedure("merged"),
            merged_expected_result="Done.",
            merged_source_task_ids=["task-1"],
        )
    ])

    env["committer"]().commit()

    survivor = env["store"].get_skill_candidate(c1.id)
    assert survivor.status == "pending"
    assert survivor.title == "Merged Dup"
    assert env["store"].get_skill_candidate(c2.id).status == "declined"


def test_duplicate_declines_candidate(env):
    [record] = env["store"].enqueue_skill_candidates(
        [_proposal("Already Covered", "covered")], source="test"
    )
    env["start"]([
        _action(
            KIND_DUPLICATE_OF_SAVED_SKILL,
            source_candidate_ids=[record.id],
            target_skill_slug="existing-slug",
        )
    ])

    env["committer"]().commit()

    assert env["store"].get_skill_candidate(record.id).status == "declined"


def test_delete_removes_skill_and_writes_backup(env):
    saved = env["service"].save_skill(
        title="Obsolete Skill",
        body=_procedure("obsolete"),
        when_to_use="Use when the obsolete workflow is triggered by the user.",
        triggers=["obsolete"],
        source_task_ids=["t"],
    )
    env["start"]([
        _action(KIND_DELETE_SAVED_SKILL, target_skill_slug=saved.slug)
    ])

    report = env["committer"]().commit()

    assert len(report["applied"]) == 1
    with pytest.raises(SkillNotFoundError):
        env["service"].load_skill(saved.slug, mark_used=False)
    backup_dir = env["backup_root"] / report["session_id"] / saved.slug
    assert backup_dir.is_dir()
    assert any(backup_dir.iterdir())


def test_rejected_actions_are_never_applied(env):
    [record] = env["store"].enqueue_skill_candidates(
        [_proposal("Not Wanted", "nope")], source="test"
    )
    action = _action(KIND_KEEP_NEW, source_candidate_ids=[record.id])
    action.decision = DECISION_REJECTED
    env["start"]([action])

    report = env["committer"]().commit()

    assert report["applied"] == []
    assert report["skipped"] == []
    assert env["service"].list_skills() == []
    assert env["store"].get_skill_candidate(record.id).status == "pending"


def test_drifted_referents_are_skipped_not_crashed(env):
    # Accepted actions pointing at a candidate/skill that no longer exists must
    # be skipped with a note; the commit as a whole still succeeds.
    env["start"]([
        _action(
            KIND_KEEP_NEW,
            source_candidate_ids=["ghost-candidate"],
            merged_title="Ghost",
            merged_procedure_markdown=_procedure("ghost"),
        ),
        _action(
            KIND_ENHANCE_SAVED_SKILL,
            source_candidate_ids=["ghost-candidate"],
            target_skill_slug="ghost-slug",
        ),
    ])

    report = env["committer"]().commit()

    assert report["applied"] == []
    assert len(report["skipped"]) == 2
    assert all("reason" in entry for entry in report["skipped"])
    assert env["service"].list_skills() == []


def test_double_commit_is_rejected(env):
    [record] = env["store"].enqueue_skill_candidates(
        [_proposal("Commit Once", "once")], source="test"
    )
    env["start"]([
        _action(
            KIND_KEEP_NEW,
            source_candidate_ids=[record.id],
            merged_title="Commit Once",
            merged_procedure_markdown=_procedure("once"),
        )
    ])

    env["committer"]().commit()
    with pytest.raises(RuntimeError):
        env["committer"]().commit()


def test_memory_proposals_survive_a_skill_commit(env):
    # A memory proposal shares proposal_store.json with skill candidates. A
    # skills-only commit must leave it untouched (cross-store safety).
    [mem] = env["store"].enqueue_memory_proposals(
        [
            MemoryProposal(
                target_file="now.md",
                observation="User prefers concise summaries.",
                why="Stated repeatedly during review.",
                confidence="high",
            )
        ],
        source="test",
    )
    [record] = env["store"].enqueue_skill_candidates(
        [_proposal("Skill Keeper", "skill")], source="test"
    )
    env["start"]([
        _action(
            KIND_KEEP_NEW,
            source_candidate_ids=[record.id],
            merged_title="Skill Keeper",
            merged_procedure_markdown=_procedure("skill"),
        )
    ])

    env["committer"]().commit()

    pending_memory = env["store"].list_pending_memory_proposals()
    assert [m.id for m in pending_memory] == [mem.id]
