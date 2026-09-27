"""Apply evaluator skill proposals to the proposal store, enhancement-aware.

Routing for each proposal:
  * `enhances_candidate_id` set  -> replace that pending candidate in place.
  * `enhances_skill_slug` set    -> stage a candidate that overwrites the skill on approval.
  * otherwise (a "new" proposal) -> run the deterministic overlap detector as a
    backstop; if it flags a strong overlap with a pending candidate the model did
    not catch, ask the model (`confirm_or_merge_overlap`) to merge or confirm
    distinct. Merging is always model-produced; this module never combines text.

Stale references (an id/slug that no longer exists) degrade gracefully to the
new-candidate path so a proposal is never silently dropped.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from api.services.memory.proposal_store import (
    ProposalStore,
    SkillCandidateRecord,
    get_proposal_store,
)
from api.services.skills import skill_overlap
from api.services.skills.skill_evaluator import (
    PendingCandidateView,
    SkillEvaluator,
    SkillProposal,
)
from api.services.skills.skill_service import SkillService, get_skill_service


logger = logging.getLogger(__name__)


async def apply_skill_proposals(
    proposals: List[SkillProposal],
    *,
    evaluator: SkillEvaluator,
    source: str,
    store: Optional[ProposalStore] = None,
    skill_service: Optional[SkillService] = None,
) -> int:
    """Apply proposals and return how many candidates were added or updated."""
    if not proposals:
        return 0

    proposal_store = store or get_proposal_store()
    skills = skill_service or get_skill_service()

    applied = 0
    for proposal in proposals:
        if await _apply_single_proposal(proposal, evaluator, proposal_store, skills, source):
            applied += 1
    return applied


async def _apply_single_proposal(
    proposal: SkillProposal,
    evaluator: SkillEvaluator,
    proposal_store: ProposalStore,
    skills: SkillService,
    source: str,
) -> bool:
    if proposal.enhances_candidate_id and _replace_pending_candidate(
        proposal, proposal.enhances_candidate_id, proposal_store
    ):
        return True

    if proposal.enhances_skill_slug and _saved_skill_exists(
        proposal.enhances_skill_slug, skills
    ):
        _record_saved_skill_observation(proposal, skills)
        proposal_store.enqueue_skill_candidates([proposal], source=source)
        return True

    return await _apply_new_proposal(proposal, evaluator, proposal_store, source)


def _replace_pending_candidate(
    proposal: SkillProposal,
    candidate_id: str,
    proposal_store: ProposalStore,
) -> bool:
    target = _find_pending_candidate(candidate_id, proposal_store)
    if target is None:
        logger.info(
            "Proposal referenced unknown pending candidate '%s'; treating as new.",
            candidate_id,
        )
        return False
    proposal_store.replace_skill_candidate_content(
        candidate_id,
        title=proposal.title,
        when_to_use=proposal.when_to_use,
        triggers=list(proposal.triggers),
        procedure_markdown=proposal.procedure_markdown,
        expected_result=proposal.expected_result,
        source_task_ids=list(proposal.source_task_ids),
    )
    return True


async def _apply_new_proposal(
    proposal: SkillProposal,
    evaluator: SkillEvaluator,
    proposal_store: ProposalStore,
    source: str,
) -> bool:
    target = _detect_overlapping_candidate(proposal, proposal_store)
    if target is not None:
        merged = await evaluator.confirm_or_merge_overlap(
            proposal, _candidate_view(target, include_body=True)
        )
        if merged is not None and merged.enhances_candidate_id:
            if _replace_pending_candidate(
                merged, merged.enhances_candidate_id, proposal_store
            ):
                return True
    proposal_store.enqueue_skill_candidates([proposal], source=source)
    return True


def _detect_overlapping_candidate(
    proposal: SkillProposal,
    proposal_store: ProposalStore,
) -> Optional[SkillCandidateRecord]:
    proposal_text = _proposal_text(proposal)
    best: Optional[SkillCandidateRecord] = None
    best_score = 0.0
    for record in _list_pending(proposal_store):
        if not skill_overlap.proposal_overlaps_candidate(
            proposal_text=proposal_text,
            proposal_source_task_ids=proposal.source_task_ids,
            candidate_text=_record_text(record),
            candidate_source_task_ids=record.source_task_ids,
        ):
            continue
        score = skill_overlap.text_similarity(proposal_text, _record_text(record))
        if score >= best_score:
            best = record
            best_score = score
    return best


def _find_pending_candidate(
    candidate_id: str,
    proposal_store: ProposalStore,
) -> Optional[SkillCandidateRecord]:
    for record in _list_pending(proposal_store):
        if record.id == candidate_id:
            return record
    return None


def _list_pending(proposal_store: ProposalStore) -> List[SkillCandidateRecord]:
    try:
        return proposal_store.list_pending_skill_candidates()
    except Exception:
        logger.exception("Failed to list pending skill candidates during apply")
        return []


def _saved_skill_exists(slug: str, skills: SkillService) -> bool:
    try:
        return any(entry.slug == slug for entry in skills.store.list_skill_catalog_entries())
    except Exception:
        logger.exception("Failed to verify saved skill '%s' during apply", slug)
        return False


def _record_saved_skill_observation(proposal: SkillProposal, skills: SkillService) -> None:
    """Increment the target saved skill's recurrence counter at observation time.

    The staged enhancement candidate still carries the same source task ids, so
    the later approval union is a no-op against this increment (idempotent).
    """
    try:
        skills.record_skill_observation(
            proposal.enhances_skill_slug,
            source_task_ids=list(proposal.source_task_ids),
        )
    except Exception:
        logger.exception(
            "Failed to record observation on saved skill '%s' during apply",
            proposal.enhances_skill_slug,
        )


def _candidate_view(record: SkillCandidateRecord, *, include_body: bool) -> PendingCandidateView:
    return PendingCandidateView(
        id=record.id,
        title=record.title,
        when_to_use=record.when_to_use,
        triggers=list(record.triggers),
        source_task_ids=list(record.source_task_ids),
        procedure_markdown=record.procedure_markdown if include_body else None,
    )


def _proposal_text(proposal: SkillProposal) -> str:
    return " ".join(
        [proposal.title, proposal.when_to_use, *proposal.triggers, proposal.procedure_markdown]
    )


def _record_text(record: SkillCandidateRecord) -> str:
    return " ".join(
        [record.title, record.when_to_use, *record.triggers, record.procedure_markdown]
    )
