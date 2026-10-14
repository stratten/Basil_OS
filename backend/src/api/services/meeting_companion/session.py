"""One live Companion session: observes finalized transcript lines and records timeline events."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union, get_args

from .capacity import CapacityGuard, allowed_triggers, prefetch_allowed
from .chat import ChatRequest, CompanionChatService
from .context_search import RootRejected, validate_root
from .context_service import ContextLookup, ContextService
from .conversation_state import ConversationState
from .evaluator import CompanionEvaluator, EvaluationOutcome, EvaluationRequest
from .event_log import CompanionEventLog
from .gate import Gate, GateConfig, GateDecision
from .models import (
    CapacityState,
    CompanionMode,
    CompanionRoot,
    CompanionSettings,
    CompanionSnapshot,
    CompanionStatus,
    CompanionTurn,
    CompanionWatch,
    FeedbackAction,
    TimelineEvent,
    TurnRole,
)
from .store import resolve_anchor_meeting_dir
from .timeline import DerivedState, build_snapshot, reduce_timeline
from .utterances import SessionClock, UtteranceAssembler
from .watches import (
    WatchRejected,
    build_watch_created_payload,
    parse_watch_request,
    watch_event_payload,
)

logger = logging.getLogger(__name__)

TICK_SECONDS = 1.0
PREFETCH_INTERVAL_SECONDS = 6.0
PREFETCH_LOG_INTERVAL_SECONDS = 30.0
STATUS_BROADCAST_INTERVAL_SECONDS = 2.0
ERROR_LOG_INTERVAL_SECONDS = 30.0
MAX_RESULT_AGE_SECONDS = 75.0
ANCHOR_CACHE_SECONDS = 60.0
MAX_CHAT_CHARS = 4000
CHAT_CLOSE_GRACE_SECONDS = 30.0
MAX_ROOTS = 5
SEED_WINDOW_SECONDS = 90.0
MAX_ERROR_MESSAGE_CHARS = 300


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


@dataclass
class _Member:
    meeting_id: str
    role: TurnRole
    assembler: UtteranceAssembler
    recorder: Any
    seeded_until: float = -1.0


class CompanionSession:
    def __init__(
        self,
        *,
        session_key: str,
        settings: CompanionSettings,
        evaluator: CompanionEvaluator,
        context: ContextService,
        capacity_guard: CapacityGuard,
        broadcast: Callable[[Dict[str, Any]], Awaitable[Any]],
        event_log: Optional[CompanionEventLog] = None,
        chat_service: Optional[CompanionChatService] = None,
        gate_config: Optional[GateConfig] = None,
        directory_resolver: Callable[[str], Path] = resolve_anchor_meeting_dir,
        mode_explicit: bool = True,
        model_explicit: bool = True,
        focus_explicit: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session_key = session_key
        self.settings = settings
        self._mode_explicit = mode_explicit
        self._model_explicit = model_explicit
        self._focus_explicit = focus_explicit
        self._evaluator = evaluator
        self._context = context
        self._capacity_guard = capacity_guard
        self._broadcast_fn = broadcast
        self._directory_resolver = directory_resolver
        self._clock = clock
        self._gate = Gate(gate_config)
        self._conversation = ConversationState()
        self._session_clock = SessionClock()
        self._members: Dict[str, _Member] = {}
        self._known_ids: Set[str] = set()
        self._nonce = uuid.uuid4().hex[:4]
        self._primary_meeting_id: Optional[str] = None
        self._event_log = event_log or CompanionEventLog(
            session_key=session_key,
            resolve_directory=self._resolve_directory,
            settings_provider=lambda: self.settings,
        )
        self._chat = chat_service or CompanionChatService(model_provider=evaluator.model_for)
        self._latest_meeting_time = 0.0
        self._capacity: CapacityState = "ok"
        self._capacity_reason: Optional[str] = None
        self._lag_seconds = 0.0
        self._evaluating = False
        self._derived: Optional[DerivedState] = None
        self._closed = False
        self._tasks: Set["asyncio.Future[Any]"] = set()
        self._chat_tasks: Set["asyncio.Future[Any]"] = set()
        self._loop_task: Optional["asyncio.Future[Any]"] = None
        self._evaluation_task: Optional["asyncio.Future[Any]"] = None
        self._prefetch_task: Optional["asyncio.Future[Any]"] = None
        self._chat_lock = asyncio.Lock()
        self._last_prefetch_at = float("-inf")
        self._last_prefetch_log_at = float("-inf")
        self._last_status_broadcast_at = float("-inf")
        self._last_error_at: Dict[str, float] = {}
        self._anchor_cache: Optional[Tuple[float, Path]] = None
        self._event_log.subscribe(self._on_event)

    # ------------------------------------------------------------------ identity and status

    def meeting_ids(self) -> List[str]:
        return sorted(self._known_ids)

    def has_member(self, meeting_id: str) -> bool:
        return meeting_id in self._members

    def member_count(self) -> int:
        return len(self._members)

    def pending_line_count(self) -> int:
        return self._gate.pending_count()

    def events(self) -> List[TimelineEvent]:
        return self._event_log.events()

    def conversation_state_text(self) -> str:
        return self._conversation.text

    def status(self) -> CompanionStatus:
        return CompanionStatus(
            live=not self._closed,
            enabled=self.settings.enabled,
            mode=self.settings.mode,
            model_id=self.settings.model_id,
            focus=self.settings.focus,
            capacity=self._capacity,
            capacity_reason=self._capacity_reason,
            latest_meeting_time=round(self._latest_meeting_time, 3),
            transcription_lag_seconds=round(self._lag_seconds, 1),
            evaluating=self._evaluating,
        )

    def _status_payload(self) -> Dict[str, Any]:
        return {
            "enabled": self.settings.enabled,
            "mode": self.settings.mode,
            "model_id": self.settings.model_id,
            "focus": self.settings.focus,
            "capacity": self._capacity,
            "reason": self._capacity_reason,
        }

    def snapshot(self, meeting_id: str) -> CompanionSnapshot:
        return build_snapshot(
            meeting_id=meeting_id,
            session_key=self.session_key,
            status=self.status(),
            derived=self._get_derived(),
        )

    def _get_derived(self) -> DerivedState:
        if self._derived is None:
            self._derived = reduce_timeline(self._event_log.events())
        return self._derived

    def _resolve_directory(self) -> Path:
        now = self._clock()
        cached = self._anchor_cache
        if cached is not None and now - cached[0] < ANCHOR_CACHE_SECONDS:
            return cached[1]
        directory = self._directory_resolver(self._primary_meeting_id or self.session_key)
        self._anchor_cache = (now, directory)
        return directory

    def _candidate_directories(self) -> List[Path]:
        candidates: List[Path] = [self._resolve_directory()]
        for member in self._members.values():
            meeting_dir = getattr(member.recorder, "meeting_dir", None)
            if meeting_dir is not None and Path(meeting_dir) not in candidates:
                candidates.append(Path(meeting_dir))
        return candidates

    # ------------------------------------------------------------------ lifecycle

    async def start(self, *, run_loop: bool = True) -> None:
        """Load any stored timeline, restore attached roots, record the enabled status and begin ticking."""
        stored = await asyncio.to_thread(self._event_log.load_existing, self._candidate_directories())
        if stored is not None:
            if not self._mode_explicit:
                self.settings.mode = stored.mode
            if not self._model_explicit:
                self.settings.model_id = stored.model_id
            if not self._focus_explicit:
                self.settings.focus = stored.focus
        self._derived = None
        events = self._event_log.events()
        self._latest_meeting_time = max(self._latest_meeting_time, max((event.meeting_time for event in events), default=0.0))
        restored = False
        for root in list(self._get_derived().roots):
            try:
                resolved, kind = validate_root(root.path)
            except RootRejected:
                self._append(
                    "source",
                    self._latest_meeting_time,
                    {"root_id": root.id, "state": "detached", "path": root.path, "display_name": root.display_name, "kind": root.kind},
                )
                continue
            self._context.attach_root(root.id, resolved, kind, root.display_name)
            restored = True
        if restored:
            self._spawn(self._context.rebuild_vocabulary())
        self._append("status", self._latest_meeting_time, self._status_payload())
        await self._broadcast_status(self._clock(), force=True)
        if run_loop:
            self._loop_task = asyncio.ensure_future(self._run_loop())

    async def _run_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(TICK_SECONDS)
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error("Companion tick failed for %s: %s", self.session_key, error, exc_info=True)

    # ------------------------------------------------------------------ members and ingestion

    def add_member(
        self,
        *,
        meeting_id: str,
        role: TurnRole,
        speaker: str,
        recorder: Any,
        start_epoch: Optional[float],
        existing_segments: Sequence[Dict[str, Any]] = (),
    ) -> None:
        """Register one recorder; its already-final segments from the last 90 seconds become history only."""
        if meeting_id in self._members:
            return
        self._session_clock.register_member(meeting_id, start_epoch)
        member = _Member(
            meeting_id=meeting_id,
            role=role,
            assembler=UtteranceAssembler(
                source_meeting_id=meeting_id,
                role=role,
                default_speaker=speaker,
                id_prefix=f"t{self._nonce}{len(self._members) + 1}-",
            ),
            recorder=recorder,
        )
        self._members[meeting_id] = member
        self._known_ids.add(meeting_id)
        if self._primary_meeting_id is None:
            self._primary_meeting_id = meeting_id
        self._anchor_cache = None
        self._seed(member, existing_segments)

    def remove_member(self, meeting_id: str) -> int:
        """Finalize and drop one recorder; returns the number of members left."""
        member = self._members.pop(meeting_id, None)
        if member is not None:
            self._ingest(member.assembler.flush_all())
            if self._primary_meeting_id == meeting_id and self._members:
                self._primary_meeting_id = next(iter(self._members))
            self._anchor_cache = None
        return len(self._members)

    def _seed(self, member: _Member, segments: Sequence[Dict[str, Any]]) -> None:
        usable = [
            segment
            for segment in segments
            if not segment.get("is_interim") and str(segment.get("text") or "").strip()
        ]
        if not usable:
            return
        usable.sort(key=lambda segment: float(segment["start"]))
        latest_end = max(float(segment["end"]) for segment in usable)
        member.seeded_until = latest_end
        seed_assembler = UtteranceAssembler(
            source_meeting_id=member.meeting_id,
            role=member.role,
            default_speaker=member.assembler.default_speaker,
            id_prefix=f"s{self._nonce}{len(self._members)}-",
        )
        now = self._clock()
        turns: List[CompanionTurn] = []
        for segment in usable:
            if float(segment["end"]) < latest_end - SEED_WINDOW_SECONDS:
                continue
            turns.extend(
                seed_assembler.add_fragment(
                    start=self._session_clock.to_meeting_time(member.meeting_id, float(segment["start"])),
                    end=self._session_clock.to_meeting_time(member.meeting_id, float(segment["end"])),
                    text=str(segment["text"]),
                    speaker=segment.get("speaker"),
                    now_wall=now,
                )
            )
        turns.extend(seed_assembler.flush_all())
        for turn in turns:
            self._gate.seed_history(turn)
            self._latest_meeting_time = max(self._latest_meeting_time, turn.end)

    def on_segment(self, meeting_id: str, segment: Dict[str, Any]) -> None:
        """Feed one finalized recorder fragment (called on the loop thread)."""
        member = self._members.get(meeting_id)
        if member is None or self._closed or segment.get("is_interim"):
            return
        text = segment.get("text")
        if not text or not str(text).strip():
            return
        end = float(segment["end"])
        if end <= member.seeded_until:
            return
        start = self._session_clock.to_meeting_time(meeting_id, float(segment["start"]))
        meeting_end = self._session_clock.to_meeting_time(meeting_id, end)
        self._latest_meeting_time = max(self._latest_meeting_time, meeting_end)
        self._ingest(
            member.assembler.add_fragment(
                start=start,
                end=meeting_end,
                text=str(text),
                speaker=segment.get("speaker"),
                now_wall=self._clock(),
            )
        )

    def _ingest(self, turns: Sequence[CompanionTurn]) -> None:
        now = self._clock()
        for turn in turns:
            self._gate.add_turn(turn, now)
            self._latest_meeting_time = max(self._latest_meeting_time, turn.end)

    # ------------------------------------------------------------------ the tick

    async def tick(self) -> None:
        """One scheduling step: idle flush, capacity, gate, prefetch, persistence, status."""
        if self._closed:
            return
        now = self._clock()
        for member in list(self._members.values()):
            self._ingest(member.assembler.flush_idle(now))
        assessment = self._capacity_guard.assess(now)
        self._lag_seconds = assessment.lag_seconds
        if assessment.state != self._capacity:
            self._capacity = assessment.state
            self._capacity_reason = assessment.reason
            self._append("status", self._latest_meeting_time, self._status_payload())
            await self._broadcast_status(now, force=True)
        if not self._evaluating:
            decision = self._gate.decide(
                now,
                mode=self.settings.mode,
                watches=self._get_derived().watches,
                allowed=allowed_triggers(self._capacity),
            )
            if decision.fire:
                self._evaluating = True
                self._evaluation_task = self._spawn(self._run_evaluation(decision, now))
        prefetch_idle = self._prefetch_task is None or self._prefetch_task.done()
        if (
            prefetch_allowed(self._capacity)
            and prefetch_idle
            and self._context.has_roots()
            and now - self._last_prefetch_at >= PREFETCH_INTERVAL_SECONDS
        ):
            self._last_prefetch_at = now
            self._prefetch_task = self._spawn(self._run_prefetch(now))
        if self._event_log.is_dirty():
            await asyncio.to_thread(self._event_log.flush_if_due, now)
        await self._broadcast_status(now)

    async def _run_evaluation(self, decision: GateDecision, started: float) -> None:
        try:
            self._gate.commit(decision, started)
            derived = self._get_derived()
            already_shown = [item.text for item in derived.items][-6:]
            pack = None
            if self._context.has_roots():
                extra_queries = list(decision.watch.keywords) if decision.watch is not None else []
                lookup = await self._context.lookup(" ".join(turn.text for turn in decision.new_turns), extra_queries=extra_queries)
                if lookup is not None:
                    pack = lookup.pack
                    self._log_retrieval("watch" if decision.watch is not None else "answer", lookup, started, always=True)
            request = EvaluationRequest(
                trigger=decision.trigger or "periodic",
                mode=self.settings.mode,
                meeting_time=self._latest_meeting_time,
                new_turns=list(decision.new_turns),
                window_turns=self._gate.window(),
                conversation_state=self._conversation.text,
                already_shown=already_shown,
                pack=pack,
                has_roots=self._context.has_roots(),
                watch=decision.watch,
                model_id=self.settings.model_id,
                focus=self.settings.focus,
            )
            outcome = await self._evaluator.evaluate(request)
            self._apply_outcome(decision, outcome, started)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error("Companion evaluation crashed for %s: %s", self.session_key, error, exc_info=True)
            self._record_error("evaluation_failed", str(error))
        finally:
            self._evaluating = False

    def _apply_outcome(self, decision: GateDecision, outcome: EvaluationOutcome, started: float) -> None:
        if self._closed:
            return
        if outcome.conversation_state:
            self._conversation.apply(outcome.conversation_state, self._latest_meeting_time)
        if outcome.error:
            self._record_error("evaluation_failed", outcome.error)
            return
        if self._clock() - started > MAX_RESULT_AGE_SECONDS:
            logger.info("Companion discarded a stale evaluation result for %s", self.session_key)
            return
        latency_ms = max(0, int(round((self._clock() - started) * 1000)))
        for item in outcome.items:
            stamped = item.model_copy(update={"latency_ms": latency_ms})
            self._append("item", stamped.transcript_range.end, {"item": stamped.model_dump(mode="json")})
        if decision.watch is not None:
            self._append("watch", self._latest_meeting_time, watch_event_payload(decision.watch, "triggered"))

    async def _run_prefetch(self, now: float) -> None:
        try:
            text = " ".join(turn.text for turn in self._gate.window(30.0, 12))
            lookup = await self._context.prefetch(text)
            if lookup is not None and lookup.pack.hit_count > 0:
                self._log_retrieval("prefetch", lookup, now, always=False)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Companion prefetch failed for %s: %s", self.session_key, error, exc_info=True)

    def _log_retrieval(self, purpose: str, lookup: ContextLookup, now: float, *, always: bool) -> None:
        if not always and now - self._last_prefetch_log_at < PREFETCH_LOG_INTERVAL_SECONDS:
            return
        if purpose == "prefetch":
            self._last_prefetch_log_at = now
        self._append(
            "retrieval",
            self._latest_meeting_time,
            {
                "purpose": purpose,
                "queries": list(lookup.queries),
                "hit_count": lookup.pack.hit_count,
                "paths": lookup.pack.paths()[:6],
                "duration_ms": lookup.pack.duration_ms,
                "cache": lookup.cache,
            },
        )

    def _record_error(self, code: str, message: str) -> None:
        now = self._clock()
        if now - self._last_error_at.get(code, float("-inf")) < ERROR_LOG_INTERVAL_SECONDS:
            return
        self._last_error_at[code] = now
        self._append("error", self._latest_meeting_time, {"code": code, "message": message[:MAX_ERROR_MESSAGE_CHARS]})

    # ------------------------------------------------------------------ events and broadcast

    def _append(self, kind: str, meeting_time: float, payload: Dict[str, Any]) -> TimelineEvent:
        return self._event_log.append(kind, meeting_time, payload)  # type: ignore[arg-type]

    def _on_event(self, event: TimelineEvent) -> None:
        self._derived = None
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._spawn(self._broadcast({"event_type": "meeting_companion_event", "event": event.model_dump(mode="json")}))

    def _spawn(self, coroutine: Awaitable[Any]) -> "asyncio.Future[Any]":
        task = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _broadcast(self, payload: Dict[str, Any]) -> None:
        message = {**payload, "session_key": self.session_key, "meeting_ids": self.meeting_ids()}
        try:
            await self._broadcast_fn(message)
        except Exception as error:
            logger.warning("Companion broadcast failed: %s", error)

    async def _broadcast_status(self, now: float, *, force: bool = False) -> None:
        if not force and now - self._last_status_broadcast_at < STATUS_BROADCAST_INTERVAL_SECONDS:
            return
        self._last_status_broadcast_at = now
        await self._broadcast({"event_type": "meeting_companion_status", **self.status().model_dump(mode="json")})

    async def wait_idle(self) -> None:
        """Await every background and chat task (used by tests and by close)."""
        while True:
            pending = [task for task in (*self._tasks, *self._chat_tasks) if not task.done()]
            if not pending:
                return
            await asyncio.gather(*pending, return_exceptions=True)
    # ------------------------------------------------------------------ settings and feedback

    def update_settings(
        self,
        *,
        mode: Optional[CompanionMode] = None,
        model_id: Union[str, None, _Unset] = UNSET,
        focus: Optional[str] = None,
    ) -> CompanionSettings:
        """Change the mode, model and/or focus mid-meeting; records one status event when anything changed."""
        changed = False
        if mode is not None and mode != self.settings.mode:
            self.settings.mode = mode
            self._mode_explicit = True
            changed = True
        if not isinstance(model_id, _Unset):
            cleaned = model_id or None
            if cleaned != self.settings.model_id:
                self.settings.model_id = cleaned
                self._model_explicit = True
                changed = True
        if focus is not None:
            cleaned_focus = focus.strip()
            if cleaned_focus != self.settings.focus:
                self.settings.focus = cleaned_focus
                self._focus_explicit = True
                changed = True
        if changed:
            self._append("status", self._latest_meeting_time, self._status_payload())
            self._spawn(self._broadcast_status(self._clock(), force=True))
        return self.settings

    def record_feedback(self, item_id: str, action: str) -> bool:
        """Record dismiss, pin or another reaction; ``False`` when the item does not exist."""
        if action not in get_args(FeedbackAction):
            raise ValueError(f"Unknown feedback action: {action}")
        if not any(item.id == item_id for item in self._get_derived().items):
            return False
        self._append("feedback", self._latest_meeting_time, {"item_id": item_id, "action": action})
        return True

    # ------------------------------------------------------------------ watches and sources

    def create_watch(self, topic: str, instruction: str) -> CompanionWatch:
        """Create a standing "when X comes up, do Y" watch; raises ``WatchRejected`` with a user-facing reason."""
        active = sum(1 for watch in self._get_derived().watches if watch.active)
        payload = build_watch_created_payload(topic, instruction, active_count=active)
        self._append("watch", self._latest_meeting_time, payload)
        return next(watch for watch in self._get_derived().watches if watch.id == payload["watch_id"])

    def cancel_watch(self, watch_id: str) -> bool:
        watch = next((candidate for candidate in self._get_derived().watches if candidate.id == watch_id and candidate.active), None)
        if watch is None:
            return False
        self._append("watch", self._latest_meeting_time, watch_event_payload(watch, "cancelled"))
        return True

    def attach_root(self, path_text: str) -> CompanionRoot:
        """Attach a folder or file as read-only grounding; raises ``RootRejected`` with a user-facing reason."""
        resolved, kind = validate_root(path_text)
        roots = self._get_derived().roots
        existing = next((root for root in roots if root.path == str(resolved)), None)
        if existing is not None:
            return existing
        if len(roots) >= MAX_ROOTS:
            raise RootRejected(f"At most {MAX_ROOTS} sources can be attached to one meeting.")
        root_id = f"r-{uuid.uuid4().hex[:8]}"
        display_name = resolved.name or str(resolved)
        self._context.attach_root(root_id, resolved, kind, display_name)
        self._append(
            "source",
            self._latest_meeting_time,
            {"root_id": root_id, "state": "attached", "path": str(resolved), "display_name": display_name, "kind": kind},
        )
        self._spawn(self._context.rebuild_vocabulary())
        return next(root for root in self._get_derived().roots if root.id == root_id)

    def detach_root(self, root_id: str) -> bool:
        root = next((candidate for candidate in self._get_derived().roots if candidate.id == root_id), None)
        if root is None:
            return False
        self._context.detach_root(root_id)
        self._append(
            "source",
            self._latest_meeting_time,
            {"root_id": root.id, "state": "detached", "path": root.path, "display_name": root.display_name, "kind": root.kind},
        )
        if self._context.has_roots():
            self._spawn(self._context.rebuild_vocabulary())
        return True

    # ------------------------------------------------------------------ chat

    def submit_chat(self, text: str) -> str:
        """Record a user message and answer it in the background; returns the assistant message id."""
        if self._closed:
            raise RuntimeError("The Companion session has ended.")
        cleaned = (text or "").strip()
        if not cleaned:
            raise ValueError("Type a message first.")
        if len(cleaned) > MAX_CHAT_CHARS:
            raise ValueError(f"Messages can be at most {MAX_CHAT_CHARS} characters.")
        user_id = f"m-{uuid.uuid4().hex[:8]}"
        assistant_id = f"m-{uuid.uuid4().hex[:8]}"
        self._append("chat", self._latest_meeting_time, {"message_id": user_id, "role": "user", "text": cleaned})
        task = asyncio.ensure_future(self._handle_chat(cleaned, user_id, assistant_id))
        self._chat_tasks.add(task)
        task.add_done_callback(self._chat_tasks.discard)
        return assistant_id

    async def _handle_chat(self, text: str, user_id: str, assistant_id: str) -> None:
        pieces: List[str] = []
        try:
            async with self._chat_lock:
                watch_request = parse_watch_request(text)
                if watch_request is not None:
                    self._reply_to_watch_request(watch_request, assistant_id)
                else:
                    await self._answer_chat(text, user_id, assistant_id, pieces)
        except asyncio.CancelledError:
            partial = "".join(pieces).strip()
            self._record_assistant_message(
                assistant_id,
                partial or "The meeting ended before I could answer.",
                truncated=bool(partial),
                status="complete" if partial else "error",
            )
            raise
        except Exception as error:
            logger.error("Companion chat crashed for %s: %s", self.session_key, error, exc_info=True)
            self._record_assistant_message(assistant_id, "I couldn't answer that right now.", truncated=False, status="error")

    def _reply_to_watch_request(self, watch_request: Tuple[str, str], assistant_id: str) -> None:
        topic, instruction = watch_request
        try:
            watch = self.create_watch(topic, instruction)
            reply = f"Watching for \u201c{watch.topic}\u201d. When it comes up I will: {watch.instruction}"
            status = "complete"
        except WatchRejected as rejection:
            reply = str(rejection)
            status = "error"
        self._record_assistant_message(assistant_id, reply, truncated=False, status=status)

    async def _answer_chat(self, text: str, user_id: str, assistant_id: str, pieces: List[str]) -> None:
        history = [message for message in self._get_derived().chat if message.id not in (user_id, assistant_id)][-8:]
        recent = " ".join(turn.text for turn in self._gate.window(60.0, 12))
        pack = None
        if self._context.has_roots():
            lookup = await self._context.lookup(f"{text} {recent}")
            if lookup is not None:
                pack = lookup.pack
                self._log_retrieval("chat", lookup, self._clock(), always=True)
        request = ChatRequest(
            user_text=text,
            meeting_time=self._latest_meeting_time,
            window_turns=self._gate.window(),
            conversation_state=self._conversation.text,
            history=history,
            pack=pack,
            has_roots=self._context.has_roots(),
            model_id=self.settings.model_id,
            focus=self.settings.focus,
        )

        async def on_delta(piece: str) -> None:
            pieces.append(piece)
            await self._broadcast({"event_type": "meeting_companion_chat_delta", "message_id": assistant_id, "text_delta": piece, "done": False, "truncated": False})

        result = await self._chat.stream_answer(request, on_delta)
        self._record_assistant_message(assistant_id, result.display_text(), truncated=result.truncated, status=result.status)

    def _record_assistant_message(self, message_id: str, text: str, *, truncated: bool, status: str) -> None:
        self._append(
            "chat",
            self._latest_meeting_time,
            {"message_id": message_id, "role": "assistant", "text": text, "truncated": truncated, "status": status},
        )

    # ------------------------------------------------------------------ shutdown

    async def close(self, *, discard: bool = False, final_enabled: bool = True) -> None:
        """Stop the session: cancel evaluation, let in-flight chat finish, persist, and announce the final status."""
        if self._closed:
            return
        self._closed = True
        self.settings.enabled = final_enabled
        for task in (self._loop_task, self._evaluation_task, self._prefetch_task):
            if task is not None and not task.done():
                task.cancel()
        pending_chat = [task for task in self._chat_tasks if not task.done()]
        if pending_chat and not discard:
            _done, still_running = await asyncio.wait(pending_chat, timeout=CHAT_CLOSE_GRACE_SECONDS)
            for task in still_running:
                task.cancel()
        else:
            for task in pending_chat:
                task.cancel()
        remaining = [task for task in (self._loop_task, *self._tasks, *self._chat_tasks) if task is not None and not task.done()]
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)
        await self.wait_idle()
        self._evaluating = False
        if discard:
            self._event_log.discard()
        else:
            self._append("status", self._latest_meeting_time, self._status_payload())
            await asyncio.to_thread(self._event_log.flush)
        await self._broadcast_status(self._clock(), force=True)
        await self.wait_idle()
        self._event_log.unsubscribe(self._on_event)
