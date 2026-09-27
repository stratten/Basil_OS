"""Persistence for the parallel setup assistant state."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


SETUP_ASSISTANT_STATE_FILE = Path.home() / ".config" / "basil" / "setup_assistant_state.json"


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
        "reminder_dismissed": False,
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
        return merged

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
            "completed_at": datetime.utcnow().isoformat(),
            "configured": configured,
            "skipped": skipped,
            "deferred": deferred,
            "session_goals": session_goals or [],
            "execution_outcomes": execution_outcomes or [],
            "blockers": blockers or [],
            "pending_setup_assistant": False,
            "last_skipped_at": None,
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
    ) -> Dict[str, Any]:
        """Record a Skip-for-now exit. Leaves completed=false and surfaces the resume reminder."""

        SETUP_ASSISTANT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        now_iso = datetime.utcnow().isoformat()
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
            # Clearing reminder_dismissed lets the toast surface again after a fresh skip,
            # even if the user previously asked us to stop reminding them.
            "reminder_dismissed": False,
        }
        SETUP_ASSISTANT_STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))
        return state

    def dismiss_setup_reminder(self) -> Dict[str, Any]:
        """Suppress the launch-time resume toast without clearing the pending flag."""

        SETUP_ASSISTANT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        current = self.load_setup_state()
        current["reminder_dismissed"] = True
        SETUP_ASSISTANT_STATE_FILE.write_text(json.dumps(current, indent=2, sort_keys=True))
        return current

    def _mark_first_run_onboarding_complete(self) -> None:
        """Mark the primary setup assistant as satisfying first-run onboarding."""
        from api.core.preferences.preferences_io import load_preferences, save_preferences

        preferences = load_preferences()
        if preferences.general.has_completed_onboarding:
            return
        preferences.general.has_completed_onboarding = True
        save_preferences(preferences)
