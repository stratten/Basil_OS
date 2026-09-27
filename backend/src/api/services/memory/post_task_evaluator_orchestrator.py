"""Coordinate optional model-driven post-task memory and skill evaluation."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from api.core.config.api_settings import settings
from api.services.memory.memory_evaluator import ActivitySignal, MemoryEvaluator, MemoryProposal
from api.services.memory.proposal_store import get_proposal_store
from api.services.skills.skill_context_builder import build_context_for_completed_tasks
from api.services.skills.skill_evaluator import (
    CompletedTask,
    ExistingSkillContext,
    SkillEvaluator,
    SkillProposal,
)
from api.services.skills.skill_proposal_applier import apply_skill_proposals


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PostTaskEvaluatorResult:
    """Summary returned to hooks, routes, and future Settings run-now UI."""

    memory_proposals_added: int = 0
    skill_candidates_added: int = 0
    errors: List[str] = field(default_factory=list)


class PostTaskEvaluatorOrchestrator:
    """Run enabled model-driven evaluators without involving the task agent."""

    async def run_for_completed_task(
        self,
        *,
        task: CompletedTask,
        memory_signals: Optional[List[ActivitySignal]] = None,
        existing_context: Optional[ExistingSkillContext] = None,
    ) -> PostTaskEvaluatorResult:
        """Run enabled in-loop evaluators for one completed task."""
        settings = self._load_memory_intelligence_settings()
        model_id = self._select_fallback_model_id()
        tasks = []

        if self._is_enabled(settings, "memory_after_task_enabled"):
            tasks.append(self._evaluate_memory_signals(memory_signals or [self._signal_from_task(task)], settings, model_id))
        if self._is_enabled(settings, "skill_after_task_enabled"):
            context = existing_context or build_context_for_completed_tasks(task)
            tasks.append(self._evaluate_completed_task_skill(task, context, settings, model_id))

        return await self._collect_results(tasks)

    async def run_daily_sweep(self) -> PostTaskEvaluatorResult:
        """Run enabled daily evaluators.

        Zettel signals track their own progress: each consumed entry is stamped
        with memory_swept_at once its proposals are stored, so this method holds
        no cursor for them. The remaining agent_tasks watermark belongs to the
        older skill sweep and advances only if its own evaluator actually ran.
        """
        settings = self._load_memory_intelligence_settings()
        if not (
            self._is_enabled(settings, "memory_daily_enabled")
            or self._is_enabled(settings, "skill_daily_enabled")
        ):
            return PostTaskEvaluatorResult()

        watermarks = self._read_watermarks()
        advanced = dict(watermarks)
        fallback_model_id = self._select_fallback_model_id()
        tasks = []

        if self._is_enabled(settings, "memory_daily_enabled"):
            from api.services.zettel.memory_bridge import load_unswept_signals

            signals, entry_ids = load_unswept_signals()
            if signals:
                tasks.append(
                    self._evaluate_memory_signals(
                        signals, settings, fallback_model_id, entry_ids=entry_ids
                    )
                )

        if self._is_enabled(settings, "skill_daily_enabled"):
            skill_evaluator = SkillEvaluator(
                model_id=getattr(settings, "skill_processing_model", None) or fallback_model_id
            )
            completed_tasks = skill_evaluator.load_recent_completed_tasks_after_watermark(
                watermark=watermarks["agent_tasks"],
            )
            if completed_tasks:
                context = build_context_for_completed_tasks(*completed_tasks)
                tasks.append(
                    self._evaluate_recent_task_skills(skill_evaluator, completed_tasks, context)
                )
                advanced["agent_tasks"] = datetime.now(timezone.utc).isoformat()

        result = await self._collect_results(tasks)
        self._write_watermarks(advanced)
        return result

    async def _evaluate_memory_signals(
        self,
        signals: List[ActivitySignal],
        settings,
        fallback_model_id: str,
        entry_ids: Optional[List[str]] = None,
    ) -> PostTaskEvaluatorResult:
        model_id = getattr(settings, "memory_processing_model", None) or fallback_model_id
        try:
            proposals = await MemoryEvaluator(model_id=model_id).evaluate_signals(signals)
            added_count = await self._store_memory_proposals(proposals)
            if entry_ids:
                # Stamped only here: the entries are consumed once their
                # proposals are stored, so any failure above leaves them
                # unstamped for the next sweep to retry.
                from api.services.zettel.memory_bridge import mark_swept

                await asyncio.to_thread(mark_swept, entry_ids)
            return PostTaskEvaluatorResult(memory_proposals_added=added_count)
        except Exception as exc:
            logger.exception("Memory post-task evaluation failed")
            return PostTaskEvaluatorResult(errors=[str(exc)])

    async def _evaluate_completed_task_skill(
        self,
        task: CompletedTask,
        existing_context: ExistingSkillContext,
        settings,
        fallback_model_id: str,
    ) -> PostTaskEvaluatorResult:
        model_id = getattr(settings, "skill_processing_model", None) or fallback_model_id
        try:
            evaluator = SkillEvaluator(model_id=model_id)
            proposal = await evaluator.evaluate_completed_task(
                task,
                existing_context=existing_context,
            )
            added_count = await self._store_skill_proposals(
                evaluator, [proposal] if proposal else []
            )
            return PostTaskEvaluatorResult(skill_candidates_added=added_count)
        except Exception as exc:
            logger.exception("Skill post-task evaluation failed")
            return PostTaskEvaluatorResult(errors=[str(exc)])

    async def _evaluate_recent_task_skills(
        self,
        evaluator: SkillEvaluator,
        tasks: List[CompletedTask],
        existing_context: ExistingSkillContext,
    ) -> PostTaskEvaluatorResult:
        try:
            proposals = await evaluator.evaluate_recent_tasks(tasks, existing_context)
            added_count = await self._store_skill_proposals(evaluator, proposals)
            return PostTaskEvaluatorResult(skill_candidates_added=added_count)
        except Exception as exc:
            logger.exception("Daily skill evaluation failed")
            return PostTaskEvaluatorResult(errors=[str(exc)])

    async def _collect_results(self, tasks) -> PostTaskEvaluatorResult:
        if not tasks:
            return PostTaskEvaluatorResult()

        results = await asyncio.gather(*tasks, return_exceptions=True)
        memory_proposals_added = 0
        skill_candidates_added = 0
        errors: List[str] = []

        for result in results:
            if isinstance(result, Exception):
                errors.append(str(result))
                continue
            memory_proposals_added += result.memory_proposals_added
            skill_candidates_added += result.skill_candidates_added
            errors.extend(result.errors)

        return PostTaskEvaluatorResult(
            memory_proposals_added=memory_proposals_added,
            skill_candidates_added=skill_candidates_added,
            errors=errors,
        )

    async def _store_memory_proposals(self, proposals: List[MemoryProposal]) -> int:
        records = get_proposal_store().enqueue_memory_proposals(
            proposals,
            source="memory_evaluator",
        )
        return len(records)

    async def _store_skill_proposals(
        self,
        evaluator: SkillEvaluator,
        proposals: List[SkillProposal],
    ) -> int:
        return await apply_skill_proposals(
            proposals,
            evaluator=evaluator,
            source="skill_evaluator",
        )

    def _signal_from_task(self, task: CompletedTask) -> ActivitySignal:
        prompt = task.transcribed_prompt or task.original_prompt or task.title or "Completed Basil task"
        return ActivitySignal(
            source="agent_task",
            occurred_at=task.completed_at,
            summary=prompt,
            metadata={
                "task_id": task.id,
                "result_summary": task.result_summary,
            },
        )

    def _load_memory_intelligence_settings(self):
        try:
            from api.core.preferences.preferences_io import load_preferences

            return getattr(load_preferences(), "memory_intelligence", None)
        except Exception:
            logger.exception("Failed to load memory intelligence settings")
            return None

    def _select_fallback_model_id(self) -> str:
        try:
            from api.core.preferences.preferences_io import load_preferences

            return load_preferences().models.reasoning_model
        except Exception:
            logger.exception("Failed to read fallback reasoning model")
            raise

    def _is_enabled(self, settings, field_name: str) -> bool:
        return bool(getattr(settings, field_name, False))

    @property
    def watermark_path(self):
        return settings.STORAGE_DIR / "memory" / "intelligence_watermarks.json"

    def _read_watermarks(self) -> dict:
        if not self.watermark_path.exists():
            return self._default_watermarks()
        try:
            payload = json.loads(self.watermark_path.read_text(encoding="utf-8"))
            defaults = self._default_watermarks()
            return {
                "agent_tasks": str(payload.get("agent_tasks") or defaults["agent_tasks"]),
            }
        except Exception:
            logger.exception("Failed to read intelligence watermarks")
            return self._default_watermarks()

    def _write_watermarks(self, watermarks: dict) -> None:
        self.watermark_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.watermark_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(watermarks, indent=2, sort_keys=True), encoding="utf-8")
        temporary_path.replace(self.watermark_path)

    def _default_watermarks(self) -> dict:
        # Only the older skill sweep still uses a cursor. Zettel signals track
        # consumption per row via memory_swept_at.
        return {
            "agent_tasks": "1970-01-01T00:00:00+00:00",
        }


_post_task_evaluator_orchestrator_singleton: Optional[PostTaskEvaluatorOrchestrator] = None


def get_post_task_evaluator_orchestrator() -> PostTaskEvaluatorOrchestrator:
    global _post_task_evaluator_orchestrator_singleton
    if _post_task_evaluator_orchestrator_singleton is None:
        _post_task_evaluator_orchestrator_singleton = PostTaskEvaluatorOrchestrator()
    return _post_task_evaluator_orchestrator_singleton
