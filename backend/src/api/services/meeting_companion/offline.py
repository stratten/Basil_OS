"""Read and update a finished meeting's saved Companion timeline without a live session."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import store as store_module
from .event_log import CompanionEventLog
from .models import CompanionItem, CompanionSnapshot, CompanionStatus
from .proposals import ProposalDecision, ProposalLauncher, decide_proposal
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


_STORED_FILE_LOCK = threading.Lock()


def _open_stored_log(meeting_id: str) -> Optional[CompanionEventLog]:
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
    return log


def record_stored_feedback(meeting_id: str, item_id: str, action: str) -> Optional[bool]:
    """Append a feedback event to the saved timeline: ``None`` when nothing is saved, ``False`` when the item is unknown, else ``True``."""
    with _STORED_FILE_LOCK:
        log = _open_stored_log(meeting_id)
        if log is None:
            return None
        if not any(item.id == item_id for item in log.derived().items):
            return False
        latest = max((event.meeting_time for event in log.events()), default=0.0)
        log.append("feedback", latest, {"item_id": item_id, "action": action})
        log.flush()
        return True


def _load_stored_item(meeting_id: str, item_id: str) -> Optional[Tuple[str, Optional[CompanionItem]]]:
    with _STORED_FILE_LOCK:
        log = _open_stored_log(meeting_id)
        if log is None:
            return None
        return log.session_key, next((item for item in log.derived().items if item.id == item_id), None)


def _append_stored_proposal_events(meeting_id: str, payloads: List[Dict[str, Any]]) -> None:
    if not payloads:
        return
    with _STORED_FILE_LOCK:
        log = _open_stored_log(meeting_id)
        if log is None:
            return
        latest = max((event.meeting_time for event in log.events()), default=0.0)
        for payload in payloads:
            log.append("proposal", latest, payload)
        log.flush()


async def decide_stored_proposal(meeting_id: str, item_id: str, decision: str, launcher: Optional[ProposalLauncher]) -> Optional[ProposalDecision]:
    """Approve or dismiss a proposal in a finished meeting: ``None`` when nothing is saved; raises ``ProposalNotFound`` or ``ProposalRejected``. Shielded so a dropped connection cannot cancel it between a launch and the record of that launch."""

    async def decide() -> Optional[ProposalDecision]:
        loaded = await asyncio.to_thread(_load_stored_item, meeting_id, item_id)
        if loaded is None:
            return None
        session_key, item = loaded
        pending: List[Dict[str, Any]] = []
        outcome = await decide_proposal(session_key=session_key, item=item, decision=decision, launcher=launcher, append=pending.append)
        await asyncio.to_thread(_append_stored_proposal_events, meeting_id, pending)
        return outcome

    return await asyncio.shield(decide())
