"""Model-driven evaluator for reusable skill proposals."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field, ValidationError

from api.core.models.model_types import ModelCapability
from api.core.services.model_service import ModelService, get_model_service
from api.services.agent_processing.lifecycle.execution_graph.agent_model_caller import (
    call_agent_model_with_messages,
)
from api.services.skills.skill_store import SKILL_BODY_CAP_BYTES


logger = logging.getLogger(__name__)
MAX_SKILL_PROCEDURE_CHARS = min(1700, SKILL_BODY_CAP_BYTES - 256)


@dataclass(frozen=True)
class CompletedTask:
    """A completed task considered for possible skill capture."""

    id: str
    title: Optional[str]
    original_prompt: Optional[str]
    transcribed_prompt: Optional[str]
    result_summary: Optional[str]
    execution_timeline: List[Dict[str, Any]]
    intermediate_step_summaries: List[Dict[str, Any]]
    completed_at: Optional[str]


@dataclass(frozen=True)
class SkillCatalogEntry:
    """Metadata-only view of an existing skill."""

    slug: str
    title: str
    when_to_use: str


@dataclass(frozen=True)
class PendingCandidateView:
    """A pending skill candidate shown to the evaluator for overlap reasoning.

    `procedure_markdown` is populated only for the most-relevant candidates so
    the model can decide enhance-vs-new; otherwise it is None (metadata only).
    """

    id: str
    title: str
    when_to_use: str
    triggers: List[str]
    source_task_ids: List[str]
    procedure_markdown: Optional[str] = None


@dataclass(frozen=True)
class SavedSkillView:
    """An approved saved skill shown to the evaluator for overlap reasoning.

    `body` is populated only for the most-relevant skills; otherwise None.
    """

    slug: str
    title: str
    when_to_use: str
    triggers: List[str]
    source_task_ids: List[str]
    body: Optional[str] = None


@dataclass(frozen=True)
class ExistingSkillContext:
    """Everything the evaluator needs to deduplicate or enhance prior work."""

    pending_candidates: List[PendingCandidateView]
    saved_skills: List[SavedSkillView]

    @classmethod
    def empty(cls) -> "ExistingSkillContext":
        return cls(pending_candidates=[], saved_skills=[])


class SkillProposal(BaseModel):
    """A user-reviewable skill candidate produced by a reasoning model.

    When the model judges a task to be augmentative rather than novel, it may set
    exactly one of `enhances_candidate_id` (fold into an existing pending
    candidate) or `enhances_skill_slug` (stage an update to an approved saved
    skill). In both cases `procedure_markdown`, `triggers`, and `source_task_ids`
    represent the already-merged, cohesive result.
    """

    title: str = Field(min_length=6, max_length=80)
    when_to_use: str = Field(min_length=30, max_length=280)
    triggers: List[str] = Field(min_items=2, max_items=8)
    procedure_markdown: str = Field(min_length=200, max_length=MAX_SKILL_PROCEDURE_CHARS)
    expected_result: str = Field(min_length=1, max_length=500)
    source_task_ids: List[str] = Field(min_items=1, max_items=10)
    enhances_candidate_id: Optional[str] = None
    enhances_skill_slug: Optional[str] = None


class SingleSkillProposalResponse(BaseModel):
    """Strict response envelope for in-loop skill evaluation."""

    candidate: Optional[SkillProposal] = None


class SkillProposalBatchResponse(BaseModel):
    """Strict response envelope for daily skill evaluation."""

    candidates: List[SkillProposal] = Field(default_factory=list)


class SkillEvaluator:
    """Use a reasoning model to propose reusable skills for user review."""

    def __init__(
        self,
        *,
        model: Optional[Any] = None,
        model_id: Optional[str] = None,
        model_service: Optional[ModelService] = None,
    ) -> None:
        self.model = model
        self.model_id = model_id
        self.model_service = model_service or get_model_service()

    async def evaluate_completed_task(
        self,
        task: CompletedTask,
        existing_context: Optional[ExistingSkillContext] = None,
    ) -> Optional[SkillProposal]:
        """Evaluate one successful task as an optional skill proposal."""
        context = existing_context or ExistingSkillContext.empty()
        model = await self._resolve_model()
        response_text = await call_agent_model_with_messages(
            model,
            [
                {"role": "system", "content": self._build_single_task_system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": self._serialize_completed_task(task),
                            "existing_skills": self._serialize_existing_context(context),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            enable_web_search=False,
        )
        return self._parse_single_response(response_text)

    async def evaluate_recent_tasks(
        self,
        tasks: List[CompletedTask],
        existing_context: ExistingSkillContext,
    ) -> List[SkillProposal]:
        """Evaluate recent successful tasks as optional skill proposals."""
        if not tasks:
            return []

        model = await self._resolve_model()
        response_text = await call_agent_model_with_messages(
            model,
            [
                {"role": "system", "content": self._build_batch_system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "tasks": [self._serialize_completed_task(task) for task in tasks],
                            "existing_skills": self._serialize_existing_context(existing_context),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            enable_web_search=False,
        )
        return self._parse_batch_response(response_text)

    async def confirm_or_merge_overlap(
        self,
        new_proposal: SkillProposal,
        target: PendingCandidateView,
    ) -> Optional[SkillProposal]:
        """Backstop pass: ask the model whether a new proposal duplicates a candidate.

        Returns a single merged `SkillProposal` (with `enhances_candidate_id` set
        to `target.id`) when the two describe the same operation, or None when the
        model confirms they are genuinely distinct. The merge content is entirely
        model-produced; this method never combines text deterministically.
        """
        model = await self._resolve_model()
        response_text = await call_agent_model_with_messages(
            model,
            [
                {"role": "system", "content": self._build_merge_confirmation_system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "existing_candidate": self._serialize_pending_candidate(target),
                            "new_candidate": self._serialize_new_proposal(new_proposal),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            enable_web_search=False,
        )
        merged = self._parse_single_response(response_text)
        if merged is None:
            return None
        return merged.model_copy(
            update={
                "enhances_candidate_id": target.id,
                "enhances_skill_slug": None,
            }
        )

    async def _resolve_model(self) -> Any:
        if self.model is not None:
            return self.model
        if not self.model_id:
            raise ValueError("SkillEvaluator requires either model or model_id.")
        return await self.model_service.load_model_by_id(
            self.model_id,
            {ModelCapability.REASONING},
        )

    def _build_single_task_system_prompt(self) -> str:
        return (
            "You evaluate one successful Basil task and decide whether it deserves a reusable "
            "skill. The input includes existing_skills with pending_candidates (not yet "
            "approved) and saved_skills (already approved); items judged most relevant include "
            "their full body, others are metadata only. Return strict JSON only: "
            '{"candidate":null} OR {"candidate":{"title":"6-80 chars",'
            '"when_to_use":"30-280 chars",'
            '"triggers":["2-8 concise semantic triggers"],'
            '"procedure_markdown":"200-1700 chars with at least three numbered steps",'
            '"expected_result":"what success should look like",'
            '"source_task_ids":["task id"],'
            '"enhances_candidate_id":null,"enhances_skill_slug":null}}. '
            "Decide among four outcomes: (a) propose a brand-new skill; (b) ENHANCE an existing "
            "pending candidate when this task is the same operation with additional or refined "
            "steps, by setting enhances_candidate_id to that candidate's id; (c) ENHANCE an "
            "existing saved skill when it covers the same operation, by setting "
            "enhances_skill_slug to that skill's slug; or (d) return null when an existing skill "
            "already fully covers it with nothing new, the task was too one-off, or the trace "
            "lacks enough concrete procedure. When enhancing, set exactly one of "
            "enhances_candidate_id / enhances_skill_slug and return a single cohesive "
            "procedure_markdown that folds the overlapping steps and adds only the net-new "
            "aspects, with triggers and source_task_ids unioned across both. "
            "Do not include markdown fences or prose outside JSON."
        )

    def _build_batch_system_prompt(self) -> str:
        return (
            "You evaluate recent successful Basil tasks and propose reusable skills only when "
            "the task history supports a durable procedure. The input includes existing_skills "
            "with pending_candidates (not yet approved) and saved_skills (already approved); "
            "items judged most relevant include their full body, others are metadata only. "
            "Return strict JSON only: "
            '{"candidates":[{"title":"6-80 chars","when_to_use":"30-280 chars",'
            '"triggers":["2-8 concise semantic triggers"],'
            '"procedure_markdown":"200-1700 chars with at least three numbered steps",'
            '"expected_result":"what success should look like",'
            '"source_task_ids":["one or more task ids"],'
            '"enhances_candidate_id":null,"enhances_skill_slug":null}]}. '
            "For each proposal, choose to propose a brand-new skill, ENHANCE an existing pending "
            "candidate (set enhances_candidate_id), or ENHANCE an existing saved skill (set "
            "enhances_skill_slug) when the operation overlaps. When enhancing, set exactly one of "
            "those ids and return a single cohesive procedure_markdown that folds overlapping "
            "steps and adds only net-new aspects, with triggers and source_task_ids unioned. "
            "Do not emit two candidates that describe the same operation; merge them instead. "
            "Return {\"candidates\":[]} when nothing deserves review. "
            "Do not include markdown fences or prose outside JSON."
        )

    def _build_merge_confirmation_system_prompt(self) -> str:
        return (
            "You are given existing_candidate (an already pending skill candidate) and "
            "new_candidate (a freshly proposed one). Decide whether they describe the SAME "
            "reusable operation. Return strict JSON only: {\"candidate\":null} when they are "
            "genuinely distinct and should remain separate, OR a single merged "
            '{"candidate":{"title":"6-80 chars","when_to_use":"30-280 chars",'
            '"triggers":["2-8 concise semantic triggers"],'
            '"procedure_markdown":"200-1700 chars with at least three numbered steps",'
            '"expected_result":"what success should look like",'
            '"source_task_ids":["unioned task ids"]}} that folds the overlapping steps of both '
            "and adds the net-new aspects of new_candidate, unioning triggers and source_task_ids. "
            "Do not include markdown fences or prose outside JSON."
        )

    def _serialize_completed_task(self, task: CompletedTask) -> Dict[str, Any]:
        return {
            "id": task.id,
            "title": task.title,
            "original_prompt": task.original_prompt,
            "transcribed_prompt": task.transcribed_prompt,
            "result_summary": task.result_summary,
            "execution_timeline": task.execution_timeline,
            "intermediate_step_summaries": task.intermediate_step_summaries,
            "completed_at": task.completed_at,
        }

    def load_recent_completed_tasks_after_watermark(
        self,
        *,
        db_path: Optional[Path] = None,
        watermark: str,
        limit: int = 500,
    ) -> List[CompletedTask]:
        """Load completed tasks updated after a watermark, excluding negative feedback."""
        database_path = db_path or Path.home() / ".basil" / "knowledge_base.db"
        if not database_path.exists():
            return []

        connection = sqlite3.connect(str(database_path))
        connection.row_factory = sqlite3.Row
        try:
            if not self._table_exists(connection, "agent_tasks"):
                return []
            rows = connection.execute(
                """
                SELECT id, title, original_prompt, transcribed_prompt, result_preview,
                       execution_timeline, updated_at
                FROM agent_tasks
                WHERE updated_at > ?
                  AND status = 'completed'
                  AND (user_rating IS NULL OR user_rating >= 0)
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (watermark, limit),
            ).fetchall()
            return [self._completed_task_from_row(row) for row in rows]
        finally:
            connection.close()

    def _serialize_existing_context(self, context: ExistingSkillContext) -> Dict[str, Any]:
        return {
            "pending_candidates": [
                self._serialize_pending_candidate(candidate)
                for candidate in context.pending_candidates
            ],
            "saved_skills": [
                self._serialize_saved_skill(skill) for skill in context.saved_skills
            ],
        }

    def _serialize_pending_candidate(self, candidate: PendingCandidateView) -> Dict[str, Any]:
        return {
            "id": candidate.id,
            "title": candidate.title,
            "when_to_use": candidate.when_to_use,
            "triggers": list(candidate.triggers),
            "source_task_ids": list(candidate.source_task_ids),
            "procedure_markdown": candidate.procedure_markdown,
        }

    def _serialize_saved_skill(self, skill: SavedSkillView) -> Dict[str, Any]:
        return {
            "slug": skill.slug,
            "title": skill.title,
            "when_to_use": skill.when_to_use,
            "triggers": list(skill.triggers),
            "source_task_ids": list(skill.source_task_ids),
            "body": skill.body,
        }

    def _serialize_new_proposal(self, proposal: SkillProposal) -> Dict[str, Any]:
        return {
            "title": proposal.title,
            "when_to_use": proposal.when_to_use,
            "triggers": list(proposal.triggers),
            "procedure_markdown": proposal.procedure_markdown,
            "expected_result": proposal.expected_result,
            "source_task_ids": list(proposal.source_task_ids),
        }

    def _completed_task_from_row(self, row: sqlite3.Row) -> CompletedTask:
        return CompletedTask(
            id=str(row["id"]),
            title=row["title"],
            original_prompt=row["original_prompt"],
            transcribed_prompt=row["transcribed_prompt"],
            result_summary=row["result_preview"],
            execution_timeline=self._parse_json_list(row["execution_timeline"]),
            intermediate_step_summaries=[],
            completed_at=row["updated_at"],
        )

    def _parse_json_list(self, value: Any) -> List[Dict[str, Any]]:
        if not value:
            return []
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
        except Exception:
            return []
        return parsed if isinstance(parsed, list) else []

    def _table_exists(self, connection: sqlite3.Connection, table_name: str) -> bool:
        row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def _parse_single_response(self, response_text: str) -> Optional[SkillProposal]:
        try:
            payload = self._parse_json_object_response(response_text)
            return SingleSkillProposalResponse(**payload).candidate
        except (TypeError, json.JSONDecodeError, ValidationError) as exc:
            logger.info(
                "SkillEvaluator received invalid JSON/schema for optional single-task skill capture; "
                "treating as no candidate. %s",
                self._invalid_response_log_context(response_text, exc),
            )
            return None

    def _parse_batch_response(self, response_text: str) -> List[SkillProposal]:
        try:
            payload = self._parse_json_object_response(response_text)
            return SkillProposalBatchResponse(**payload).candidates
        except (TypeError, json.JSONDecodeError, ValidationError) as exc:
            logger.info(
                "SkillEvaluator received invalid JSON/schema for optional batch skill capture; "
                "treating as no candidates. %s",
                self._invalid_response_log_context(response_text, exc),
            )
            return []

    def _parse_json_object_response(self, response_text: Any) -> Dict[str, Any]:
        """Parse a model JSON object, tolerating common markdown wrapping."""
        response_string = "" if response_text is None else str(response_text)
        stripped = response_string.strip()
        if not stripped:
            raise json.JSONDecodeError("Empty response", response_string, 0)

        fenced_body = self._extract_fenced_json_body(stripped)
        if fenced_body is not None:
            return json.loads(fenced_body)

        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return self._parse_first_json_object(stripped)

    def _extract_fenced_json_body(self, response_text: str) -> Optional[str]:
        if not response_text.startswith("```"):
            return None

        first_newline = response_text.find("\n")
        if first_newline == -1:
            return None

        closing_fence = response_text.rfind("```")
        if closing_fence <= first_newline:
            return None

        return response_text[first_newline + 1:closing_fence].strip()

    def _parse_first_json_object(self, response_text: str) -> Dict[str, Any]:
        decoder = json.JSONDecoder()
        for index, char in enumerate(response_text):
            if char != "{":
                continue
            try:
                payload, _ = decoder.raw_decode(response_text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload

        raise json.JSONDecodeError("No JSON object found", response_text, 0)

    def _invalid_response_log_context(self, response_text: Any, exc: Exception) -> str:
        response_string = "" if response_text is None else str(response_text)
        preview = response_string.strip().replace("\n", "\\n")[:240]
        if not preview:
            preview = "<empty>"

        return (
            f"response_length={len(response_string)}; "
            f"response_preview={preview!r}; "
            f"error={type(exc).__name__}: {exc}"
        )
