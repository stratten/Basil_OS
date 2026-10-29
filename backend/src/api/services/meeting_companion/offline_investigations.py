"""Investigations for a finished meeting: the same investigator and policy as a live one, run against the saved transcript and the saved sources.

Results are appended to the meeting's ``companion.json`` and announced on the websocket exactly like live events, so an open Companion pane for the finished meeting updates without a reload. Runs are tracked per meeting for the life of the process, and the run count is restored from the saved timeline so the per-meeting limit holds across restarts and across live and finished use.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from . import offline
from .context_search import RootRejected, validate_root
from .context_service import ContextService
from .investigator.coordinator import InvestigationCoordinator, InvestigationHost
from .investigator.runner import CompanionInvestigator
from .models import CompanionItem, CompanionRoot, CompanionSettings, CompanionTurn, TimelineEvent
from .proposals import DEFAULT_POLICY, ProposalPolicy
from .store import resolve_anchor_meeting_dir
from .stored_transcript import load_stored_turns

logger = logging.getLogger(__name__)

Broadcast = Callable[[Dict[str, Any]], Awaitable[Any]]


@dataclass
class _Prepared:
    session_key: str
    settings: CompanionSettings
    events: List[TimelineEvent]
    root_specs: List[Dict[str, str]]
    chat_user_ids: Set[str]


@dataclass
class _StoredMeeting:
    meeting_id: str
    session_key: str
    coordinator: InvestigationCoordinator
    turns: List[CompanionTurn]
    context: ContextService


def _prepare(meeting_id: str) -> Optional[_Prepared]:
    with offline._STORED_FILE_LOCK:
        log = offline._open_stored_log(meeting_id)
        if log is None:
            return None
        derived = log.derived()
        return _Prepared(
            session_key=log.session_key,
            settings=log.settings(),
            events=log.events(),
            root_specs=[{"id": root.id, "path": root.path, "kind": root.kind, "display_name": root.display_name} for root in derived.roots],
            chat_user_ids={message.id for message in derived.chat if message.role == "user"},
        )


def _stored_items(meeting_id: str) -> List[CompanionItem]:
    with offline._STORED_FILE_LOCK:
        log = offline._open_stored_log(meeting_id)
        return list(log.derived().items) if log is not None else []


def _attach_saved_roots(context: ContextService, specs: List[Dict[str, str]]) -> int:
    """Re-attach the sources that were attached and never detached; a path that no longer exists is skipped. Returns how many attached."""
    attached = 0
    for spec in specs:
        try:
            resolved, kind = validate_root(spec["path"])
        except RootRejected as skipped:
            logger.info("Companion skipped saved source %s: %s", spec["path"], skipped)
            continue
        context.attach_root(spec["id"], resolved, kind, spec["display_name"])
        attached += 1
    return attached


class StoredInvestigations:
    def __init__(
        self,
        *,
        investigator: CompanionInvestigator,
        model_provider: Callable[[Optional[str]], Awaitable[Any]],
        broadcast: Broadcast,
        proposal_policy: Callable[[], ProposalPolicy] = lambda: DEFAULT_POLICY,
    ) -> None:
        self._investigator = investigator
        self._model_provider = model_provider
        self._broadcast = broadcast
        self._proposal_policy = proposal_policy
        self._meetings: Dict[str, _StoredMeeting] = {}
        self._tasks: Set["asyncio.Future[Any]"] = set()
        self._creation_lock = asyncio.Lock()

    def active_count(self, meeting_id: str) -> int:
        stored = self._meetings.get(meeting_id)
        return stored.coordinator.active_count if stored is not None else 0

    async def request(self, meeting_id: str, question: str, reply_to_message_id: Optional[str] = None) -> Optional[str]:
        """Start an investigation in a finished meeting. ``None`` when nothing was saved; raises ``InvestigationRejected``, ``ValueError`` or ``RuntimeError`` with a user-facing reason like the live path."""
        stored = await self._meeting(meeting_id)
        if stored is None:
            return None
        if reply_to_message_id is not None:
            prepared = await asyncio.to_thread(_prepare, meeting_id)
            if prepared is None or reply_to_message_id not in prepared.chat_user_ids:
                raise ValueError("That chat message is no longer available.")
        return stored.coordinator.request(question, origin="explicit", reply_to_message_id=reply_to_message_id)

    def cancel(self, meeting_id: str, investigation_id: str) -> bool:
        stored = self._meetings.get(meeting_id)
        return stored.coordinator.cancel(investigation_id) if stored is not None else False

    def sync_attached(self, meeting_id: str, root: CompanionRoot) -> None:
        """Make a source attached after this meeting's context was cached visible to the next investigation. A meeting that is not cached yet reads its sources from ``companion.json`` when first used."""
        stored = self._meetings.get(meeting_id)
        if stored is None:
            return
        try:
            resolved, kind = validate_root(root.path)
        except RootRejected as skipped:
            logger.info("Companion skipped saved source %s: %s", root.path, skipped)
            return
        stored.context.attach_root(root.id, resolved, kind, root.display_name)

    def sync_detached(self, meeting_id: str, root_id: str) -> None:
        """Drop a detached source from this meeting's cached context."""
        stored = self._meetings.get(meeting_id)
        if stored is not None:
            stored.context.detach_root(root_id)

    async def shutdown(self) -> None:
        for stored in self._meetings.values():
            stored.coordinator.cancel_all()
        tasks = [task for task in self._tasks if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._meetings.clear()

    async def wait_idle(self) -> None:
        while True:
            pending = [task for task in self._tasks if not task.done()]
            if not pending:
                return
            await asyncio.gather(*pending, return_exceptions=True)

    async def _meeting(self, meeting_id: str) -> Optional[_StoredMeeting]:
        async with self._creation_lock:
            existing = self._meetings.get(meeting_id)
            if existing is not None:
                return existing
            prepared = await asyncio.to_thread(_prepare, meeting_id)
            if prepared is None:
                return None
            turns = await asyncio.to_thread(load_stored_turns, meeting_id)
            context = ContextService()
            await asyncio.to_thread(_attach_saved_roots, context, prepared.root_specs)
            settings = prepared.settings.model_copy(update={"enabled": True, "investigate": True})
            latest = max((event.meeting_time for event in prepared.events), default=0.0)
            holder: Dict[str, InvestigationCoordinator] = {}
            host = InvestigationHost(
                settings=lambda: settings,
                context=context,
                capacity=lambda: "ok",
                closed=lambda: False,
                latest_meeting_time=lambda: max(latest, turns[-1].end if turns else 0.0),
                window_turns=lambda: list(turns),
                conversation_state=lambda: "",
                shown_texts=lambda: [item.text for item in _stored_items(meeting_id)][-6:],
                model_provider=self._model_provider,
                append=lambda kind, meeting_time, payload: self._append(meeting_id, prepared.session_key, kind, meeting_time, payload),
                spawn=self._spawn,
                record_error=lambda code, message: self._append(meeting_id, prepared.session_key, "error", latest, {"code": code, "message": message[:300]}),
                status_changed=lambda: self._announce_status(meeting_id, prepared.session_key, holder["coordinator"].active_count),
                proposal_policy=lambda: self._proposal_policy(),
                items=lambda: _stored_items(meeting_id),
            )
            coordinator = InvestigationCoordinator(self._investigator, host)
            coordinator.restore(prepared.events)
            holder["coordinator"] = coordinator
            stored = _StoredMeeting(meeting_id=meeting_id, session_key=prepared.session_key, coordinator=coordinator, turns=turns, context=context)
            self._meetings[meeting_id] = stored
            return stored

    def _spawn(self, coroutine: Awaitable[Any]) -> "asyncio.Future[Any]":
        task = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _append(self, meeting_id: str, session_key: str, kind: str, meeting_time: float, payload: Dict[str, Any]) -> Optional[TimelineEvent]:
        with offline._STORED_FILE_LOCK:
            log = offline._open_stored_log(meeting_id)
            if log is None:
                return None
            event = log.append(kind, meeting_time, payload)  # type: ignore[arg-type]
            log.flush()
        self._spawn(self._broadcast({"event_type": "meeting_companion_event", "event": event.model_dump(mode="json"), "session_key": session_key, "meeting_ids": [meeting_id]}))
        return event

    def _announce_status(self, meeting_id: str, session_key: str, investigating: int) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._spawn(self._broadcast({"event_type": "meeting_companion_status", "investigating": investigating, "session_key": session_key, "meeting_ids": [meeting_id]}))
