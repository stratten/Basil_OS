"""Turns a gate decision into timeline-ready Companion items through one structured model call."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from api.core.models.model_invocation import StructuredModelOutputError, call_model_with_schema

from .context_pack import ContextPack
from .conversation_state import format_transcript
from .evaluation_ledger import (
    DROP_CONFIDENCE_FLOOR,
    DROP_DUPLICATE,
    DROP_EMPTY,
    DROP_OVER_CAP,
    KEPT,
    CandidateRecord,
    clean_considered,
)
from .investigator.escalation import ResearchRequest, honored_research
from .models import CompanionItem, CompanionMode, CompanionTurn, CompanionWatch, TranscriptRange
from .prompts import build_evaluation_prompt
from .similarity import content_tokens, jaccard, normalize_text

logger = logging.getLogger(__name__)

MAX_ITEMS = 2
MAX_ITEM_CHARS = 600
DUPLICATE_SIMILARITY = 0.6
PACK_PROMPT_CHARS = 9000
WINDOW_PROMPT_CHARS = 6000


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluatedItem(_Contract):
    kind: Literal["insight", "suggestion", "answer", "context_note"]
    text: str
    confidence: float
    pack_ids: List[str] = Field(default_factory=list)
    source_turn_ids: List[str] = Field(default_factory=list)


class EvaluatedProposal(_Contract):
    """A follow-up a speaker committed to or asked for; only these two actions can be proposed from the fast path."""

    action: Literal["todo", "agent_task"]
    title: str
    instruction: str
    confidence: float


class CompanionEvaluationResponse(_Contract):
    items: List[EvaluatedItem] = Field(default_factory=list)
    proposals: List[EvaluatedProposal] = Field(default_factory=list)
    conversation_state: str = ""
    research: Optional[ResearchRequest] = None
    # One or two plain sentences on what the model weighed, including when it stayed silent.
    considered: str = ""


@dataclass
class EvaluationRequest:
    trigger: str
    mode: CompanionMode
    meeting_time: float
    new_turns: List[CompanionTurn]
    window_turns: List[CompanionTurn]
    conversation_state: str
    already_shown: List[str]
    pack: Optional[ContextPack]
    has_roots: bool
    watch: Optional[CompanionWatch] = None
    model_id: Optional[str] = None
    focus: str = ""


@dataclass
class EvaluationOutcome:
    items: List[CompanionItem] = field(default_factory=list)
    conversation_state: Optional[str] = None
    latency_ms: int = 0
    error: Optional[str] = None
    dropped: int = 0
    model_id: Optional[str] = None
    finish_reason: Optional[str] = None
    research: Optional[ResearchRequest] = None
    considered: str = ""
    candidates: List[CandidateRecord] = field(default_factory=list)
    # At most one follow-up proposal that cleared the confidence floor; the session shapes it into a review card.
    proposals: List[EvaluatedProposal] = field(default_factory=list)


QUESTION_CONFIDENCE_FLOOR = 0.4
DEFAULT_CONFIDENCE_FLOOR = 0.6


def min_confidence_for(trigger: str) -> float:
    """The lowest confidence a note may have; asked-for notes (a question or a watch) clear a lower bar than unprompted ones. The replay harness overrides these module values to test other floors."""
    return QUESTION_CONFIDENCE_FLOOR if trigger in ("question", "watch") else DEFAULT_CONFIDENCE_FLOOR


def best_proposals(response: CompanionEvaluationResponse, trigger: str) -> List[EvaluatedProposal]:
    """The single most confident proposal at or above the trigger's floor, or none."""
    floor = min_confidence_for(trigger)
    eligible = [entry for entry in response.proposals if entry.confidence >= floor and normalize_text(entry.title) and normalize_text(entry.instruction)]
    eligible.sort(key=lambda entry: entry.confidence, reverse=True)
    return eligible[:1]


def default_item_id() -> str:
    return f"it-{uuid.uuid4().hex[:10]}"


def materialize_items(
    response: CompanionEvaluationResponse,
    request: EvaluationRequest,
    *,
    id_factory: Callable[[], str] = default_item_id,
    records: Optional[List[CandidateRecord]] = None,
) -> Tuple[List[CompanionItem], int]:
    """Validate, deduplicate, cite and time-range the model's items; returns ``(items, dropped_count)``.

    When ``records`` is given, one ``CandidateRecord`` per candidate is appended to it with the reason it was kept or dropped.
    """
    rationale = clean_considered(response.considered)

    def record(raw: EvaluatedItem, text: str, confidence: float, outcome: str) -> None:
        if records is not None:
            records.append(CandidateRecord(kind=raw.kind, text=text, confidence=confidence, outcome=outcome))

    turns_by_id: Dict[str, CompanionTurn] = {turn.id: turn for turn in request.window_turns}
    turns_by_id.update({turn.id: turn for turn in request.new_turns})
    prior_tokens = [content_tokens(text) for text in request.already_shown]
    floor = min_confidence_for(request.trigger)
    kept: List[CompanionItem] = []
    dropped = 0
    for raw in response.items:
        text = normalize_text(raw.text)[:MAX_ITEM_CHARS]
        confidence = min(1.0, max(0.0, float(raw.confidence)))
        if len(kept) >= MAX_ITEMS:
            dropped += 1
            record(raw, text, confidence, DROP_OVER_CAP)
            continue
        if not text:
            dropped += 1
            record(raw, text, confidence, DROP_EMPTY)
            continue
        if confidence < floor:
            dropped += 1
            record(raw, text, confidence, DROP_CONFIDENCE_FLOOR)
            continue
        tokens = content_tokens(text)
        if any(jaccard(tokens, prior) >= DUPLICATE_SIMILARITY for prior in prior_tokens):
            dropped += 1
            record(raw, text, confidence, DROP_DUPLICATE)
            continue
        citations = request.pack.citations(raw.pack_ids) if request.pack is not None else []
        referenced = [turns_by_id[turn_id] for turn_id in raw.source_turn_ids if turn_id in turns_by_id]
        if not referenced:
            referenced = list(request.new_turns)
        if referenced:
            start = min(turn.start for turn in referenced)
            end = max(turn.end for turn in referenced)
            turn_ids = [turn.id for turn in referenced]
        else:
            start = end = request.meeting_time
            turn_ids = []
        kept.append(
            CompanionItem(
                id=id_factory(),
                kind=raw.kind,
                text=text,
                confidence=round(confidence, 3),
                citations=citations,
                no_source=(raw.kind == "answer" and not citations),
                transcript_range=TranscriptRange(start=start, end=end, turn_ids=turn_ids),
                trigger=request.trigger,
                watch_id=request.watch.id if request.watch is not None else None,
                rationale=rationale,
            )
        )
        record(raw, text, confidence, KEPT)
        prior_tokens.append(tokens)
    return kept, dropped


async def load_companion_model(model_id: Optional[str]) -> Any:
    """Load the analysis model exactly as the meeting analyzer does; ``None`` selects the default reasoning model."""
    from api.core.models.model_types import ModelCapability
    from api.dependencies import get_model_service
    from api.services.model_usage_service import ModelUsageService

    model = await ModelUsageService(get_model_service()).get_model_for_task(
        capabilities={ModelCapability.REASONING},
        explicit_model_id=model_id,
    )
    if model is None:
        raise RuntimeError("No suitable reasoning model is available")
    return model


def default_token_budget(model: Any) -> int:
    from api.core.models.reasoning.streaming_contract import resolve_generation_budget

    return resolve_generation_budget(
        model,
        purpose="general",
        requested_output_tokens=1500,
        minimum_output_tokens=512,
    ).effective_output_tokens


class CompanionEvaluator:
    def __init__(
        self,
        *,
        model_loader: Callable[[Optional[str]], Awaitable[Any]] = load_companion_model,
        schema_caller: Callable[..., Awaitable[Any]] = call_model_with_schema,
        token_budget: Callable[[Any], int] = default_token_budget,
        clock: Callable[[], float] = time.monotonic,
        timeout_seconds: float = 60.0,
        id_factory: Callable[[], str] = default_item_id,
    ) -> None:
        self._model_loader = model_loader
        self._schema_caller = schema_caller
        self._token_budget = token_budget
        self._clock = clock
        self._timeout_seconds = timeout_seconds
        self._id_factory = id_factory
        self._cached_model_id: Optional[str] = None
        self._cached_model: Any = None
        self._has_cached_model = False

    async def model_for(self, model_id: Optional[str]) -> Any:
        """The loaded model for ``model_id``; reloads only when the selection changed."""
        if self._has_cached_model and self._cached_model_id == model_id:
            return self._cached_model
        model = await self._model_loader(model_id)
        self._cached_model_id = model_id
        self._cached_model = model
        self._has_cached_model = True
        return model

    def forget_model(self) -> None:
        self._cached_model = None
        self._has_cached_model = False

    async def evaluate(self, request: EvaluationRequest) -> EvaluationOutcome:
        started = self._clock()

        def elapsed_ms() -> int:
            return int((self._clock() - started) * 1000)

        try:
            model = await self.model_for(request.model_id)
        except Exception as error:
            return EvaluationOutcome(error=f"model_unavailable: {error}", latency_ms=elapsed_ms(), model_id=request.model_id)
        prompt = self.build_prompt(request)
        try:
            response = await asyncio.wait_for(
                self._schema_caller(
                    model,
                    prompt=prompt,
                    response_model=CompanionEvaluationResponse,
                    max_tokens=self._token_budget(model),
                ),
                timeout=self._timeout_seconds,
            )
        except asyncio.TimeoutError:
            return EvaluationOutcome(error="timeout", latency_ms=elapsed_ms(), model_id=request.model_id)
        except StructuredModelOutputError as error:
            if not error.retryable:
                self.forget_model()
            return EvaluationOutcome(error=f"{error.category}: {error}", latency_ms=elapsed_ms(), model_id=request.model_id)
        except Exception as error:
            logger.warning("Companion evaluation failed: %s", error, exc_info=True)
            return EvaluationOutcome(error=f"evaluation_failed: {error}", latency_ms=elapsed_ms(), model_id=request.model_id)
        records: List[CandidateRecord] = []
        items, dropped = materialize_items(response.value, request, id_factory=self._id_factory, records=records)
        return EvaluationOutcome(
            considered=clean_considered(response.value.considered),
            candidates=records,
            proposals=best_proposals(response.value, request.trigger),
            items=items,
            conversation_state=response.value.conversation_state or None,
            latency_ms=elapsed_ms(),
            dropped=dropped,
            model_id=request.model_id,
            finish_reason=getattr(response, "finish_reason", None),
            research=honored_research(
                response.value.research,
                trigger=request.trigger,
                item_count=len(items),
                sourced_item_count=sum(1 for entry in items if entry.citations),
            ),
        )

    def build_prompt(self, request: EvaluationRequest) -> str:
        if not request.has_roots:
            status, context_text = "none_attached", ""
        elif request.pack is not None and not request.pack.is_empty:
            status, context_text = "excerpts", request.pack.render(PACK_PROMPT_CHARS)
        else:
            status, context_text = "no_results", ""
        return build_evaluation_prompt(
            trigger=request.trigger,
            conversation_state=request.conversation_state,
            already_shown=request.already_shown[-6:],
            context_status=status,
            context_text=context_text,
            watch_instruction=request.watch.instruction if request.watch is not None else None,
            window_text=format_transcript(request.window_turns, WINDOW_PROMPT_CHARS),
            new_line_ids=[turn.id for turn in request.new_turns],
            focus=request.focus,
        )
