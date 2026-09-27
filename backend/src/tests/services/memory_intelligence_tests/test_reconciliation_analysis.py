"""Analysis routing: clustering + candidate/saved-skill matching via a fake model.

`reconciliation_analysis` is pure orchestration over the deterministic
`skill_overlap` detector; the model is injected, so these tests assert *which*
comparisons run and *which* action kinds are emitted, with no real model.
"""

import asyncio
from typing import Any, Dict, List, Optional

from api.services.memory.proposal_store import SkillCandidateRecord
from api.services.skills.reconciliation import reconciliation_analysis
from api.services.skills.reconciliation.reconciliation_evaluator import (
    RELATIONSHIP_DISTINCT,
    RELATIONSHIP_DUPLICATE,
    RELATIONSHIP_ENHANCE,
    ReconcileResult,
)
from api.services.skills.reconciliation.reconciliation_session import (
    KIND_DUPLICATE_OF_SAVED_SKILL,
    KIND_ENHANCE_SAVED_SKILL,
    KIND_KEEP_NEW,
    KIND_MERGE_CANDIDATES,
)
from api.services.skills.skill_evaluator import SkillProposal


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


def _candidate(
    cid: str,
    *,
    title: str,
    when: str,
    triggers: List[str],
    marker: str,
    source_task_ids: List[str],
    procedure: Optional[str] = None,
) -> SkillCandidateRecord:
    return SkillCandidateRecord(
        id=cid,
        title=title,
        when_to_use=when,
        triggers=triggers,
        procedure_markdown=procedure if procedure is not None else _procedure(marker),
        expected_result=f"The {marker} workflow finishes.",
        source_task_ids=source_task_ids,
        source="test",
        created_at="2026-07-01T00:00:00+00:00",
    )


def _proposal(title: str, marker: str) -> SkillProposal:
    return SkillProposal(
        title=title,
        when_to_use=f"Use the {marker} workflow when needed during the day.",
        triggers=[marker, f"{marker} request"],
        procedure_markdown=_procedure(marker),
        expected_result=f"The {marker} workflow finishes.",
        source_task_ids=["task-merged"],
    )


class _FakeEvaluator:
    """Records calls and returns scripted merge/relationship verdicts."""

    def __init__(
        self,
        *,
        merge_result: Optional[SkillProposal] = None,
        reconcile_result: Optional[ReconcileResult] = None,
    ) -> None:
        self.merge_result = merge_result
        self.reconcile_result = reconcile_result or ReconcileResult(RELATIONSHIP_DISTINCT)
        self.merge_calls: List[List[str]] = []
        self.reconcile_calls: List[str] = []

    async def merge_candidate_group(self, records):
        self.merge_calls.append([r.id for r in records])
        return self.merge_result

    async def reconcile_candidate_with_saved_skill(self, candidate, saved_skill):
        self.reconcile_calls.append(candidate.id)
        return self.reconcile_result


def _collect(pending, saved, evaluator):
    async def _run():
        return [
            action
            async for action in reconciliation_analysis.run_analysis(
                pending=pending, saved_skills=saved, evaluator=evaluator
            )
        ]

    return asyncio.run(_run())


def test_overlapping_candidates_cluster_and_route_to_merge():
    # Shared source_task_ids force a strong deterministic overlap → one cluster.
    a = _candidate(
        "c-a", title="Invoice A", when="process invoice", triggers=["invoice"],
        marker="invoice", source_task_ids=["task-1"],
    )
    b = _candidate(
        "c-b", title="Invoice B", when="process invoice", triggers=["invoice"],
        marker="invoice", source_task_ids=["task-1"],
    )
    evaluator = _FakeEvaluator(merge_result=_proposal("Unified Invoice", "invoice"))

    actions = _collect([a, b], [], evaluator)

    assert len(actions) == 1
    assert actions[0].kind == KIND_MERGE_CANDIDATES
    assert set(actions[0].source_candidate_ids) == {"c-a", "c-b"}
    assert evaluator.merge_calls == [["c-a", "c-b"]]
    assert actions[0].merged_title == "Unified Invoice"


def test_distinct_candidates_produce_keep_new_each():
    a = _candidate(
        "c-a", title="Invoice reconciliation", when="reconcile monthly vendor invoices",
        triggers=["invoice"], marker="invoice", source_task_ids=["task-a"],
        procedure="1. Open the accounting ledger and locate unpaid vendor bills.",
    )
    b = _candidate(
        "c-b", title="Photo resizing", when="shrink vacation photographs for email",
        triggers=["photo"], marker="photo", source_task_ids=["task-b"],
        procedure="1. Launch the image editor and crop each holiday snapshot.",
    )
    evaluator = _FakeEvaluator()

    actions = _collect([a, b], [], evaluator)

    assert {a.kind for a in actions} == {KIND_KEEP_NEW}
    assert len(actions) == 2
    # No clustering happened, so the merge model was never called.
    assert evaluator.merge_calls == []


def test_candidate_covered_by_saved_skill_is_flagged_duplicate():
    candidate = _candidate(
        "c-a", title="Invoice work", when="process invoices",
        triggers=["invoice"], marker="invoice", source_task_ids=["task-shared"],
    )
    saved = {
        "slug": "invoice-workflow",
        "title": "Invoice workflow",
        "when_to_use": "process invoices",
        "triggers": ["invoice"],
        "body": _procedure("invoice"),
        "source_task_ids": ["task-shared"],
    }
    evaluator = _FakeEvaluator(reconcile_result=ReconcileResult(RELATIONSHIP_DUPLICATE))

    actions = _collect([candidate], [saved], evaluator)

    assert len(actions) == 1
    assert actions[0].kind == KIND_DUPLICATE_OF_SAVED_SKILL
    assert actions[0].target_skill_slug == "invoice-workflow"
    assert evaluator.reconcile_calls == ["c-a"]


def test_candidate_enhancing_saved_skill_carries_merged_body():
    candidate = _candidate(
        "c-a", title="Invoice work", when="process invoices",
        triggers=["invoice"], marker="invoice", source_task_ids=["task-shared"],
    )
    saved = {
        "slug": "invoice-workflow",
        "title": "Invoice workflow",
        "when_to_use": "process invoices",
        "triggers": ["invoice"],
        "body": _procedure("invoice"),
        "source_task_ids": ["task-shared"],
    }
    merged = _proposal("Invoice workflow (enhanced)", "invoice")
    evaluator = _FakeEvaluator(
        reconcile_result=ReconcileResult(RELATIONSHIP_ENHANCE, merged=merged)
    )

    actions = _collect([candidate], [saved], evaluator)

    assert len(actions) == 1
    assert actions[0].kind == KIND_ENHANCE_SAVED_SKILL
    assert actions[0].target_skill_slug == "invoice-workflow"
    assert actions[0].merged_title == "Invoice workflow (enhanced)"
