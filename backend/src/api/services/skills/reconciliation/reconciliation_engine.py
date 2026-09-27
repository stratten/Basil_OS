"""Coordinator for a reconciliation session's analysis pass.

``start_session`` snapshots the live skill state, activates the freeze gate,
creates the in-memory session, and spawns a background analysis task. The task
streams progress and each produced :class:`ProposedAction` to the web app over
the shared ``/ws`` broadcast bus using ``skill_reconciliation_*`` event types,
persisting everything into the session store so a late-mounting webview can
hydrate via ``GET .../session``.

The engine never mutates the live ``proposal_store`` / ``skill_store`` - that is
strictly the job of :mod:`reconciliation_commit` on explicit user commit.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from api.services import websocket_connection_manager
from api.services.memory.proposal_store import (
    ProposalStore,
    SkillCandidateRecord,
    get_proposal_store,
)
from api.services.skills.reconciliation import reconciliation_gate
from api.services.skills.reconciliation.reconciliation_analysis import run_analysis
from api.services.skills.reconciliation.reconciliation_evaluator import (
    ReconciliationEvaluator,
)
from api.services.skills.reconciliation.reconciliation_session import (
    STATUS_READY,
    ProposedAction,
    ReconciliationSession,
    ReconciliationSessionStore,
    SessionSnapshot,
    get_reconciliation_session_store,
)
from api.services.skills.skill_evaluator import SkillEvaluator
from api.services.skills.skill_service import SkillService, get_skill_service


logger = logging.getLogger(__name__)

EVENT_STATUS = "skill_reconciliation_status"
EVENT_PROGRESS = "skill_reconciliation_progress"
EVENT_ACTION_READY = "skill_reconciliation_action_ready"

EvaluatorFactory = Callable[[], ReconciliationEvaluator]


class ReconciliationEngine:
    """Owns session start + the streaming analysis task."""

    def __init__(
        self,
        *,
        session_store: Optional[ReconciliationSessionStore] = None,
        proposal_store: Optional[ProposalStore] = None,
        skill_service: Optional[SkillService] = None,
        evaluator_factory: Optional[EvaluatorFactory] = None,
    ) -> None:
        self._session_store = session_store or get_reconciliation_session_store()
        self._proposal_store = proposal_store or get_proposal_store()
        self._skill_service = skill_service or get_skill_service()
        self._evaluator_factory = evaluator_factory or self._default_evaluator_factory

    async def start_session(self) -> ReconciliationSession:
        """Snapshot state, freeze capture, and kick off streaming analysis."""
        if reconciliation_gate.is_active():
            raise RuntimeError("A reconciliation session is already active.")

        snapshot = self._build_snapshot()
        session = self._session_store.create(snapshot)
        reconciliation_gate.activate(session.id)
        await self._broadcast_status(session)
        asyncio.create_task(
            self._run_analysis(session.id),
            name=f"skill-reconciliation-{session.id}",
        )
        return session

    async def _run_analysis(self, session_id: str) -> None:
        session = self._session_store.load()
        if session is None or session.id != session_id:
            return
        try:
            all_records = [
                SkillCandidateRecord(**record)
                for record in session.snapshot.pending_candidates
            ]
            # Single sightings (below the configured threshold) are excluded from
            # reconciliation review; they remain in the snapshot for the web app's
            # read-only "single sightings" tab.
            min_observations = session.snapshot.min_observations
            records = [
                record
                for record in all_records
                if record.observation_count >= min_observations
            ]
            saved_skills = list(session.snapshot.saved_skills)
            evaluator = self._evaluator_factory()

            def on_progress(processed: int, total: int) -> None:
                self._session_store.update_progress(
                    phase="analyzing", processed=processed, total=total
                )

            async for action in run_analysis(
                pending=records,
                saved_skills=saved_skills,
                evaluator=evaluator,
                on_progress=on_progress,
            ):
                self._session_store.append_action(action)
                await self._broadcast_action(session_id, action)
                await self._broadcast_progress(session_id)

            self._session_store.update_progress(phase="ready")
            self._session_store.set_status(STATUS_READY)
        except Exception as exc:
            logger.exception("Reconciliation analysis failed for session %s", session_id)
            self._session_store.append_error(f"Analysis failed: {exc}")
            self._session_store.update_progress(phase="ready")
            self._session_store.set_status(STATUS_READY)

        final = self._session_store.load()
        if final is not None and final.id == session_id:
            await self._broadcast_status(final)

    def _build_snapshot(self) -> SessionSnapshot:
        pending_records = self._proposal_store.list_pending_skill_candidates()
        pending_dicts = [asdict(record) for record in pending_records]

        saved_dicts: List[Dict[str, Any]] = []
        for record in self._skill_service.store.list_skills():
            metadata = record.metadata or {}
            saved_dicts.append(
                {
                    "slug": record.slug,
                    "title": str(metadata.get("title") or record.slug),
                    "when_to_use": str(metadata.get("when_to_use") or ""),
                    "triggers": [
                        str(trigger)
                        for trigger in metadata.get("triggers", [])
                        if isinstance(trigger, str)
                    ],
                    "source_task_ids": [
                        str(task_id)
                        for task_id in metadata.get("source_task_ids", [])
                        if task_id
                    ],
                    "observation_count": int(
                        metadata.get("observation_count")
                        or len([t for t in metadata.get("source_task_ids", []) if t])
                        or 1
                    ),
                    "version": int(metadata.get("version") or 1),
                    "body": record.body,
                }
            )

        return SessionSnapshot(
            captured_at=datetime.now(timezone.utc).isoformat(),
            pending_candidates=pending_dicts,
            saved_skills=saved_dicts,
            min_observations=self._resolve_min_observations(),
        )

    def _default_evaluator_factory(self) -> ReconciliationEvaluator:
        return ReconciliationEvaluator(SkillEvaluator(model_id=self._resolve_model_id()))

    def _resolve_model_id(self) -> str:
        from api.core.preferences.preferences_io import load_preferences

        preferences = load_preferences()
        settings = getattr(preferences, "memory_intelligence", None)
        return (
            getattr(settings, "skill_processing_model", None)
            or preferences.models.reasoning_model
        )

    def _resolve_min_observations(self) -> int:
        from api.core.preferences.preferences_io import load_preferences

        preferences = load_preferences()
        settings = getattr(preferences, "memory_intelligence", None)
        value = getattr(settings, "skill_reconciliation_min_instances", None)
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 2

    async def _broadcast_status(self, session: ReconciliationSession) -> None:
        await self._broadcast(
            {
                "event_type": EVENT_STATUS,
                "session_id": session.id,
                "status": session.status,
                "progress": dict(session.progress),
                "error_count": len(session.errors),
            }
        )

    async def _broadcast_progress(self, session_id: str) -> None:
        session = self._session_store.load()
        if session is None or session.id != session_id:
            return
        await self._broadcast(
            {
                "event_type": EVENT_PROGRESS,
                "session_id": session_id,
                "progress": dict(session.progress),
            }
        )

    async def _broadcast_action(self, session_id: str, action: ProposedAction) -> None:
        await self._broadcast(
            {
                "event_type": EVENT_ACTION_READY,
                "session_id": session_id,
                "action": action.to_dict(),
            }
        )

    async def _broadcast(self, payload: Dict[str, Any]) -> None:
        try:
            await websocket_connection_manager.broadcast_json_text(payload, log=logger)
        except Exception:
            logger.exception("Failed to broadcast reconciliation event %s", payload.get("event_type"))


_engine_singleton: Optional[ReconciliationEngine] = None


def get_reconciliation_engine() -> ReconciliationEngine:
    """Return the process-wide reconciliation engine."""
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = ReconciliationEngine()
    return _engine_singleton
