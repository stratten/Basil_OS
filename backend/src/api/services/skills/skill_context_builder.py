"""Assemble the existing-skill context shown to the SkillEvaluator.

This is the single shared builder used by the per-task evaluator, the daily
sweep, and the manual "save as skill" preview route. It collects pending skill
candidates and approved saved skills, ranks them against the task text via the
deterministic :mod:`skill_overlap` detector, and includes full bodies only for
the most relevant few so the evaluator can decide enhance-vs-new without an
unbounded prompt.
"""

from __future__ import annotations

import logging
from typing import List

from api.services.memory.proposal_store import SkillCandidateRecord, get_proposal_store
from api.services.skills import skill_overlap
from api.services.skills.skill_evaluator import (
    CompletedTask,
    ExistingSkillContext,
    PendingCandidateView,
    SavedSkillView,
)
from api.services.skills.skill_service import get_skill_service


logger = logging.getLogger(__name__)


def compose_task_text(*tasks: CompletedTask) -> str:
    """Build the searchable text used to rank existing skills against task(s)."""
    parts: List[str] = []
    for task in tasks:
        for value in (
            task.title,
            task.original_prompt,
            task.transcribed_prompt,
            task.result_summary,
        ):
            if value:
                parts.append(str(value))
        for step in task.intermediate_step_summaries or []:
            tool_name = step.get("tool") if isinstance(step, dict) else None
            if tool_name:
                parts.append(str(tool_name))
    return "\n".join(parts)


def build_existing_skill_context(task_text: str) -> ExistingSkillContext:
    """Return pending candidates + saved skills, with bodies for the top matches."""
    pending_records = _load_pending_candidates()
    catalog_entries = _load_saved_skill_catalog()

    rankable = [
        skill_overlap.RankableItem(
            key=record.id,
            text=_candidate_text(record),
        )
        for record in pending_records
    ] + [
        skill_overlap.RankableItem(
            key=entry.slug,
            text=_catalog_text(entry),
        )
        for entry in catalog_entries
    ]

    body_keys = skill_overlap.select_body_keys(task_text, rankable)

    pending_candidates = [
        PendingCandidateView(
            id=record.id,
            title=record.title,
            when_to_use=record.when_to_use,
            triggers=list(record.triggers),
            source_task_ids=list(record.source_task_ids),
            procedure_markdown=(
                record.procedure_markdown if record.id in body_keys else None
            ),
        )
        for record in pending_records
    ]

    saved_skills = [
        _saved_skill_view(entry, include_body=entry.slug in body_keys)
        for entry in catalog_entries
    ]

    return ExistingSkillContext(
        pending_candidates=pending_candidates,
        saved_skills=saved_skills,
    )


def build_context_for_completed_tasks(*tasks: CompletedTask) -> ExistingSkillContext:
    """Convenience wrapper: compose task text and build the context in one call."""
    return build_existing_skill_context(compose_task_text(*tasks))


def _load_pending_candidates() -> List[SkillCandidateRecord]:
    try:
        return get_proposal_store().list_pending_skill_candidates()
    except Exception:
        logger.exception("Failed to load pending skill candidates for evaluator context")
        return []


def _load_saved_skill_catalog():
    try:
        return get_skill_service().store.list_skill_catalog_entries()
    except Exception:
        logger.exception("Failed to load saved skill catalog for evaluator context")
        return []


def _saved_skill_view(entry, *, include_body: bool) -> SavedSkillView:
    body = None
    source_task_ids: List[str] = []
    if include_body:
        try:
            record = get_skill_service().store.read_skill(entry.slug)
            body = record.body
            source_task_ids = [
                str(task_id)
                for task_id in record.metadata.get("source_task_ids", [])
                if task_id
            ]
        except Exception:
            logger.exception("Failed to read saved skill body for '%s'", entry.slug)
            body = None
    return SavedSkillView(
        slug=entry.slug,
        title=entry.title,
        when_to_use=entry.when_to_use,
        triggers=list(getattr(entry, "triggers", []) or []),
        source_task_ids=source_task_ids,
        body=body,
    )


def _candidate_text(record: SkillCandidateRecord) -> str:
    return " ".join(
        [record.title, record.when_to_use, *record.triggers]
    )


def _catalog_text(entry) -> str:
    triggers = list(getattr(entry, "triggers", []) or [])
    return " ".join([entry.title, entry.when_to_use, *triggers])
