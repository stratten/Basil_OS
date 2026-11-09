"""A durable record of every setting an agent changed, so each change can be reviewed and undone."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

JOURNAL_FILE_NAME = "app_control_changes.json"
JOURNAL_VERSION = 1
MAX_JOURNAL_ENTRIES = 200


class ChangeJournal:
    """A JSON file of recent agent changes, newest last. A damaged file reads as empty rather than blocking changes."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _read(self) -> List[Dict[str, Any]]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            logger.warning("App control journal at %s is unreadable and will be treated as empty: %s", self._path, exc)
            return []
        changes = payload.get("changes") if isinstance(payload, dict) else None
        return [change for change in changes if isinstance(change, dict)] if isinstance(changes, list) else []

    def _write(self, changes: List[Dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": JOURNAL_VERSION, "changes": changes}, indent=2), encoding="utf-8")
        os.replace(temporary, self._path)

    def record(
        self,
        *,
        agent_task_id: Optional[str],
        reason: str,
        changes: List[Dict[str, Any]],
        approved_by_user: bool,
    ) -> Dict[str, Any]:
        """Append one change set and return it. Each item in `changes` has key, label, before_raw, after_raw, before, after."""
        entry: Dict[str, Any] = {
            "id": f"chg-{uuid.uuid4().hex[:8]}",
            "at": datetime.now(timezone.utc).isoformat(),
            "at_epoch": time.time(),
            "agent_task_id": agent_task_id,
            "reason": reason,
            "approved_by_user": approved_by_user,
            "undone": False,
            "changes": changes,
        }
        with self._lock:
            existing = self._read()
            existing.append(entry)
            self._write(existing[-MAX_JOURNAL_ENTRIES:])
        return entry

    def get(self, change_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return next((change for change in self._read() if change.get("id") == change_id), None)

    def latest_undoable(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            for change in reversed(self._read()):
                if not change.get("undone"):
                    return change
        return None

    def recent(self, limit: int) -> List[Dict[str, Any]]:
        with self._lock:
            return self._read()[-limit:]

    def mark_undone(self, change_id: str) -> bool:
        with self._lock:
            changes = self._read()
            for change in changes:
                if change.get("id") == change_id:
                    change["undone"] = True
                    change["undone_at"] = datetime.now(timezone.utc).isoformat()
                    self._write(changes)
                    return True
        return False

    def count_since(self, seconds: float, now: Optional[float] = None) -> int:
        """How many individual setting changes were recorded in the last `seconds`."""
        cutoff = (time.time() if now is None else now) - seconds
        with self._lock:
            return sum(
                len(change.get("changes") or [])
                for change in self._read()
                if float(change.get("at_epoch") or 0.0) >= cutoff
            )


def default_journal_path() -> Path:
    from api.core.preferences import preferences_io

    return preferences_io.SETTINGS_DIR / JOURNAL_FILE_NAME


_DEFAULT_JOURNAL: Optional[ChangeJournal] = None


def get_default_journal() -> ChangeJournal:
    """The journal beside the preferences file, created once per process."""
    global _DEFAULT_JOURNAL
    if _DEFAULT_JOURNAL is None:
        _DEFAULT_JOURNAL = ChangeJournal(default_journal_path())
    return _DEFAULT_JOURNAL
