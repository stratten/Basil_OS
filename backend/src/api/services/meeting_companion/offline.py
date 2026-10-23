"""Read and update a finished meeting's saved Companion timeline without a live session."""

from __future__ import annotations

import asyncio
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import store as store_module
from .context_search import MAX_ROOTS, RootRejected, validate_root
from .event_log import CompanionEventLog
from .models import AuditReport, CompanionItem, CompanionRoot, CompanionSettings, CompanionSnapshot, CompanionStatus
from .item_actions import ItemActionResult, actionable_item, run_item_action
from .proposals import ProposalDecision, ProposalLauncher, ProposalPolicy, ProposalRejected, decide_proposal
from .store import CompanionStore, read_json_object, resolve_anchor_meeting_dir
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


def _stored_session_key(meeting_id: str) -> str:
    """The key a live session would have used: the recording session id when the meeting belongs to one, else the meeting id."""
    metadata = read_json_object(store_module.meetings_root() / meeting_id / "metadata.json")
    session_id = metadata.get("session_id") if metadata else None
    return str(session_id or meeting_id)


def _open_or_create_stored_log(meeting_id: str) -> CompanionEventLog:
    """The saved log, or a new empty one anchored where ``companion.json`` belongs. Nothing is written until the first event is flushed."""
    existing = _open_stored_log(meeting_id)
    if existing is not None:
        return existing
    directory: Path = resolve_anchor_meeting_dir(meeting_id)
    return CompanionEventLog(
        session_key=_stored_session_key(meeting_id),
        resolve_directory=lambda: directory,
        settings_provider=lambda: CompanionSettings(),
    )


def _latest_meeting_time(log: CompanionEventLog) -> float:
    return max((event.meeting_time for event in log.events()), default=0.0)


def attach_stored_root(meeting_id: str, path_text: str) -> Optional[CompanionRoot]:
    """Attach a folder or file to a finished meeting: ``None`` when the meeting does not exist; raises ``RootRejected`` with a user-facing reason. Creates ``companion.json`` (Companion off) when the meeting never had one, and returns the existing source when the same path is already attached."""
    if not meeting_exists(meeting_id):
        return None
    resolved, kind = validate_root(path_text)
    with _STORED_FILE_LOCK:
        log = _open_or_create_stored_log(meeting_id)
        roots = log.derived().roots
        existing = next((root for root in roots if root.path == str(resolved)), None)
        if existing is not None:
            return existing
        if len(roots) >= MAX_ROOTS:
            raise RootRejected(f"At most {MAX_ROOTS} sources can be attached to one meeting.")
        root_id = f"r-{uuid.uuid4().hex[:8]}"
        display_name = resolved.name or str(resolved)
        log.append(
            "source",
            _latest_meeting_time(log),
            {"root_id": root_id, "state": "attached", "path": str(resolved), "display_name": display_name, "kind": kind},
        )
        if not log.flush():
            raise RootRejected("Could not save the source. Try again.")
        return next(root for root in log.derived().roots if root.id == root_id)


def detach_stored_root(meeting_id: str, root_id: str) -> Optional[bool]:
    """Detach a source from a finished meeting: ``None`` when nothing is saved, ``False`` when that source is not attached, else ``True``."""
    with _STORED_FILE_LOCK:
        log = _open_stored_log(meeting_id)
        if log is None:
            return None
        root = next((candidate for candidate in log.derived().roots if candidate.id == root_id), None)
        if root is None:
            return False
        log.append(
            "source",
            _latest_meeting_time(log),
            {"root_id": root.id, "state": "detached", "path": root.path, "display_name": root.display_name, "kind": root.kind},
        )
        log.flush()
        return True


def stored_root_paths(meeting_id: str) -> List[str]:
    """Paths of the sources currently attached to a finished meeting; empty when nothing is saved."""
    with _STORED_FILE_LOCK:
        log = _open_stored_log(meeting_id)
        return [root.path for root in log.derived().roots] if log is not None else []


def record_stored_feedback(meeting_id: str, item_id: str, action: str) -> Optional[bool]:
    """Append a feedback event to the saved timeline: ``None`` when nothing is saved, ``False`` when the item is unknown, else ``True``."""
    with _STORED_FILE_LOCK:
        log = _open_stored_log(meeting_id)
        if log is None:
            return None
        derived = log.derived()
        if action.startswith("audit_"):
            if derived.audit is None or not any(moment.id == item_id for moment in derived.audit.moments):
                return False
        elif not any(item.id == item_id for item in derived.items):
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


def _load_stored_items(meeting_id: str) -> Optional[Tuple[str, List[CompanionItem], Optional[AuditReport]]]:
    with _STORED_FILE_LOCK:
        log = _open_stored_log(meeting_id)
        if log is None:
            return None
        derived = log.derived()
        return log.session_key, list(derived.items), derived.audit


def _append_stored_action(meeting_id: str, card: CompanionItem, payloads: List[Dict[str, Any]]) -> None:
    with _STORED_FILE_LOCK:
        log = _open_stored_log(meeting_id)
        if log is None:
            return
        latest = max((event.meeting_time for event in log.events()), default=0.0)
        log.append("item", latest, {"item": card.model_dump(mode="json")})
        for payload in payloads:
            log.append("proposal", latest, payload)
        log.flush()


_ACTING: set = set()


async def act_on_stored_item(
    meeting_id: str,
    item_id: str,
    action: str,
    launcher: Optional[ProposalLauncher],
    policy: ProposalPolicy,
) -> Optional[ItemActionResult]:
    """The Make to-do and Hand to agent buttons on a note in a finished meeting: ``None`` when nothing is saved; raises ``ProposalNotFound`` or ``ProposalRejected``. Shielded for the same reason as ``decide_stored_proposal``, and a second click on the same note while the first is running is refused."""

    async def act() -> Optional[ItemActionResult]:
        key = f"{meeting_id}:{item_id}"
        if key in _ACTING:
            raise ProposalRejected("That note is already being turned into an action.")
        _ACTING.add(key)
        try:
            loaded = await asyncio.to_thread(_load_stored_items, meeting_id)
            if loaded is None:
                return None
            session_key, items, audit = loaded
            reference_paths = await asyncio.to_thread(stored_root_paths, meeting_id)
            cards: List[CompanionItem] = []
            pending: List[Dict[str, Any]] = []
            outcome = await run_item_action(
                session_key=session_key,
                item=actionable_item(items, audit, item_id),
                action=action,
                existing=items,
                policy=policy,
                launcher=launcher,
                append_item=cards.append,
                append_proposal=pending.append,
                reference_paths=reference_paths,
            )
            await asyncio.to_thread(_append_stored_action, meeting_id, cards[0], pending)
            return outcome
        finally:
            _ACTING.discard(key)

    return await asyncio.shield(act())


async def decide_stored_proposal(meeting_id: str, item_id: str, decision: str, launcher: Optional[ProposalLauncher]) -> Optional[ProposalDecision]:
    """Approve or dismiss a proposal in a finished meeting: ``None`` when nothing is saved; raises ``ProposalNotFound`` or ``ProposalRejected``. Shielded so a dropped connection cannot cancel it between a launch and the record of that launch."""

    async def decide() -> Optional[ProposalDecision]:
        loaded = await asyncio.to_thread(_load_stored_item, meeting_id, item_id)
        if loaded is None:
            return None
        session_key, item = loaded
        pending: List[Dict[str, Any]] = []
        reference_paths = await asyncio.to_thread(stored_root_paths, meeting_id)
        outcome = await decide_proposal(session_key=session_key, item=item, decision=decision, launcher=launcher, append=pending.append, reference_paths=reference_paths)
        await asyncio.to_thread(_append_stored_proposal_events, meeting_id, pending)
        return outcome

    return await asyncio.shield(decide())
