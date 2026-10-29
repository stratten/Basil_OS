"""Owns the investigations of one Companion session: start policy, lifecycle, cancellation and the timeline results."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from ..context_service import ContextService
from ..models import CompanionItem, CompanionSettings, CompanionTurn, CompanionWatch, TimelineEvent, TranscriptRange
from ..proposals import DEFAULT_POLICY, ProposalPolicy, may_auto_start, shape_proposals
from ..similarity import content_tokens, jaccard
from .models import (
    AUTOMATIC_ORIGINS,
    DUPLICATE_QUESTION_SIMILARITY,
    InvestigationOrigin,
    InvestigationRejected,
    InvestigationRequest,
    InvestigationResult,
)
from .policy import decide_start
from .runner import CompanionInvestigator
from .triggers import MIN_QUESTION_CHARS, normalize_question

logger = logging.getLogger(__name__)

INVESTIGATION_PURPOSE = "investigation"


@dataclass
class InvestigationHost:
    """What the coordinator needs from its session, as narrow callables instead of private attribute access."""

    settings: Callable[[], CompanionSettings]
    context: ContextService
    capacity: Callable[[], str]
    closed: Callable[[], bool]
    latest_meeting_time: Callable[[], float]
    window_turns: Callable[[], List[CompanionTurn]]
    conversation_state: Callable[[], str]
    shown_texts: Callable[[], List[str]]
    model_provider: Callable[[Optional[str]], Awaitable[Any]]
    append: Callable[[str, float, Dict[str, Any]], Any]
    spawn: Callable[[Awaitable[Any]], "asyncio.Future[Any]"]
    record_error: Callable[[str, str], None]
    status_changed: Callable[[], None]
    proposal_policy: Callable[[], ProposalPolicy] = lambda: DEFAULT_POLICY
    items: Callable[[], List[CompanionItem]] = lambda: []
    watch_for: Callable[[str], Optional[CompanionWatch]] = lambda watch_id: None
    auto_start: Callable[[CompanionItem, CompanionWatch], None] = lambda item, watch: None


@dataclass
class _Run:
    request: InvestigationRequest
    cancel_event: "asyncio.Event"
    range_start: float
    range_end: float
    turn_ids: List[str]
    task: Optional["asyncio.Future[Any]"] = None


def _range_for(turns: Sequence[CompanionTurn], turn_ids: Sequence[str], meeting_time: float) -> tuple:
    wanted = set(turn_ids)
    referenced = [turn for turn in turns if turn.id in wanted]
    if not referenced:
        return meeting_time, meeting_time, []
    return min(turn.start for turn in referenced), max(turn.end for turn in referenced), [turn.id for turn in referenced]


class InvestigationCoordinator:
    def __init__(self, investigator: Optional[CompanionInvestigator], host: InvestigationHost) -> None:
        self._investigator = investigator
        self._host = host
        self._runs: Dict[str, _Run] = {}
        self._runs_started = 0
        self._questions: List[str] = []
        self._auto_starts = 0

    @property
    def active_count(self) -> int:
        return len(self._runs)

    @property
    def runs_started(self) -> int:
        return self._runs_started

    def restore(self, events: Sequence[TimelineEvent]) -> None:
        """Rebuild the per-meeting run count and question list from the durable start events after a restart."""
        started = [event for event in events if event.kind == "retrieval" and event.payload.get("purpose") == INVESTIGATION_PURPOSE]
        self._runs_started = len(started)
        self._questions = [str((event.payload.get("queries") or [""])[0]) for event in started]
        self._auto_starts = sum(1 for event in events if event.kind == "proposal" and event.payload.get("auto") and event.payload.get("state") in ("started", "failed"))

    def request(
        self,
        question: str,
        *,
        origin: InvestigationOrigin,
        source_turn_ids: Sequence[str] = (),
        watch_id: Optional[str] = None,
        reply_to_message_id: Optional[str] = None,
    ) -> str:
        """Start one investigation and return its id; raises ``InvestigationRejected`` with a user-facing reason."""
        if self._host.closed():
            raise RuntimeError("The Companion session has ended.")
        cleaned = normalize_question(question)
        if len(cleaned) < MIN_QUESTION_CHARS:
            raise ValueError("Describe what to look into.")
        if self._investigator is None:
            raise InvestigationRejected("The investigator is not available.")
        decision = decide_start(
            origin=origin,
            question=cleaned,
            capacity=self._host.capacity(),
            enabled=self._host.settings().investigate,
            active_count=len(self._runs),
            concurrency_limit=self._investigator.concurrency_limit,
            runs_started=self._runs_started,
            prior_questions=self._questions,
        )
        if not decision.allowed:
            raise InvestigationRejected(decision.reason)
        investigation_id = f"iv-{uuid.uuid4().hex[:8]}"
        meeting_time = self._host.latest_meeting_time()
        turns = self._host.window_turns()
        range_start, range_end, turn_ids = _range_for(turns, source_turn_ids, meeting_time)
        settings = self._host.settings()
        request = InvestigationRequest(
            investigation_id=investigation_id,
            origin=origin,
            question=cleaned,
            meeting_time=meeting_time,
            window_turns=turns,
            conversation_state=self._host.conversation_state(),
            focus=settings.focus,
            model_id=settings.model_id,
            watch_id=watch_id,
            source_turn_ids=list(turn_ids),
            reply_to_message_id=reply_to_message_id,
        )
        run = _Run(request=request, cancel_event=asyncio.Event(), range_start=range_start, range_end=range_end, turn_ids=turn_ids)
        self._runs[investigation_id] = run
        self._runs_started += 1
        self._questions.append(cleaned)
        self._host.append(
            "retrieval",
            meeting_time,
            {
                "purpose": INVESTIGATION_PURPOSE,
                "queries": [cleaned],
                "hit_count": 0,
                "paths": [],
                "duration_ms": 0,
                "cache": "miss",
                "investigation_id": investigation_id,
                "origin": origin,
            },
        )
        run.task = self._host.spawn(self._run(run))
        self._host.status_changed()
        return investigation_id

    def cancel(self, investigation_id: str) -> bool:
        run = self._runs.get(investigation_id)
        if run is None:
            return False
        run.cancel_event.set()
        return True

    def cancel_all(self) -> int:
        """Ask every active run to stop; each run ends by itself at its next checkpoint."""
        for run in self._runs.values():
            run.cancel_event.set()
        return len(self._runs)

    async def _run(self, run: _Run) -> None:
        investigation_id = run.request.investigation_id
        investigator = self._investigator
        if investigator is None:
            self._runs.pop(investigation_id, None)
            return
        try:
            result = await investigator.investigate(
                run.request,
                context=self._host.context,
                cancel_event=run.cancel_event,
                model_provider=self._host.model_provider,
            )
            self._apply(run, result)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error("Companion investigation %s crashed: %s", investigation_id, error, exc_info=True)
            if not self._host.closed():
                self._record_outcome(run, status="failed", shown=False, reason="crashed")
            if run.request.origin not in AUTOMATIC_ORIGINS:
                self._host.record_error("investigation_failed", f"The investigation could not finish: {error}")
        finally:
            self._runs.pop(investigation_id, None)
            if not self._host.closed():
                self._host.status_changed()

    def _apply(self, run: _Run, result: InvestigationResult) -> None:
        if self._host.closed():
            return
        shown, reason = self._show_result(run, result)
        self._record_outcome(run, status=result.status, shown=shown, reason=reason, result=result)

    def _show_result(self, run: _Run, result: InvestigationResult) -> Tuple[bool, str]:
        """Put the result on the timeline when it deserves to be seen; returns whether it was shown and, when it was not, why."""
        request = run.request
        automatic = request.origin in AUTOMATIC_ORIGINS
        if result.status == "canceled":
            return False, "canceled"
        if result.status in ("failed", "timed_out"):
            logger.info("Companion investigation %s ended %s: %s", request.investigation_id, result.status, result.detail)
            if not automatic:
                reason = "ran out of time" if result.status == "timed_out" else "failed"
                self._host.record_error("investigation_failed", f"The investigation {reason}: {request.question}")
            return False, result.status
        if result.status == "not_found":
            if automatic:
                return False, "no_answer_automatic"
            text = f"I looked through the attached files and your Basil records and could not find an answer to: {request.question}"
            self._append_item(run, result, kind="context_note", text=text, confidence=0.5)
            return True, ""
        if automatic:
            answer_tokens = content_tokens(result.answer)
            if any(jaccard(answer_tokens, content_tokens(text)) >= DUPLICATE_QUESTION_SIMILARITY for text in self._host.shown_texts()):
                return False, "duplicate_of_shown_note"
        self._append_item(run, result, kind="answer", text=result.answer, confidence=result.confidence)
        self._append_proposals(run, result)
        return True, ""

    def _record_outcome(self, run: _Run, *, status: str, shown: bool, reason: str, result: Optional[InvestigationResult] = None) -> None:
        """Save how a run ended. The start event is only a placeholder, so this is what shows whether research found anything and whether the reader saw it."""
        request = run.request
        self._host.append(
            "investigation",
            run.range_end,
            {
                "investigation_id": request.investigation_id,
                "origin": request.origin,
                "status": status,
                "shown": shown,
                "reason": reason,
                "detail": (result.detail if result is not None else "")[:200],
                "duration_ms": result.duration_ms if result is not None else 0,
                "tool_calls": result.tool_calls if result is not None else 0,
                "evidence_count": result.evidence_count if result is not None else 0,
                "citations": len(result.citations) if result is not None else 0,
                "has_sources": bool(getattr(self._host.context, "has_roots", lambda: False)()),
            },
        )

    def _append_proposals(self, run: _Run, result: InvestigationResult) -> None:
        """Append the run's proposals as approval cards; one starts by itself only with an active watch of the user's as its authority."""
        if not result.proposals:
            return
        request = run.request
        watch = self._host.watch_for(request.watch_id) if request.origin == "watch" and request.watch_id else None
        policy = self._host.proposal_policy()
        cards = shape_proposals(
            result.proposals,
            policy=policy,
            existing=self._host.items(),
            investigation_id=request.investigation_id,
            transcript_range=TranscriptRange(start=run.range_start, end=run.range_end, turn_ids=list(run.turn_ids)),
            watch_id=request.watch_id,
            watch_authority=watch is not None,
            confidence=result.confidence,
        )
        for card in cards:
            self._host.append("item", card.transcript_range.end, {"item": card.model_dump(mode="json")})
            if watch is not None and card.proposal is not None and may_auto_start(policy, card.proposal, auto_started=self._auto_starts):
                self._auto_starts += 1
                self._host.auto_start(card, watch)

    def _append_item(self, run: _Run, result: InvestigationResult, *, kind: str, text: str, confidence: float) -> None:
        request = run.request
        item = CompanionItem(
            id=f"it-{uuid.uuid4().hex[:10]}",
            kind=kind,  # type: ignore[arg-type]
            text=text,
            confidence=confidence,
            citations=list(result.citations),
            no_source=not result.citations,
            transcript_range=TranscriptRange(start=run.range_start, end=run.range_end, turn_ids=list(run.turn_ids)),
            trigger="investigation",
            watch_id=request.watch_id,
            latency_ms=result.duration_ms,
            researched=True,
            investigation_id=request.investigation_id,
            evidence_count=result.evidence_count,
            reply_to_message_id=request.reply_to_message_id,
        )
        self._host.append("item", item.transcript_range.end, {"item": item.model_dump(mode="json")})
