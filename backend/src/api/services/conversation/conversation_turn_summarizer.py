"""Writes per-exchange summaries and a running brief for long direct conversations."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Set

from ...core.models.models_registry import get_model
from ...core.models.reasoning.streaming_contract import resolve_generation_budget
from ...core.models.token_utils import estimate_tokens
from .conversation_context_builder import (
    ConversationExchange,
    split_conversation_exchanges,
    user_message_model_content,
)
from .conversation_exchange_summaries import (
    coverage_fingerprint_for,
    exchange_needs_summary,
    exchange_source_texts,
    prior_failed_attempts,
    summary_coverage_entries,
    valid_conversation_brief,
)
from .conversation_models import Conversation
from .conversation_summary_contract import (
    CONVERSATION_BRIEF_METADATA_KEY,
    SUMMARY_FORMAT_VERSION,
    TURN_SUMMARY_METADATA_KEY,
    ConversationBriefRecord,
    TurnSummaryRecord,
    TurnSummaryStatus,
    exchange_fingerprint,
)

logger = logging.getLogger(__name__)

SUMMARY_ELIGIBILITY_TOKENS = 4000
RECENT_EXCHANGES_LEFT_UNSUMMARIZED = 2
MAX_SUMMARIES_PER_PASS = 4
BRIEF_REFRESH_MIN_NEW_SUMMARIES = 4
BRIEF_REFRESH_BATCH_SIZE = 12
SUMMARY_SOURCE_CHAR_LIMIT = 24000
TURN_SUMMARY_MAX_CHARS = 700
CONVERSATION_BRIEF_MAX_CHARS = 2400
FALLBACK_SUMMARY_OUTPUT_TOKENS = 1024
_NATIVE_LOCK_TYPES = (type(threading.Lock()), type(threading.RLock()))
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)

TURN_SUMMARY_SYSTEM_PROMPT = "You write compact recaps of one exchange in a long conversation between a user and an AI assistant. The recaps later stand in for the full text when the conversation no longer fits in a model's context window, so they must keep what a later reply would need."
TURN_SUMMARY_INSTRUCTIONS = "Summarize the exchange below in at most three sentences and under 90 words. Keep concrete facts, decisions, names, numbers, dates, file paths, code identifiers, commitments, open questions, and anything the user asked to remember. Write in the third person, for example \"The user asked\" and \"The assistant explained\". Output only the summary, with no heading or preamble."
BRIEF_SYSTEM_PROMPT = "You maintain a running brief of a long conversation between a user and an AI assistant. The brief later stands in for the oldest part of the conversation when it no longer fits in a model's context window."
BRIEF_INSTRUCTIONS = "Update the brief so it also covers the new exchange summaries below. Write at most 10 short bullet points and under 250 words. Cover the user's goals, the facts and decisions that were established, preferences the user stated, and threads that are still unresolved. Drop details that later exchanges superseded. Output only the brief, with no heading or preamble."

LoadConversation = Callable[[str], Awaitable[Optional[Conversation]]]
GetActiveModel = Callable[[str], Optional[Any]]
LoadModel = Callable[[str], Awaitable[Optional[Any]]]
ScheduleTask = Callable[[Any, str], Any]


@dataclass
class SummaryPassOutcome:
    """What one pass did; returned for logging and tests."""

    eligible: bool = False
    summarized: int = 0
    failed: int = 0
    skipped_unavailable: int = 0
    stopped_busy: bool = False
    brief_updated: bool = False


def summary_model_location(model_id: str) -> Optional[str]:
    """Return the registry location ("local" or "cloud") for a model id, or None when unknown."""
    for candidate in (model_id, model_id.replace("/", "-")):
        try:
            config = get_model(candidate)
        except Exception:
            config = None
        if isinstance(config, dict):
            location = config.get("location")
            return location if isinstance(location, str) else None
    return None


def local_model_is_idle(model: Any) -> bool:
    """A held native execution lock means a local generation is running right now."""
    lock = getattr(model, "native_execution_lock", None)
    if not isinstance(lock, _NATIVE_LOCK_TYPES):
        return True
    if not lock.acquire(blocking=False):
        return False
    lock.release()
    return True


def conversation_history_tokens(exchanges: Sequence[ConversationExchange]) -> int:
    total = 0
    for exchange in exchanges:
        if exchange.user is not None:
            total += estimate_tokens(user_message_model_content(exchange.user))
        total += sum(estimate_tokens(assistant.content) for assistant in exchange.assistants)
    return total


def pending_summary_exchanges(exchanges: Sequence[ConversationExchange]) -> List[ConversationExchange]:
    """Older exchanges that still need a summary, oldest first."""
    if len(exchanges) <= RECENT_EXCHANGES_LEFT_UNSUMMARIZED:
        return []
    candidates = exchanges[: len(exchanges) - RECENT_EXCHANGES_LEFT_UNSUMMARIZED]
    return [exchange for exchange in candidates if exchange_needs_summary(exchange)]


def clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    clipped = text[:limit]
    boundary = clipped.rfind(" ")
    if boundary > limit // 2:
        clipped = clipped[:boundary]
    return clipped.rstrip()


def _clip_source(text: str) -> str:
    if len(text) <= SUMMARY_SOURCE_CHAR_LIMIT:
        return text
    head_chars = (SUMMARY_SOURCE_CHAR_LIMIT * 2) // 3
    tail_chars = SUMMARY_SOURCE_CHAR_LIMIT - head_chars
    return f"{text[:head_chars]}\n[middle of message omitted]\n{text[len(text) - tail_chars:]}"


def clean_summary_output(raw: Any, limit: int) -> str:
    if not isinstance(raw, str):
        raise ValueError("Summary output was not text")
    text = _THINK_BLOCK.sub("", raw)
    if "<think>" in text:
        raise ValueError("Summary output contained unterminated reasoning")
    text = text.strip()
    if not text:
        raise ValueError("Summary output was empty")
    return clip_text(text, limit)


def build_turn_summary_messages(user_text: str, assistant_text: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": TURN_SUMMARY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{TURN_SUMMARY_INSTRUCTIONS}\n\n"
                f"User message:\n<<<\n{_clip_source(user_text)}\n>>>\n\n"
                f"Assistant reply:\n<<<\n{_clip_source(assistant_text)}\n>>>"
            ),
        },
    ]


def build_brief_messages(previous_brief: Optional[str], summaries: Sequence[str]) -> List[Dict[str, str]]:
    numbered = "\n".join(f"{position}. {summary}" for position, summary in enumerate(summaries, start=1))
    return [
        {"role": "system", "content": BRIEF_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{BRIEF_INSTRUCTIONS}\n\n"
                f"Current brief:\n<<<\n{previous_brief or '(none yet)'}\n>>>\n\n"
                f"New exchange summaries, oldest first:\n<<<\n{numbered}\n>>>"
            ),
        },
    ]


def _accepts_keyword(function: Any, name: str) -> bool:
    try:
        return name in inspect.signature(function).parameters
    except (TypeError, ValueError):
        return False


async def generate_summary_text(model: Any, messages: List[Dict[str, str]], limit: int) -> str:
    try:
        max_tokens = int(resolve_generation_budget(model, purpose="narrative").effective_output_tokens)
    except Exception:
        max_tokens = FALLBACK_SUMMARY_OUTPUT_TOKENS
    kwargs: Dict[str, Any] = {"max_tokens": max_tokens}
    if _accepts_keyword(model.generate_from_messages, "enable_web_search"):
        kwargs["enable_web_search"] = False
    raw = await model.generate_from_messages(messages, **kwargs)
    return clean_summary_output(raw, limit)


class ConversationTurnSummarizer:
    """Owns background summary passes for direct conversations."""

    def __init__(
        self,
        *,
        repository: Any,
        load_conversation: LoadConversation,
        get_active_model: GetActiveModel,
        load_model: LoadModel,
        schedule_task: ScheduleTask,
    ) -> None:
        self._repository = repository
        self._load_conversation = load_conversation
        self._get_active_model = get_active_model
        self._load_model = load_model
        self._schedule_task = schedule_task
        self._pass_lock = asyncio.Lock()
        self._running: Set[str] = set()
        self._rerun_requested: Set[str] = set()

    def request_pass(self, conversation_id: str) -> None:
        if conversation_id in self._running:
            self._rerun_requested.add(conversation_id)
            return
        self._running.add(conversation_id)
        self._schedule_task(self._run_passes(conversation_id), f"conversation-summaries-{conversation_id}")

    async def _run_passes(self, conversation_id: str) -> None:
        try:
            while True:
                self._rerun_requested.discard(conversation_id)
                try:
                    outcome = await self.run_pass(conversation_id)
                    if outcome.summarized or outcome.failed or outcome.brief_updated:
                        logger.info("Conversation %s summary pass: %s", conversation_id, outcome)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("Conversation %s summary pass failed: %s", conversation_id, exc)
                if conversation_id not in self._rerun_requested:
                    return
        finally:
            self._running.discard(conversation_id)
            self._rerun_requested.discard(conversation_id)

    async def run_pass(self, conversation_id: str) -> SummaryPassOutcome:
        outcome = SummaryPassOutcome()
        async with self._pass_lock:
            conversation = await self._load_conversation(conversation_id)
            if conversation is None:
                return outcome
            parts = split_conversation_exchanges(conversation.messages)
            if conversation_history_tokens(parts.exchanges) < SUMMARY_ELIGIBILITY_TOKENS:
                return outcome
            outcome.eligible = True
            await self._summarize_pending(parts.exchanges, outcome)
            if outcome.stopped_busy:
                return outcome
            refreshed = await self._load_conversation(conversation_id)
            if refreshed is not None:
                await self._refresh_brief(refreshed, outcome)
        return outcome

    async def _resolve_summary_model(self, model_id: str) -> Optional[Any]:
        active_model = self._get_active_model(model_id)
        if active_model is not None:
            return active_model
        if summary_model_location(model_id) != "cloud":
            return None
        try:
            return await self._load_model(model_id)
        except Exception as exc:
            logger.warning("Summary model %s could not be prepared: %s", model_id, exc)
            return None

    async def _summarize_pending(
        self,
        exchanges: Sequence[ConversationExchange],
        outcome: SummaryPassOutcome,
    ) -> None:
        for exchange in pending_summary_exchanges(exchanges)[:MAX_SUMMARIES_PER_PASS]:
            anchor = exchange.anchor
            texts = exchange_source_texts(exchange)
            if anchor is None or texts is None or not anchor.model_id:
                continue
            model = await self._resolve_summary_model(anchor.model_id)
            if model is None:
                outcome.skipped_unavailable += 1
                continue
            if not local_model_is_idle(model):
                outcome.stopped_busy = True
                return
            fingerprint = exchange_fingerprint(texts[0], texts[1])
            attempt_count = prior_failed_attempts(exchange, fingerprint) + 1
            try:
                summary_text = await generate_summary_text(
                    model,
                    build_turn_summary_messages(texts[0], texts[1]),
                    TURN_SUMMARY_MAX_CHARS,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Summary for message %s failed: %s", anchor.id, exc)
                record = TurnSummaryRecord(
                    status=TurnSummaryStatus.FAILED,
                    text=None,
                    source_fingerprint=fingerprint,
                    model_id=anchor.model_id,
                    attempt_count=attempt_count,
                    version=SUMMARY_FORMAT_VERSION,
                )
                outcome.failed += 1
            else:
                record = TurnSummaryRecord(
                    status=TurnSummaryStatus.COMPLETED,
                    text=summary_text,
                    source_fingerprint=fingerprint,
                    model_id=anchor.model_id,
                    attempt_count=attempt_count,
                    version=SUMMARY_FORMAT_VERSION,
                )
                outcome.summarized += 1
            await self._repository.merge_message_metadata(
                anchor.id,
                {TURN_SUMMARY_METADATA_KEY: record.to_metadata()},
                touch_conversation=False,
            )

    async def _refresh_brief(self, conversation: Conversation, outcome: SummaryPassOutcome) -> None:
        parts = split_conversation_exchanges(conversation.messages)
        entries = summary_coverage_entries(parts.exchanges)
        brief = valid_conversation_brief(parts.exchanges, conversation.metadata)
        covered_count = len(brief.covered_anchor_ids) if brief is not None else 0
        uncovered = entries[covered_count:]
        if len(uncovered) < BRIEF_REFRESH_MIN_NEW_SUMMARIES:
            return
        batch = uncovered[:BRIEF_REFRESH_BATCH_SIZE]
        model_id = batch[-1].model_id
        if not model_id:
            return
        model = await self._resolve_summary_model(model_id)
        if model is None:
            return
        if not local_model_is_idle(model):
            outcome.stopped_busy = True
            return
        try:
            brief_text = await generate_summary_text(
                model,
                build_brief_messages(brief.text if brief is not None else None, [entry.text for entry in batch]),
                CONVERSATION_BRIEF_MAX_CHARS,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Brief refresh for conversation %s failed: %s", conversation.id, exc)
            return
        covered = entries[: covered_count + len(batch)]
        record = ConversationBriefRecord(
            text=brief_text,
            covered_anchor_ids=tuple(entry.anchor_id for entry in covered),
            covered_fingerprint=coverage_fingerprint_for(covered),
            model_id=model_id,
            version=SUMMARY_FORMAT_VERSION,
        )
        await self._repository.merge_conversation_metadata(
            conversation.id,
            {CONVERSATION_BRIEF_METADATA_KEY: record.to_metadata()},
        )
        outcome.brief_updated = True
