"""Read and update a finished meeting's saved Companion timeline without a live session."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import store as store_module
from .event_log import CompanionEventLog
from .models import CompanionSnapshot, CompanionStatus
from .store import CompanionStore, resolve_anchor_meeting_dir
from .timeline import build_snapshot, reduce_timeline, stored_status


def meeting_exists(meeting_id: str) -> bool:
    return (store_module.meetings_root() / meeting_id).is_dir()


def empty_snapshot(meeting_id: str) -> CompanionSnapshot:
    return CompanionSnapshot(meeting_id=meeting_id, session_key=meeting_id, status=CompanionStatus())


def load_stored_snapshot(meeting_id: str) -> Optional[CompanionSnapshot]:
    """The saved snapshot for ``meeting_id`` (resolved to the session's anchor directory), or ``None`` when nothing was saved."""
    directory = resolve_anchor_meeting_dir(meeting_id)
    document = CompanionStore(directory).load()
    if document is None:
        return None
    derived = reduce_timeline(sorted(document.events, key=lambda event: event.seq))
    return build_snapshot(
        meeting_id=meeting_id,
        session_key=document.session_key,
        status=stored_status(derived, document.settings),
        derived=derived,
    )


def record_stored_feedback(meeting_id: str, item_id: str, action: str) -> Optional[bool]:
    """Append a feedback event to the saved timeline: ``None`` when nothing is saved, ``False`` when the item is unknown, else ``True``."""
    directory: Path = resolve_anchor_meeting_dir(meeting_id)
    document = CompanionStore(directory).load()
    if document is None:
        return None
    log = CompanionEventLog(
        session_key=document.session_key,
        resolve_directory=lambda: directory,
        settings_provider=lambda: document.settings,
    )
    log.load_existing([directory])
    if not any(item.id == item_id for item in log.derived().items):
        return False
    latest = max((event.meeting_time for event in log.events()), default=0.0)
    log.append("feedback", latest, {"item_id": item_id, "action": action})
    log.flush()
    return True
