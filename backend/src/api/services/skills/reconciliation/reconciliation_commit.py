"""Apply accepted reconciliation actions to the live skill stores.

Commit is intentionally defensive. It re-reads the live ``proposal_store`` and
``skill_store`` (never trusting the session snapshot) and validates that each
accepted action's referents still exist and are still pending before mutating
anything. A referent that drifted (e.g. the candidate was already approved, or
the saved skill was deleted) is *skipped with a note* rather than crashing the
whole commit. Any saved skill that will be overwritten or deleted is backed up
to a per-session pre-image directory first, so a manual recovery is always
possible.

The freeze gate is NOT released here. Releasing tracks the workspace window's
presence and happens on ``discard`` (fired when the window closes), so committing
without closing keeps the lock until the user closes the window.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from api.core.config.api_settings import settings
from api.services.memory.proposal_store import ProposalStore, get_proposal_store
from api.services.skills.reconciliation.reconciliation_session import (
    DECISION_ACCEPTED,
    KIND_DELETE_SAVED_SKILL,
    KIND_DUPLICATE_OF_SAVED_SKILL,
    KIND_ENHANCE_SAVED_SKILL,
    KIND_KEEP_NEW,
    KIND_MERGE_CANDIDATES,
    STATUS_COMMITTED,
    STATUS_COMMITTING,
    ProposedAction,
    ReconciliationSessionStore,
    get_reconciliation_session_store,
)
from api.services.skills.skill_service import SkillService, get_skill_service
from api.services.skills.skill_store import SkillNotFoundError


logger = logging.getLogger(__name__)


class _CommitSkip(Exception):
    """Internal signal that an action was skipped for a known reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ReconciliationCommitter:
    """Applies the accepted terminal decisions of a reconciliation session."""

    def __init__(
        self,
        *,
        session_store: Optional[ReconciliationSessionStore] = None,
        proposal_store: Optional[ProposalStore] = None,
        skill_service: Optional[SkillService] = None,
        backup_root: Optional[Path] = None,
    ) -> None:
        self._session_store = session_store or get_reconciliation_session_store()
        self._proposal_store = proposal_store or get_proposal_store()
        self._skill_service = skill_service or get_skill_service()
        self._backup_root = backup_root or (
            settings.STORAGE_DIR / "memory" / "reconciliation_backups"
        )

    def commit(self) -> Dict[str, Any]:
        """Apply accepted actions, returning a commit report. Idempotent per session."""
        session = self._session_store.require()
        if session.status == STATUS_COMMITTED:
            raise RuntimeError("This reconciliation session has already been committed.")

        self._session_store.set_status(STATUS_COMMITTING)
        applied: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []

        for action in session.actions:
            if action.decision != DECISION_ACCEPTED:
                continue
            try:
                detail = self._apply_action(action, session.id)
                applied.append(
                    {"action_id": action.id, "kind": action.kind, **detail}
                )
            except _CommitSkip as skip:
                skipped.append(
                    {"action_id": action.id, "kind": action.kind, "reason": skip.reason}
                )
            except Exception as exc:  # never let one action abort the commit
                logger.exception("Reconciliation action %s failed during commit", action.id)
                skipped.append(
                    {
                        "action_id": action.id,
                        "kind": action.kind,
                        "reason": f"Unexpected error: {exc}",
                    }
                )

        report = {
            "session_id": session.id,
            "committed_at": datetime.now(timezone.utc).isoformat(),
            "applied": applied,
            "skipped": skipped,
            "accepted_total": len(applied) + len(skipped),
        }
        self._session_store.set_commit_report(report)
        return report

    def _apply_action(self, action: ProposedAction, session_id: str) -> Dict[str, Any]:
        if action.kind == KIND_MERGE_CANDIDATES:
            return self._apply_merge(action)
        if action.kind == KIND_ENHANCE_SAVED_SKILL:
            return self._apply_enhance(action, session_id)
        if action.kind == KIND_DUPLICATE_OF_SAVED_SKILL:
            return self._apply_duplicate(action)
        if action.kind == KIND_KEEP_NEW:
            return self._apply_keep_new(action)
        if action.kind == KIND_DELETE_SAVED_SKILL:
            return self._apply_delete(action, session_id)
        raise _CommitSkip(f"Unknown action kind '{action.kind}'.")

    def _apply_merge(self, action: ProposedAction) -> Dict[str, Any]:
        if not action.source_candidate_ids:
            raise _CommitSkip("Merge action has no source candidates.")
        survivor_id = action.source_candidate_ids[0]
        other_ids = action.source_candidate_ids[1:]
        self._require_pending_candidate(survivor_id)

        payload = action.effective_payload()
        self._proposal_store.replace_skill_candidate_content(
            survivor_id,
            title=payload["title"],
            when_to_use=payload["when_to_use"],
            triggers=list(payload["triggers"]),
            procedure_markdown=payload["procedure_markdown"],
            expected_result=payload["expected_result"],
            source_task_ids=list(payload["source_task_ids"]),
        )
        declined: List[str] = []
        for candidate_id in other_ids:
            try:
                self._require_pending_candidate(candidate_id)
                self._proposal_store.mark_skill_candidate_status(candidate_id, "declined")
                declined.append(candidate_id)
            except _CommitSkip:
                # A sibling already left the pending queue; the merge survivor is
                # still updated, so continue rather than aborting.
                continue
        return {"survivor": survivor_id, "declined": declined}

    def _apply_enhance(self, action: ProposedAction, session_id: str) -> Dict[str, Any]:
        slug = (action.target_skill_slug or "").strip()
        if not slug:
            raise _CommitSkip("Enhance action has no target skill slug.")
        if not action.source_candidate_ids:
            raise _CommitSkip("Enhance action has no source candidate.")
        candidate_id = action.source_candidate_ids[0]
        self._require_saved_skill(slug)
        self._require_pending_candidate(candidate_id)

        backup_path = self._backup_skill(session_id, slug)
        payload = action.effective_payload()
        self._skill_service.save_skill(
            title=payload["title"],
            body=payload["procedure_markdown"],
            when_to_use=payload["when_to_use"],
            triggers=list(payload["triggers"]),
            source_task_ids=list(payload["source_task_ids"]),
            slug=slug,
        )
        self._proposal_store.mark_skill_candidate_status(candidate_id, "approved")
        return {"slug": slug, "candidate": candidate_id, "backup_path": backup_path}

    def _apply_duplicate(self, action: ProposedAction) -> Dict[str, Any]:
        if not action.source_candidate_ids:
            raise _CommitSkip("Duplicate action has no source candidate.")
        candidate_id = action.source_candidate_ids[0]
        self._require_pending_candidate(candidate_id)
        self._proposal_store.mark_skill_candidate_status(candidate_id, "declined")
        return {"declined": candidate_id, "covered_by": action.target_skill_slug}

    def _apply_keep_new(self, action: ProposedAction) -> Dict[str, Any]:
        if not action.source_candidate_ids:
            raise _CommitSkip("Keep-new action has no source candidate.")
        candidate_id = action.source_candidate_ids[0]
        self._require_pending_candidate(candidate_id)

        payload = action.effective_payload()
        saved = self._skill_service.save_skill(
            title=payload["title"],
            body=payload["procedure_markdown"],
            when_to_use=payload["when_to_use"],
            triggers=list(payload["triggers"]),
            source_task_ids=list(payload["source_task_ids"]),
        )
        self._proposal_store.mark_skill_candidate_status(candidate_id, "approved")
        return {"slug": saved.slug, "candidate": candidate_id}

    def _apply_delete(self, action: ProposedAction, session_id: str) -> Dict[str, Any]:
        slug = (action.target_skill_slug or "").strip()
        if not slug:
            raise _CommitSkip("Delete action has no target skill slug.")
        self._require_saved_skill(slug)
        backup_path = self._backup_skill(session_id, slug)
        deleted = self._skill_service.delete_skill(slug)
        return {"slug": slug, "deleted": deleted, "backup_path": backup_path}

    def _require_pending_candidate(self, candidate_id: str) -> None:
        try:
            candidate = self._proposal_store.get_skill_candidate(candidate_id)
        except ValueError as exc:
            raise _CommitSkip(
                f"Candidate '{candidate_id}' no longer exists; skipped."
            ) from exc
        if candidate.status != "pending":
            raise _CommitSkip(
                f"Candidate '{candidate_id}' is no longer pending "
                f"(now '{candidate.status}'); skipped."
            )

    def _require_saved_skill(self, slug: str) -> None:
        try:
            self._skill_service.store.read_skill(slug)
        except SkillNotFoundError as exc:
            raise _CommitSkip(
                f"Saved skill '{slug}' no longer exists; skipped."
            ) from exc

    def _backup_skill(self, session_id: str, slug: str) -> str:
        record = self._skill_service.store.read_skill(slug)
        skill_dir = record.path.parent
        backup_dir = self._backup_root / session_id / slug
        backup_dir.mkdir(parents=True, exist_ok=True)
        for entry in skill_dir.iterdir():
            if entry.is_file():
                shutil.copy2(entry, backup_dir / entry.name)
        return str(backup_dir)


def commit_active_session() -> Dict[str, Any]:
    """Commit the currently active reconciliation session."""
    return ReconciliationCommitter().commit()
