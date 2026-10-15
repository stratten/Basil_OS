"""Process-wide Meeting Companion runtime: observes recorders and owns the live sessions."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from api.services.meetings import meeting_recording_registry

from .capacity import LagCapacityGuard, recorder_lag_provider
from .chat import CompanionChatService
from .context_service import ContextService
from .evaluator import CompanionEvaluator
from .investigator.runner import CompanionInvestigator
from .models import (
    AutoProposalAction,
    CompanionGlobalSettings,
    CompanionMode,
    CompanionSettings,
    CompanionSnapshot,
    CompanionStatus,
    ProposalAction,
    ProposalMode,
    TurnRole,
)
from .proposal_launcher import TodoProposalLauncher
from .proposals import DEFAULT_POLICY, ProposalLauncher, ProposalPolicy, policy_from_settings
from .session import UNSET, CompanionSession
from .store import CompanionGlobalSettingsStore, resolve_anchor_meeting_dir

logger = logging.getLogger(__name__)

Broadcast = Callable[[Dict[str, Any]], Awaitable[Any]]


class CompanionNotLive(LookupError):
    """Raised when a Companion is requested for a meeting that is not currently recording."""


def session_key_for(meeting_id: str, recorder: Any) -> str:
    return str(getattr(recorder, "session_id", None) or meeting_id)


def role_for(recorder: Any) -> TurnRole:
    source = str(getattr(recorder, "audio_source", None) or "Microphone").strip().lower()
    return "self" if source == "microphone" else "other"


def speaker_for(recorder: Any) -> str:
    return str(getattr(recorder, "audio_source", None) or "Speaker 1")


def member_start_epoch(recorder: Any) -> float:
    """UTC epoch of the recorder's ``metadata.start_time`` (an ISO string with a trailing Z); now when unavailable."""
    metadata = getattr(recorder, "metadata", None)
    text = str(getattr(metadata, "start_time", "") or "").strip()
    try:
        parsed = datetime.fromisoformat(text.rstrip("Zz"))
    except ValueError:
        return time.time()
    return parsed.replace(tzinfo=timezone.utc).timestamp()


async def broadcast_to_clients(message: Dict[str, Any]) -> None:
    from api.services.websocket_connection_manager import broadcast_json_text

    await broadcast_json_text(message, log=logger)


class MeetingCompanionRuntime:
    def __init__(
        self,
        *,
        global_store: Optional[CompanionGlobalSettingsStore] = None,
        evaluator: Optional[CompanionEvaluator] = None,
        chat_service: Optional[CompanionChatService] = None,
        investigator: Optional[CompanionInvestigator] = None,
        proposal_launcher: Optional[ProposalLauncher] = None,
        broadcast: Optional[Broadcast] = None,
        directory_resolver: Callable[[str], Any] = resolve_anchor_meeting_dir,
        recorders: Optional[Callable[[], List[Any]]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._global_store = global_store or CompanionGlobalSettingsStore()
        self._evaluator = evaluator or CompanionEvaluator()
        self._chat_service = chat_service
        self._investigator = investigator or CompanionInvestigator()
        self._proposal_launcher: ProposalLauncher = proposal_launcher or TodoProposalLauncher()
        self._proposal_policy: ProposalPolicy = DEFAULT_POLICY
        self._broadcast: Broadcast = broadcast or broadcast_to_clients
        self._directory_resolver = directory_resolver
        self._recorders = recorders or meeting_recording_registry.active_recorders
        self._clock = clock
        self._sessions: Dict[str, CompanionSession] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lifecycle_lock = asyncio.Lock()
        self._background: Set["asyncio.Future[Any]"] = set()
        self._listening = False

    # ------------------------------------------------------------------ installation

    def install(self, loop: asyncio.AbstractEventLoop, *, register_listener: bool = True) -> None:
        self._loop = loop
        if register_listener and not self._listening:
            meeting_recording_registry.add_listener(self._on_registry_event)
            self._listening = True

    async def shutdown(self) -> None:
        if self._listening:
            meeting_recording_registry.remove_listener(self._on_registry_event)
            self._listening = False
        async with self._lifecycle_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            for session in sessions:
                try:
                    await session.close()
                except Exception as error:
                    logger.error("Companion session close failed during shutdown: %s", error, exc_info=True)
        await self.wait_idle()

    async def wait_idle(self) -> None:
        """Await posted lifecycle work (used by tests and shutdown)."""
        await asyncio.sleep(0)
        while True:
            pending = [task for task in self._background if not task.done()]
            if not pending:
                return
            await asyncio.gather(*pending, return_exceptions=True)

    # ------------------------------------------------------------------ registry listener (may run on the audio thread)

    def _on_registry_event(self, event: str, meeting_id: str, recorder: Any, payload: Optional[Dict[str, Any]]) -> None:
        if event == "segment":
            if not self._sessions:
                return
            key = session_key_for(meeting_id, recorder)
            if key not in self._sessions:
                return
            segment = (payload or {}).get("segment")
            if segment:
                self._post(self._deliver_segment, key, meeting_id, segment)
        elif event == "started":
            self._post(self._spawn_started, meeting_id, recorder)
        elif event in ("stopped", "discarded"):
            self._post(self._spawn_stopped, meeting_id, event == "discarded")

    def _post(self, callback: Callable[..., None], *args: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(callback, *args)
        except RuntimeError:
            logger.debug("Companion could not post %s: event loop is closed", getattr(callback, "__name__", "callback"))

    # ------------------------------------------------------------------ loop-thread handlers

    def _deliver_segment(self, key: str, meeting_id: str, segment: Dict[str, Any]) -> None:
        session = self._sessions.get(key)
        if session is None:
            return
        try:
            session.on_segment(meeting_id, segment)
        except Exception as error:
            logger.error("Companion could not ingest a segment for %s: %s", meeting_id, error, exc_info=True)

    def _spawn(self, coroutine: Awaitable[Any]) -> None:
        task = asyncio.ensure_future(coroutine)
        self._background.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: "asyncio.Future[Any]") -> None:
        self._background.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Companion lifecycle task failed: %s", task.exception(), exc_info=task.exception())

    def _spawn_started(self, meeting_id: str, recorder: Any) -> None:
        self._spawn(self._handle_started(meeting_id, recorder))

    def _spawn_stopped(self, meeting_id: str, discarded: bool) -> None:
        self._spawn(self._handle_stopped(meeting_id, discarded))

    async def _handle_started(self, meeting_id: str, recorder: Any) -> None:
        async with self._lifecycle_lock:
            if not self._is_live(recorder):
                return
            key = session_key_for(meeting_id, recorder)
            session = self._sessions.get(key)
            if session is not None:
                self._attach_recorder(session, recorder)
                return
            global_settings = await asyncio.to_thread(self._global_store.load)
            if not global_settings.auto_enable:
                return
            # The focus typed before the recording belongs to this meeting only, so it is consumed here.
            focus = global_settings.next_focus.strip() or None
            await self._create_session(key, mode=None, model_id=UNSET, focus=focus)
            if focus is not None:
                await asyncio.to_thread(lambda: self._global_store.save(self._global_store.load().model_copy(update={"next_focus": ""})))

    async def _handle_stopped(self, meeting_id: str, discarded: bool) -> None:
        async with self._lifecycle_lock:
            session = self._find_session(meeting_id)
            if session is None:
                return
            if session.remove_member(meeting_id) == 0:
                self._sessions.pop(session.session_key, None)
                await session.close(discard=discarded)

    # ------------------------------------------------------------------ helpers

    def _is_live(self, recorder: Any) -> bool:
        return any(candidate is recorder for candidate in self._recorders())

    def _live_members(self, key: str) -> List[Any]:
        return [
            recorder
            for recorder in self._recorders()
            if session_key_for(str(getattr(recorder, "meeting_id", "")), recorder) == key
        ]

    def _find_session(self, meeting_id: str) -> Optional[CompanionSession]:
        return next((session for session in self._sessions.values() if session.has_member(meeting_id)), None)

    def _attach_recorder(self, session: CompanionSession, recorder: Any) -> None:
        meeting_id = str(getattr(recorder, "meeting_id", ""))
        if not meeting_id or session.has_member(meeting_id):
            return
        session.add_member(
            meeting_id=meeting_id,
            role=role_for(recorder),
            speaker=speaker_for(recorder),
            recorder=recorder,
            start_epoch=member_start_epoch(recorder),
            existing_segments=list(getattr(recorder, "transcript_segments", []) or []),
        )

    async def _create_session(
        self,
        key: str,
        *,
        mode: Optional[CompanionMode],
        model_id: Any,
        focus: Optional[str] = None,
        investigate: Optional[bool] = None,
    ) -> CompanionSession:
        global_settings = await asyncio.to_thread(self._global_store.load)
        self._proposal_policy = policy_from_settings(global_settings)
        settings = CompanionSettings(
            enabled=True,
            mode=mode or global_settings.default_mode,
            model_id=None if model_id is UNSET else (model_id or None),
            focus=(focus or "").strip(),
            investigate=True if investigate is None else investigate,
        )
        session = CompanionSession(
            session_key=key,
            settings=settings,
            evaluator=self._evaluator,
            context=ContextService(),
            capacity_guard=LagCapacityGuard(recorder_lag_provider(self._recorders)),
            broadcast=self._broadcast,
            chat_service=self._chat_service,
            investigator=self._investigator,
            proposal_policy=lambda: self._proposal_policy,
            proposal_launcher=self._proposal_launcher,
            directory_resolver=self._directory_resolver,
            mode_explicit=mode is not None,
            model_explicit=model_id is not UNSET,
            focus_explicit=focus is not None,
            investigate_explicit=investigate is not None,
            clock=self._clock,
        )
        self._sessions[key] = session
        try:
            for recorder in self._live_members(key):
                self._attach_recorder(session, recorder)
            await session.start()
        except Exception:
            self._sessions.pop(key, None)
            await session.close(discard=True)
            raise
        return session

    # ------------------------------------------------------------------ public API used by routes

    def live_statuses(self) -> List[CompanionStatus]:
        """The status of every live Companion session, for the resource advisor."""
        return [session.status() for session in list(self._sessions.values())]

    def session_for(self, meeting_id: str) -> Optional[CompanionSession]:
        return next((session for session in self._sessions.values() if meeting_id in session.meeting_ids()), None)

    def snapshot(self, meeting_id: str) -> Optional[CompanionSnapshot]:
        session = self.session_for(meeting_id)
        return session.snapshot(meeting_id) if session is not None else None

    async def enable(
        self,
        meeting_id: str,
        *,
        mode: Optional[CompanionMode] = None,
        model_id: Any = UNSET,
        focus: Optional[str] = None,
        investigate: Optional[bool] = None,
    ) -> CompanionSession:
        async with self._lifecycle_lock:
            existing = self.session_for(meeting_id)
            if existing is not None:
                existing.update_settings(mode=mode, model_id=model_id, focus=focus, investigate=investigate)
                return existing
            recorder = next((candidate for candidate in self._recorders() if getattr(candidate, "meeting_id", None) == meeting_id), None)
            if recorder is None:
                raise CompanionNotLive(meeting_id)
            return await self._create_session(session_key_for(meeting_id, recorder), mode=mode, model_id=model_id, focus=focus, investigate=investigate)

    async def disable(self, meeting_id: str) -> bool:
        async with self._lifecycle_lock:
            session = self.session_for(meeting_id)
            if session is None:
                return False
            self._sessions.pop(session.session_key, None)
            await session.close(final_enabled=False)
            return True

    @property
    def proposal_launcher(self) -> ProposalLauncher:
        return self._proposal_launcher

    def get_global_settings(self) -> CompanionGlobalSettings:
        return self._global_store.load()

    def update_global_settings(
        self,
        *,
        auto_enable: Optional[bool] = None,
        default_mode: Optional[CompanionMode] = None,
        screen_share_note_dismissed: Optional[bool] = None,
        next_focus: Optional[str] = None,
        proposal_mode: Optional[ProposalMode] = None,
        proposal_capabilities: Optional[List[ProposalAction]] = None,
        auto_execute_capabilities: Optional[List[AutoProposalAction]] = None,
    ) -> CompanionGlobalSettings:
        changes: Dict[str, Any] = {}
        if auto_enable is not None:
            changes["auto_enable"] = auto_enable
        if default_mode is not None:
            changes["default_mode"] = default_mode
        if screen_share_note_dismissed is not None:
            changes["screen_share_note_dismissed"] = screen_share_note_dismissed
        if next_focus is not None:
            changes["next_focus"] = next_focus.strip()
        if proposal_mode is not None:
            changes["proposal_mode"] = proposal_mode
        if proposal_capabilities is not None:
            changes["proposal_capabilities"] = list(dict.fromkeys(proposal_capabilities))
        if auto_execute_capabilities is not None:
            changes["auto_execute_capabilities"] = list(dict.fromkeys(auto_execute_capabilities))
        updated = self._global_store.load().model_copy(update=changes)
        self._global_store.save(updated)
        self._proposal_policy = policy_from_settings(updated)
        return updated


_runtime: Optional[MeetingCompanionRuntime] = None


async def initialize_meeting_companion_runtime() -> MeetingCompanionRuntime:
    global _runtime
    if _runtime is None:
        _runtime = MeetingCompanionRuntime()
        _runtime.install(asyncio.get_running_loop())
    return _runtime


async def cleanup_meeting_companion_runtime() -> None:
    global _runtime
    runtime, _runtime = _runtime, None
    if runtime is not None:
        await runtime.shutdown()


def get_meeting_companion_runtime() -> Optional[MeetingCompanionRuntime]:
    return _runtime
