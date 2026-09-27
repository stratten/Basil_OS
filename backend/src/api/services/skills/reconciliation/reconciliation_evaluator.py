"""Model methods the reconciliation workspace needs beyond the base evaluator.

The existing :class:`SkillEvaluator` already knows how to (a) turn a task into a
proposal and (b) confirm/merge a *new* proposal against one pending candidate.
Reconciliation needs two additional model operations, kept here to isolate their
prompts and to keep ``skill_evaluator.py`` under its size cap:

- ``merge_candidate_group``: fold N already-pending candidates that the
  deterministic detector clustered together into a single cohesive proposal.
- ``reconcile_candidate_with_saved_skill``: decide whether a pending candidate
  enhances / duplicates / is distinct from an approved saved skill, returning the
  model-merged enhanced body when it enhances.

All merging is model-produced; this module never combines text deterministically.
It composes a :class:`SkillEvaluator` to reuse model resolution and the tolerant
JSON parsing helpers rather than duplicating them.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ValidationError

from api.services.agent_processing.lifecycle.execution_graph.agent_model_caller import (
    call_agent_model_with_messages,
)
from api.services.memory.proposal_store import SkillCandidateRecord
from api.services.skills.skill_evaluator import (
    SkillEvaluator,
    SkillProposal,
)


logger = logging.getLogger(__name__)

# Relationship verdicts returned by reconcile_candidate_with_saved_skill.
RELATIONSHIP_ENHANCE = "enhance"
RELATIONSHIP_DUPLICATE = "duplicate"
RELATIONSHIP_DISTINCT = "distinct"


@dataclass(frozen=True)
class ReconcileResult:
    """Outcome of comparing one pending candidate to one saved skill."""

    relationship: str
    merged: Optional[SkillProposal] = None


class _ReconcileVerdictResponse(BaseModel):
    """Strict envelope for the candidate-vs-saved-skill decision."""

    relationship: str
    merged: Optional[SkillProposal] = None


class ReconciliationEvaluator:
    """Model-driven merges/decisions for the reconciliation workspace."""

    def __init__(self, evaluator: Optional[SkillEvaluator] = None) -> None:
        self._evaluator = evaluator or SkillEvaluator()

    async def merge_candidate_group(
        self,
        records: List[SkillCandidateRecord],
    ) -> Optional[SkillProposal]:
        """Fold a cluster of pending candidates into one cohesive proposal."""
        if len(records) < 2:
            return None
        model = await self._evaluator._resolve_model()
        response_text = await call_agent_model_with_messages(
            model,
            [
                {"role": "system", "content": self._merge_group_system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"candidates": [self._serialize_candidate(r) for r in records]},
                        ensure_ascii=False,
                    ),
                },
            ],
            enable_web_search=False,
        )
        merged = self._evaluator._parse_single_response(response_text)
        if merged is None:
            return None
        union_task_ids = self._union(
            [tid for record in records for tid in record.source_task_ids],
            merged.source_task_ids,
        )
        return merged.model_copy(
            update={
                "source_task_ids": union_task_ids,
                "enhances_candidate_id": None,
                "enhances_skill_slug": None,
            }
        )

    async def reconcile_candidate_with_saved_skill(
        self,
        candidate: SkillCandidateRecord,
        saved_skill: Dict[str, Any],
    ) -> ReconcileResult:
        """Decide enhance/duplicate/distinct for a candidate vs a saved skill."""
        model = await self._evaluator._resolve_model()
        response_text = await call_agent_model_with_messages(
            model,
            [
                {"role": "system", "content": self._reconcile_saved_system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "pending_candidate": self._serialize_candidate(candidate),
                            "saved_skill": self._serialize_saved_skill(saved_skill),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            enable_web_search=False,
        )
        return self._parse_reconcile_response(response_text, candidate, saved_skill)

    def _parse_reconcile_response(
        self,
        response_text: str,
        candidate: SkillCandidateRecord,
        saved_skill: Dict[str, Any],
    ) -> ReconcileResult:
        try:
            payload = self._evaluator._parse_json_object_response(response_text)
            verdict = _ReconcileVerdictResponse(**payload)
        except (TypeError, json.JSONDecodeError, ValidationError) as exc:
            logger.info(
                "ReconciliationEvaluator got invalid JSON/schema for candidate-vs-skill; "
                "treating as distinct. error=%s",
                exc,
            )
            return ReconcileResult(relationship=RELATIONSHIP_DISTINCT, merged=None)

        relationship = verdict.relationship.strip().casefold()
        if relationship == RELATIONSHIP_ENHANCE and verdict.merged is not None:
            union_task_ids = self._union(
                candidate.source_task_ids,
                [str(t) for t in saved_skill.get("source_task_ids", []) if t],
                verdict.merged.source_task_ids,
            )
            merged = verdict.merged.model_copy(
                update={
                    "source_task_ids": union_task_ids,
                    "enhances_candidate_id": None,
                    "enhances_skill_slug": str(saved_skill.get("slug") or ""),
                }
            )
            return ReconcileResult(relationship=RELATIONSHIP_ENHANCE, merged=merged)
        if relationship == RELATIONSHIP_DUPLICATE:
            return ReconcileResult(relationship=RELATIONSHIP_DUPLICATE, merged=None)
        return ReconcileResult(relationship=RELATIONSHIP_DISTINCT, merged=None)

    def _merge_group_system_prompt(self) -> str:
        return (
            "You are given a list of pending Basil skill candidates that a detector "
            "flagged as describing overlapping reusable operations. Fold them into a "
            "SINGLE cohesive skill proposal that captures the shared procedure and "
            "incorporates every genuinely net-new step, unioning triggers and "
            "source_task_ids. Return strict JSON only: {\"candidate\":null} if they are "
            "actually NOT the same operation and must stay separate, OR "
            '{"candidate":{"title":"6-80 chars","when_to_use":"30-280 chars",'
            '"triggers":["2-8 concise semantic triggers"],'
            '"procedure_markdown":"200-1700 chars with at least three numbered steps",'
            '"expected_result":"what success should look like",'
            '"source_task_ids":["unioned task ids"]}}. '
            "Do not include markdown fences or prose outside JSON."
        )

    def _reconcile_saved_system_prompt(self) -> str:
        return (
            "You are given pending_candidate (a not-yet-approved skill candidate) and "
            "saved_skill (an already-approved skill with its full body). Decide their "
            "relationship. Return strict JSON only. Use "
            '{"relationship":"distinct","merged":null} when the candidate is a genuinely '
            "different operation the saved skill does not cover; use "
            '{"relationship":"duplicate","merged":null} when the saved skill already fully '
            "covers the candidate with nothing net-new; use "
            '{"relationship":"enhance","merged":{"title":"6-80 chars",'
            '"when_to_use":"30-280 chars","triggers":["2-8 concise semantic triggers"],'
            '"procedure_markdown":"200-1700 chars with at least three numbered steps",'
            '"expected_result":"what success should look like",'
            '"source_task_ids":["unioned task ids"]}} when the candidate adds net-new steps '
            "to the same operation - merged must be the full cohesive enhanced skill body "
            "that folds the saved skill and the candidate together. "
            "Do not include markdown fences or prose outside JSON."
        )

    def _serialize_candidate(self, record: SkillCandidateRecord) -> Dict[str, Any]:
        return {
            "id": record.id,
            "title": record.title,
            "when_to_use": record.when_to_use,
            "triggers": list(record.triggers),
            "procedure_markdown": record.procedure_markdown,
            "expected_result": record.expected_result,
            "source_task_ids": list(record.source_task_ids),
        }

    def _serialize_saved_skill(self, saved_skill: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "slug": saved_skill.get("slug"),
            "title": saved_skill.get("title"),
            "when_to_use": saved_skill.get("when_to_use"),
            "triggers": list(saved_skill.get("triggers", []) or []),
            "source_task_ids": list(saved_skill.get("source_task_ids", []) or []),
            "body": saved_skill.get("body"),
        }

    def _union(self, *lists: List[str]) -> List[str]:
        seen: Dict[str, None] = {}
        for values in lists:
            for value in values or []:
                text = str(value).strip()
                if text and text not in seen:
                    seen[text] = None
        return list(seen.keys())
