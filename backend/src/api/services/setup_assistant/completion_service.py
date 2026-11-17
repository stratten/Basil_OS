"""Persistence for the parallel setup assistant state."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from api.core.utc_time import utc_now_naive, utc_now_naive_iso


SETUP_ASSISTANT_STATE_FILE = Path.home() / ".config" / "basil" / "setup_assistant_state.json"

RESUME_ADVISORY_AFTER_DAYS = 3
"""A saved setup session older than this many whole days comes with an advisory that starting from the top may serve better. Nothing expires: the person can always pick up where they left off."""

RESUMABLE_STAGES = ("orientation", "conversation")
MAX_RESUME_SUMMARY_CHARS = 2000


def _default_state() -> Dict[str, Any]:
    return {
        "completed": False,
        "completed_at": None,
        "configured": [],
        "skipped": [],
        "deferred": [],
        "session_goals": [],
        "execution_outcomes": [],
        "blockers": [],
        "pending_setup_assistant": False,
        "last_skipped_at": None,
        "last_progress_at": None,
        "reminder_dismissed": False,
        "resume_stage": None,
        "resume_summary": None,
        "resume_model_access": None,
        "resume_interaction_style": [],
    }


class SetupAssistantCompletionService:
    """Persist setup assistant completion and first-run routing state."""

    def load_setup_state(self) -> Dict[str, Any]:
        defaults = _default_state()
        if not SETUP_ASSISTANT_STATE_FILE.exists():
            return defaults

        try:
            stored = json.loads(SETUP_ASSISTANT_STATE_FILE.read_text())
        except Exception:
            return defaults

        if not isinstance(stored, dict):
            return defaults

        merged = {**defaults, **stored}
        merged["resume_age_days"] = self._resume_age_days(merged)
        merged["resume_advisory_after_days"] = RESUME_ADVISORY_AFTER_DAYS
        return merged

    @staticmethod
    def _resume_age_days(state: Dict[str, Any]) -> Optional[int]:
        """Whole days since the session was saved, or None when nothing resumable is saved."""
        saved_at_text = state.get("last_progress_at") or state.get("last_skipped_at")
        if state.get("completed") or not state.get("resume_stage") or not saved_at_text:
            return None
        try:
            saved_at = datetime.fromisoformat(str(saved_at_text))
        except ValueError:
            return None
        if saved_at.tzinfo is not None:
            saved_at = saved_at.astimezone(timezone.utc).replace(tzinfo=None)
        return max(0, (utc_now_naive() - saved_at).days)

    @staticmethod
    def _resume_fields(
        resume_stage: Optional[str],
        resume_summary: Optional[str],
        resume_model_access: Optional[Dict[str, Any]],
        resume_interaction_style: Optional[List[str]],
    ) -> Dict[str, Any]:
        """The saved-session fields for a skip. A session is resumable only when it reached a stage the agent can continue from and has a resolved model."""
        resumable = (
            resume_stage in RESUMABLE_STAGES
            and isinstance(resume_model_access, dict)
            and bool(resume_model_access.get("resolved"))
        )
        if not resumable:
            return {"resume_stage": None, "resume_summary": None, "resume_model_access": None, "resume_interaction_style": []}
        summary = (resume_summary or "").strip()[:MAX_RESUME_SUMMARY_CHARS] or None
        style = [item for item in (resume_interaction_style or []) if isinstance(item, str)][:20]
        return {
            "resume_stage": resume_stage,
            "resume_summary": summary,
            "resume_model_access": dict(resume_model_access or {}),
            "resume_interaction_style": style,
        }

    def mark_setup_complete(
        self,
        configured: List[str],
        skipped: List[str],
        deferred: List[str],
        session_goals: List[Dict[str, Any]] | None = None,
        execution_outcomes: List[Dict[str, Any]] | None = None,
        blockers: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        SETUP_ASSISTANT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "completed": True,
            "completed_at": utc_now_naive_iso(),
            "configured": configured,
            "skipped": skipped,
            "deferred": deferred,
            "session_goals": session_goals or [],
            "execution_outcomes": execution_outcomes or [],
            "blockers": blockers or [],
            "pending_setup_assistant": False,
            "last_skipped_at": None,
            "last_progress_at": None,
            "reminder_dismissed": False,
        }
        SETUP_ASSISTANT_STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))
        self._mark_first_run_onboarding_complete()
        return state

    def mark_setup_skipped(
        self,
        configured: List[str],
        skipped: List[str],
        deferred: List[str],
        session_goals: List[Dict[str, Any]] | None = None,
        execution_outcomes: List[Dict[str, Any]] | None = None,
        blockers: List[Dict[str, Any]] | None = None,
        resume_stage: Optional[str] = None,
        resume_summary: Optional[str] = None,
        resume_model_access: Optional[Dict[str, Any]] = None,
        resume_interaction_style: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Record a Skip-for-now exit. Leaves completed=false and surfaces the resume reminder.

        When the session had reached the conversation, its stage, agenda (in ``session_goals``), model choice and a short summary are kept so the person can pick up where they left off.
        """

        SETUP_ASSISTANT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        now_iso = utc_now_naive_iso()
        state = {
            "completed": False,
            "completed_at": None,
            "configured": configured,
            "skipped": skipped,
            "deferred": deferred,
            "session_goals": session_goals or [],
            "execution_outcomes": execution_outcomes or [],
            "blockers": blockers or [],
            "pending_setup_assistant": True,
            "last_skipped_at": now_iso,
            "last_progress_at": now_iso,
            # Clearing reminder_dismissed lets the toast surface again after a fresh skip,
            # even if the user previously asked us to stop reminding them.
            "reminder_dismissed": False,
            **self._resume_fields(resume_stage, resume_summary, resume_model_access, resume_interaction_style),
        }
        SETUP_ASSISTANT_STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))
        return {**state, "resume_age_days": self._resume_age_days(state), "resume_advisory_after_days": RESUME_ADVISORY_AFTER_DAYS}

    def save_setup_progress(
        self,
        configured: List[str],
        skipped: List[str],
        deferred: List[str],
        session_goals: List[Dict[str, Any]] | None = None,
        execution_outcomes: List[Dict[str, Any]] | None = None,
        blockers: List[Dict[str, Any]] | None = None,
        resume_stage: Optional[str] = None,
        resume_summary: Optional[str] = None,
        resume_model_access: Optional[Dict[str, Any]] = None,
        resume_interaction_style: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Keep where the person is in setup as they go, so closing the window any way at all leaves something to pick up.

        Unlike a skip it does not touch ``last_skipped_at`` or ``reminder_dismissed``, and it does nothing once setup is complete or when the session has not reached a resumable stage with a chosen model (an earlier good save is never wiped by an early-stage call).
        """

        current = self.load_setup_state()
        current.pop("resume_age_days", None)
        current.pop("resume_advisory_after_days", None)
        if current.get("completed"):
            return self.load_setup_state()
        resume = self._resume_fields(resume_stage, resume_summary, resume_model_access, resume_interaction_style)
        if not resume["resume_stage"]:
            return self.load_setup_state()

        state = {
            **current,
            "completed": False,
            "configured": configured,
            "skipped": skipped,
            "deferred": deferred,
            "session_goals": session_goals or [],
            "execution_outcomes": execution_outcomes or [],
            "blockers": blockers or [],
            "pending_setup_assistant": True,
            "last_progress_at": utc_now_naive_iso(),
            **resume,
        }
        self._write_state_atomically(state)
        return self.load_setup_state()

    def discard_saved_session(self) -> Dict[str, Any]:
        """Forget the saved session when the person chooses to start from the top.

        Clears the saved stage, summary, model choice, working style, agenda and what the old session had done, so the next launch does not offer a session the person turned down. It keeps ``pending_setup_assistant`` (setup is still not finished), ``last_skipped_at`` and ``reminder_dismissed``, and it does nothing once setup is complete.
        """

        current = self.load_setup_state()
        current.pop("resume_age_days", None)
        current.pop("resume_advisory_after_days", None)
        if current.get("completed") or not current.get("resume_stage"):
            return self.load_setup_state()

        defaults = _default_state()
        cleared = {
            key: defaults[key]
            for key in (
                "configured",
                "skipped",
                "deferred",
                "session_goals",
                "execution_outcomes",
                "blockers",
                "last_progress_at",
                "resume_stage",
                "resume_summary",
                "resume_model_access",
                "resume_interaction_style",
            )
        }
        self._write_state_atomically({**current, **cleared})
        return self.load_setup_state()

    @staticmethod
    def _write_state_atomically(state: Dict[str, Any]) -> None:
        """Progress is saved often and read at launch, so a reader must never see a half-written file."""
        SETUP_ASSISTANT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = SETUP_ASSISTANT_STATE_FILE.with_name(SETUP_ASSISTANT_STATE_FILE.name + ".tmp")
        temporary.write_text(json.dumps(state, indent=2, sort_keys=True))
        os.replace(temporary, SETUP_ASSISTANT_STATE_FILE)

    def dismiss_setup_reminder(self) -> Dict[str, Any]:
        """Suppress the launch-time resume toast without clearing the pending flag."""

        SETUP_ASSISTANT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        current = self.load_setup_state()
        # The age and threshold are worked out on every read, so they are never written to the file.
        current.pop("resume_age_days", None)
        current.pop("resume_advisory_after_days", None)
        current["reminder_dismissed"] = True
        SETUP_ASSISTANT_STATE_FILE.write_text(json.dumps(current, indent=2, sort_keys=True))
        return self.load_setup_state()

    def _mark_first_run_onboarding_complete(self) -> None:
        """Mark the primary setup assistant as satisfying first-run onboarding."""
        from api.core.preferences.preferences_io import load_preferences, save_preferences

        preferences = load_preferences()
        if preferences.general.has_completed_onboarding:
            return
        preferences.general.has_completed_onboarding = True
        save_preferences(preferences)
