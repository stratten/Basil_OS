"""Durable record of when each scheduled background pass last completed.

The schedulers keep their timers in memory, so a backend that was not running at the scheduled time used to forget the missed run and wait for the next day's slot.
This ledger survives restarts, so the next start can see that a scheduled slot passed without a completed run and run it then.
Times are naive local ISO strings, matching how the schedulers express their configured HH:MM slots.
A missing or unreadable ledger reads as "never completed", which makes the next start run once and rewrite it.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

LEDGER_FILE_NAME = "scheduler_ledger.json"
_write_lock = threading.Lock()


def ledger_path() -> Path:
    from api.settings import get_settings

    return Path(get_settings().data_dir).expanduser() / LEDGER_FILE_NAME


def _read_all() -> Dict[str, str]:
    try:
        decoded = json.loads(ledger_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {str(key): str(value) for key, value in decoded.items() if isinstance(value, str)}


def read_last_completed(name: str) -> Optional[datetime]:
    """When the named pass last completed, or None when it never has or the record is unreadable."""
    raw = _read_all().get(name)
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def record_completed(name: str, when: Optional[datetime] = None) -> None:
    """Record that the named pass completed. Never raises: a ledger that cannot be written only means a later redundant catch-up run."""
    moment = when or datetime.now()
    path = ledger_path()
    try:
        with _write_lock:
            entries = _read_all()
            entries[name] = moment.isoformat()
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            temporary.write_text(json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(temporary, path)
    except OSError as exc:
        logger.warning("Could not record the %s completion in %s: %s", name, path, exc)
