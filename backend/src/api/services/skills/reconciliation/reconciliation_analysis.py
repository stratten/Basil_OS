"""Decide *which* comparisons to run and emit reconciliation proposals.

This module is pure orchestration. It uses the deterministic
:mod:`skill_overlap` detector to (a) cluster pending candidates that look like
the same operation and (b) match each remaining candidate to the most similar
saved skill, then delegates every actual merge/relationship decision to an
injected evaluator (model-driven). It performs no I/O of its own beyond what is
passed in, so it can be unit tested with a fake evaluator and no model.

Contract notes for downstream commit:
- For a ``merge_candidates`` action, ``source_candidate_ids[0]`` is the survivor
  whose content is replaced with the merged body; the rest are declined.
- ``keep_new`` carries the candidate's own body so commit can save it verbatim.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Protocol

from api.services.memory.proposal_store import SkillCandidateRecord
from api.services.skills import skill_overlap
from api.services.skills.reconciliation.reconciliation_evaluator import (
    RELATIONSHIP_DUPLICATE,
    RELATIONSHIP_ENHANCE,
    ReconcileResult,
)
from api.services.skills.reconciliation.reconciliation_session import (
    KIND_DUPLICATE_OF_SAVED_SKILL,
    KIND_ENHANCE_SAVED_SKILL,
    KIND_KEEP_NEW,
    KIND_MERGE_CANDIDATES,
    ProposedAction,
)
from api.services.skills.skill_evaluator import SkillProposal


logger = logging.getLogger(__name__)


class _EvaluatorProtocol(Protocol):
    """Minimal surface the analysis needs; satisfied by ReconciliationEvaluator."""

    async def merge_candidate_group(
        self, records: List[SkillCandidateRecord]
    ) -> Optional[SkillProposal]:
        ...

    async def reconcile_candidate_with_saved_skill(
        self, candidate: SkillCandidateRecord, saved_skill: Dict[str, Any]
    ) -> ReconcileResult:
        ...


ProgressCallback = Callable[[int, int], Any]


async def run_analysis(
    *,
    pending: List[SkillCandidateRecord],
    saved_skills: List[Dict[str, Any]],
    evaluator: _EvaluatorProtocol,
    on_progress: Optional[ProgressCallback] = None,
) -> AsyncIterator[ProposedAction]:
    """Yield ProposedActions for the snapshot, calling the model where needed."""
    total = len(pending)
    processed = 0
    if not pending:
        if on_progress is not None:
            on_progress(0, 0)
        return

    clusters = _cluster_overlapping(pending)
    singletons: List[SkillCandidateRecord] = []

    for cluster in clusters:
        if len(cluster) >= 2:
            merged = await _safe_merge_group(evaluator, cluster)
            if merged is not None:
                yield _merge_action(cluster, merged)
                processed += len(cluster)
                if on_progress is not None:
                    on_progress(processed, total)
                continue
            # Model declined the merge: treat each as an individual candidate.
            singletons.extend(cluster)
        else:
            singletons.extend(cluster)

    for candidate in singletons:
        action = await _reconcile_singleton(candidate, saved_skills, evaluator)
        yield action
        processed += 1
        if on_progress is not None:
            on_progress(processed, total)


def _cluster_overlapping(
    records: List[SkillCandidateRecord],
) -> List[List[SkillCandidateRecord]]:
    """Union-find clustering of candidates that strongly overlap each other."""
    parent = list(range(len(records)))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            if _candidates_overlap(records[i], records[j]):
                union(i, j)

    groups: Dict[int, List[SkillCandidateRecord]] = {}
    for index, record in enumerate(records):
        groups.setdefault(find(index), []).append(record)
    return list(groups.values())


def _candidates_overlap(a: SkillCandidateRecord, b: SkillCandidateRecord) -> bool:
    return skill_overlap.proposal_overlaps_candidate(
        proposal_text=_candidate_text(a),
        proposal_source_task_ids=a.source_task_ids,
        candidate_text=_candidate_text(b),
        candidate_source_task_ids=b.source_task_ids,
    )


async def _safe_merge_group(
    evaluator: _EvaluatorProtocol,
    cluster: List[SkillCandidateRecord],
) -> Optional[SkillProposal]:
    try:
        return await evaluator.merge_candidate_group(cluster)
    except Exception:
        logger.exception("merge_candidate_group failed for cluster; treating as distinct")
        return None


async def _reconcile_singleton(
    candidate: SkillCandidateRecord,
    saved_skills: List[Dict[str, Any]],
    evaluator: _EvaluatorProtocol,
) -> ProposedAction:
    match = _best_saved_match(candidate, saved_skills)
    if match is None:
        return _keep_new_action(candidate)

    try:
        result = await evaluator.reconcile_candidate_with_saved_skill(candidate, match)
    except Exception:
        logger.exception(
            "reconcile_candidate_with_saved_skill failed for candidate %s; keeping as new",
            candidate.id,
        )
        return _keep_new_action(candidate)

    target_slug = str(match.get("slug") or "")
    if result.relationship == RELATIONSHIP_ENHANCE and result.merged is not None:
        return _enhance_action(candidate, target_slug, result.merged)
    if result.relationship == RELATIONSHIP_DUPLICATE:
        return _duplicate_action(candidate, target_slug, match)
    return _keep_new_action(candidate)


def _best_saved_match(
    candidate: SkillCandidateRecord,
    saved_skills: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    best: Optional[Dict[str, Any]] = None
    best_score = 0.0
    candidate_text = _candidate_text(candidate)
    for saved in saved_skills:
        saved_source_ids = [str(t) for t in saved.get("source_task_ids", []) if t]
        overlaps = skill_overlap.proposal_overlaps_candidate(
            proposal_text=candidate_text,
            proposal_source_task_ids=candidate.source_task_ids,
            candidate_text=_saved_skill_text(saved),
            candidate_source_task_ids=saved_source_ids,
        )
        if not overlaps:
            continue
        score = skill_overlap.text_similarity(candidate_text, _saved_skill_text(saved))
        if score >= best_score:
            best_score = score
            best = saved
    return best


def _merge_action(
    cluster: List[SkillCandidateRecord],
    merged: SkillProposal,
) -> ProposedAction:
    return ProposedAction(
        id=_action_id(),
        kind=KIND_MERGE_CANDIDATES,
        source_candidate_ids=[record.id for record in cluster],
        target_skill_slug=None,
        rationale=(
            f"Model folded {len(cluster)} overlapping pending candidates into one "
            "cohesive candidate."
        ),
        merged_title=merged.title,
        merged_when_to_use=merged.when_to_use,
        merged_triggers=list(merged.triggers),
        merged_procedure_markdown=merged.procedure_markdown,
        merged_expected_result=merged.expected_result,
        merged_source_task_ids=list(merged.source_task_ids),
    )


def _enhance_action(
    candidate: SkillCandidateRecord,
    target_slug: str,
    merged: SkillProposal,
) -> ProposedAction:
    return ProposedAction(
        id=_action_id(),
        kind=KIND_ENHANCE_SAVED_SKILL,
        source_candidate_ids=[candidate.id],
        target_skill_slug=target_slug,
        rationale=(
            f"Model judged this candidate to add net-new steps to saved skill "
            f"'{target_slug}' and produced a merged body."
        ),
        merged_title=merged.title,
        merged_when_to_use=merged.when_to_use,
        merged_triggers=list(merged.triggers),
        merged_procedure_markdown=merged.procedure_markdown,
        merged_expected_result=merged.expected_result,
        merged_source_task_ids=list(merged.source_task_ids),
    )


def _duplicate_action(
    candidate: SkillCandidateRecord,
    target_slug: str,
    match: Dict[str, Any],
) -> ProposedAction:
    return ProposedAction(
        id=_action_id(),
        kind=KIND_DUPLICATE_OF_SAVED_SKILL,
        source_candidate_ids=[candidate.id],
        target_skill_slug=target_slug,
        rationale=(
            f"Model judged saved skill '{target_slug}' already fully covers this "
            "candidate; accepting will decline the candidate."
        ),
    )


def _keep_new_action(candidate: SkillCandidateRecord) -> ProposedAction:
    return ProposedAction(
        id=_action_id(),
        kind=KIND_KEEP_NEW,
        source_candidate_ids=[candidate.id],
        target_skill_slug=None,
        rationale="No overlapping candidate or saved skill detected; keep as a new skill.",
        merged_title=candidate.title,
        merged_when_to_use=candidate.when_to_use,
        merged_triggers=list(candidate.triggers),
        merged_procedure_markdown=candidate.procedure_markdown,
        merged_expected_result=candidate.expected_result,
        merged_source_task_ids=list(candidate.source_task_ids),
    )


def _candidate_text(record: SkillCandidateRecord) -> str:
    return " ".join(
        [record.title, record.when_to_use, *record.triggers, record.procedure_markdown]
    )


def _saved_skill_text(saved: Dict[str, Any]) -> str:
    triggers = list(saved.get("triggers", []) or [])
    body = str(saved.get("body") or "")
    return " ".join(
        [
            str(saved.get("title") or ""),
            str(saved.get("when_to_use") or ""),
            *triggers,
            body,
        ]
    )


def _action_id() -> str:
    return f"action-{uuid.uuid4().hex}"
