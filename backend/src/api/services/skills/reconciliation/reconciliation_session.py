"""In-memory session model for the Skill Reconciliation Workspace.

A reconciliation session is a transactional staging area. It captures an
immutable *snapshot* of the pending skill candidates and saved skills at the
moment the workspace window opens, accumulates model-produced ``ProposedAction``
rows, records the user's accept/reject/edit decisions, and finally reports what
was committed.

The session lives only for the lifetime of the open window. It is held in
process memory (no disk file) because it must never outlive its window: an
abnormal exit simply drops it, which is the correct behavior (nothing was
written to the live stores until an explicit commit). ``GET .../session`` reads
this in-memory state to hydrate the web app after the webview mounts.

Only one session may exist at a time. Launching the workspace while a session is
present focuses the existing window instead of creating a second session.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# Session lifecycle states.
STATUS_ANALYZING = "analyzing"
STATUS_READY = "ready"
STATUS_COMMITTING = "committing"
STATUS_COMMITTED = "committed"
STATUS_DISCARDED = "discarded"

# Proposed-action kinds (see module docstring of reconciliation_analysis).
KIND_MERGE_CANDIDATES = "merge_candidates"
KIND_ENHANCE_SAVED_SKILL = "enhance_saved_skill"
KIND_DUPLICATE_OF_SAVED_SKILL = "duplicate_of_saved_skill"
KIND_KEEP_NEW = "keep_new"
KIND_DELETE_SAVED_SKILL = "delete_saved_skill"

# Per-action decisions.
DECISION_PENDING = "pending"
DECISION_ACCEPTED = "accepted"
DECISION_REJECTED = "rejected"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SessionSnapshot:
    """Immutable picture of skill state captured when the session started.

    - ``pending_candidates`` are full ``SkillCandidateRecord`` dicts.
    - ``saved_skills`` each carry ``slug``/``title``/``when_to_use``/``triggers``/
      ``source_task_ids``/``body`` so analysis and the diff view have everything
      they need without re-reading the live store mid-session.
    """

    captured_at: str
    pending_candidates: List[Dict[str, Any]]
    saved_skills: List[Dict[str, Any]]
    min_observations: int = 2

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProposedAction:
    """One model-produced reconciliation proposal awaiting a user decision.

    The ``merged_*`` fields carry the model's cohesive result (for merges and
    enhancements). ``user_edited`` holds any fields the user overrode in the UI;
    ``effective_payload`` resolves the two so commit uses the final values.
    """

    id: str
    kind: str
    source_candidate_ids: List[str] = field(default_factory=list)
    target_skill_slug: Optional[str] = None
    rationale: str = ""
    merged_title: Optional[str] = None
    merged_when_to_use: Optional[str] = None
    merged_triggers: List[str] = field(default_factory=list)
    merged_procedure_markdown: Optional[str] = None
    merged_expected_result: Optional[str] = None
    merged_source_task_ids: List[str] = field(default_factory=list)
    decision: str = DECISION_PENDING
    user_edited: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def effective_payload(self) -> Dict[str, Any]:
        """Resolve user edits over the model's merged fields for commit."""
        base = {
            "title": self.merged_title,
            "when_to_use": self.merged_when_to_use,
            "triggers": list(self.merged_triggers),
            "procedure_markdown": self.merged_procedure_markdown,
            "expected_result": self.merged_expected_result,
            "source_task_ids": list(self.merged_source_task_ids),
        }
        if self.user_edited:
            for key, value in self.user_edited.items():
                if key in base and value is not None:
                    base[key] = value
        return base


@dataclass
class ReconciliationSession:
    """The full transactional staging session for a workspace window."""

    id: str
    status: str
    created_at: str
    updated_at: str
    snapshot: SessionSnapshot
    actions: List[ProposedAction] = field(default_factory=list)
    progress: Dict[str, Any] = field(
        default_factory=lambda: {"phase": "starting", "processed": 0, "total": 0}
    )
    errors: List[str] = field(default_factory=list)
    commit_report: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "snapshot": self.snapshot.to_dict(),
            "actions": [action.to_dict() for action in self.actions],
            "progress": dict(self.progress),
            "errors": list(self.errors),
            "commit_report": self.commit_report,
        }

    def find_action(self, action_id: str) -> Optional[ProposedAction]:
        for action in self.actions:
            if action.id == action_id:
                return action
        return None


class ReconciliationSessionStore:
    """Process-lived holder for the single active reconciliation session."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session: Optional[ReconciliationSession] = None

    def create(self, snapshot: SessionSnapshot) -> ReconciliationSession:
        """Create the session, rejecting a second concurrent one."""
        with self._lock:
            if self._session is not None:
                raise RuntimeError(
                    "A reconciliation session is already active; close its window first."
                )
            now = _now()
            self._session = ReconciliationSession(
                id=f"recon-{uuid.uuid4().hex}",
                status=STATUS_ANALYZING,
                created_at=now,
                updated_at=now,
                snapshot=snapshot,
                progress={
                    "phase": "analyzing",
                    "processed": 0,
                    "total": len(snapshot.pending_candidates),
                },
            )
            return self._session

    def load(self) -> Optional[ReconciliationSession]:
        with self._lock:
            return self._session

    def require(self) -> ReconciliationSession:
        session = self.load()
        if session is None:
            raise RuntimeError("No reconciliation session is active.")
        return session

    def append_action(self, action: ProposedAction) -> None:
        with self._lock:
            if self._session is None:
                raise RuntimeError("No reconciliation session is active.")
            self._session.actions.append(action)
            self._session.updated_at = _now()

    def set_action_decision(
        self,
        action_id: str,
        decision: str,
        *,
        user_edited: Optional[Dict[str, Any]] = None,
    ) -> ProposedAction:
        if decision not in {DECISION_PENDING, DECISION_ACCEPTED, DECISION_REJECTED}:
            raise ValueError(f"Unsupported action decision: {decision}")
        with self._lock:
            if self._session is None:
                raise RuntimeError("No reconciliation session is active.")
            action = self._session.find_action(action_id)
            if action is None:
                raise ValueError(f"Reconciliation action '{action_id}' was not found.")
            action.decision = decision
            if user_edited is not None:
                action.user_edited = user_edited
            self._session.updated_at = _now()
            return action

    def update_progress(
        self,
        *,
        phase: Optional[str] = None,
        processed: Optional[int] = None,
        total: Optional[int] = None,
    ) -> None:
        with self._lock:
            if self._session is None:
                return
            if phase is not None:
                self._session.progress["phase"] = phase
            if processed is not None:
                self._session.progress["processed"] = processed
            if total is not None:
                self._session.progress["total"] = total
            self._session.updated_at = _now()

    def set_status(self, status: str) -> None:
        with self._lock:
            if self._session is None:
                return
            self._session.status = status
            self._session.updated_at = _now()

    def set_commit_report(self, report: Dict[str, Any]) -> None:
        with self._lock:
            if self._session is None:
                return
            self._session.commit_report = report
            self._session.status = STATUS_COMMITTED
            self._session.updated_at = _now()

    def append_error(self, message: str) -> None:
        with self._lock:
            if self._session is None:
                return
            self._session.errors.append(message)
            self._session.updated_at = _now()

    def clear(self) -> None:
        with self._lock:
            self._session = None


_session_store_singleton: Optional[ReconciliationSessionStore] = None


def get_reconciliation_session_store() -> ReconciliationSessionStore:
    """Return the process-wide reconciliation session store."""
    global _session_store_singleton
    if _session_store_singleton is None:
        _session_store_singleton = ReconciliationSessionStore()
    return _session_store_singleton
