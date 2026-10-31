"""Audits for a finished meeting, and the automatic audit that runs when a meeting ends.

The report is appended to the meeting's ``companion.json`` and announced on the websocket like a live event, so an open Companion pane updates without a reload. Only one audit runs per meeting at a time. A failure is saved as an error event so the pane can say so; nothing is saved as "running", so a crash can never leave an audit looking stuck.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

from . import offline
from .audit import AuditFailed, AuditInputs, AuditRejected, CompanionAuditor, findings_as_items
from .models import CompanionTurn, TimelineEvent
from .stored_transcript import load_stored_turns

logger = logging.getLogger(__name__)

Broadcast = Callable[[Dict[str, Any]], Awaitable[Any]]
MAX_AUDIT_TURNS = 6000
MAX_ERROR_MESSAGE_CHARS = 300


def _load_inputs(meeting_id: str, turns: Optional[List[CompanionTurn]]) -> Optional[Tuple[str, AuditInputs]]:
    with offline._STORED_FILE_LOCK:
        log = offline._open_stored_log(meeting_id)
        if log is None:
            return None
        derived = log.derived()
        session_key, model_id = log.session_key, log.settings().model_id
        items, evaluations, total = list(derived.items), list(derived.evaluations), derived.evaluation_total
    audited = turns if turns is not None else load_stored_turns(meeting_id, limit=MAX_AUDIT_TURNS)
    return session_key, AuditInputs(turns=list(audited), items=items, evaluations=evaluations, evaluation_total=total, scope="meeting", model_id=model_id)


class StoredAudits:
    def __init__(self, *, auditor: CompanionAuditor, broadcast: Broadcast) -> None:
        self._auditor = auditor
        self._broadcast = broadcast
        self._running: Set[str] = set()
        self._tasks: Set["asyncio.Future[Any]"] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def is_running(self, meeting_id: str) -> bool:
        return meeting_id in self._running

    async def request(self, meeting_id: str, *, turns: Optional[List[CompanionTurn]] = None) -> Optional[bool]:
        """Start an audit of a finished meeting in the background. ``None`` when nothing was saved; raises ``AuditRejected`` with a user-facing reason. ``turns`` replaces the saved transcript, for the audit that runs at the end of a meeting before the transcript file is final."""
        if meeting_id in self._running:
            raise AuditRejected("An audit is already running.")
        self._loop = asyncio.get_running_loop()
        self._running.add(meeting_id)
        try:
            loaded = await asyncio.to_thread(_load_inputs, meeting_id, turns)
            if loaded is None:
                self._running.discard(meeting_id)
                return None
            session_key, inputs = loaded
            if not inputs.turns:
                raise AuditRejected("There is no saved transcript to audit.")
        except BaseException:
            self._running.discard(meeting_id)
            raise
        self._spawn(self._run(meeting_id, session_key, inputs))
        self._announce_status(meeting_id, session_key, True)
        return True

    async def shutdown(self) -> None:
        tasks = [task for task in self._tasks if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def wait_idle(self) -> None:
        while True:
            pending = [task for task in self._tasks if not task.done()]
            if not pending:
                return
            await asyncio.gather(*pending, return_exceptions=True)

    async def _run(self, meeting_id: str, session_key: str, inputs: AuditInputs) -> None:
        meeting_time = max((turn.end for turn in inputs.turns), default=0.0)
        try:
            report = await self._auditor.audit(inputs)
            await asyncio.to_thread(self._append, meeting_id, session_key, "audit", meeting_time, report.model_dump(mode="json"))
            # Findings also join the normal feed, at the point in the meeting where each miss happened.
            for finding in findings_as_items(report, inputs.turns, inputs.items):
                await asyncio.to_thread(self._append, meeting_id, session_key, "item", finding.transcript_range.end, {"item": finding.model_dump(mode="json")})
        except asyncio.CancelledError:
            raise
        except (AuditFailed, AuditRejected) as failure:
            await asyncio.to_thread(self._append, meeting_id, session_key, "error", meeting_time, {"code": "audit_failed", "message": f"The audit failed: {failure}"[:MAX_ERROR_MESSAGE_CHARS]})
        except Exception as error:
            logger.error("Companion audit failed for %s: %s", meeting_id, error, exc_info=True)
            await asyncio.to_thread(self._append, meeting_id, session_key, "error", meeting_time, {"code": "audit_failed", "message": f"The audit failed: {error}"[:MAX_ERROR_MESSAGE_CHARS]})
        finally:
            self._running.discard(meeting_id)
            self._announce_status(meeting_id, session_key, False)

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
        frame = {"event_type": "meeting_companion_event", "event": event.model_dump(mode="json"), "session_key": session_key, "meeting_ids": [meeting_id]}
        self._post(frame)
        return event

    def _announce_status(self, meeting_id: str, session_key: str, auditing: bool) -> None:
        self._post({"event_type": "meeting_companion_status", "auditing": auditing, "session_key": session_key, "meeting_ids": [meeting_id]})

    def _post(self, frame: Dict[str, Any]) -> None:
        """Broadcast from the event loop or from a worker thread that appended to the file."""
        if self._loop is None or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._spawn_broadcast, frame)

    def _spawn_broadcast(self, frame: Dict[str, Any]) -> None:
        self._spawn(self._broadcast(frame))
