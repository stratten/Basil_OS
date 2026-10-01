"""Reads exchange summaries and the conversation brief against the conversation's current text."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple

from .conversation_context_builder import ConversationExchange, user_message_model_content
from .conversation_summary_contract import (
    MAX_TURN_SUMMARY_ATTEMPTS,
    SUMMARY_FORMAT_VERSION,
    ConversationBriefRecord,
    TurnSummaryRecord,
    TurnSummaryStatus,
    coverage_fingerprint,
    exchange_fingerprint,
    parse_conversation_brief,
    parse_turn_summary,
)
from .conversation_turn_contract import (
    CONVERSATION_TURN_METADATA_KEY,
    ConversationTurnLifecycle,
    ConversationTurnRoute,
    parse_conversation_turn_metadata,
)


@dataclass(frozen=True)
class SummaryCoverageEntry:
    """One exchange whose stored summary still matches its current text."""

    anchor_id: str
    source_fingerprint: str
    text: str
    model_id: Optional[str]


def exchange_source_texts(exchange: ConversationExchange) -> Optional[Tuple[str, str]]:
    """Return the user text and joined assistant text a summary is written from."""
    if exchange.user is None or not exchange.assistants:
        return None
    user_text = user_message_model_content(exchange.user)
    assistant_text = "\n\n".join(assistant.content for assistant in exchange.assistants)
    return user_text, assistant_text


def exchange_current_fingerprint(exchange: ConversationExchange) -> Optional[str]:
    texts = exchange_source_texts(exchange)
    if texts is None:
        return None
    return exchange_fingerprint(texts[0], texts[1])


def current_exchange_summary(exchange: ConversationExchange) -> Optional[TurnSummaryRecord]:
    """Return the completed summary only while it still describes the exchange's current text."""
    anchor = exchange.anchor
    fingerprint = exchange_current_fingerprint(exchange)
    if anchor is None or fingerprint is None:
        return None
    record = parse_turn_summary(anchor.metadata)
    if record is None or record.status != TurnSummaryStatus.COMPLETED:
        return None
    if record.version != SUMMARY_FORMAT_VERSION or record.source_fingerprint != fingerprint:
        return None
    return record


def is_summarizable_exchange(exchange: ConversationExchange) -> bool:
    """Completed direct exchanges with a recorded answering model; agent-task turns are never summarized."""
    anchor = exchange.anchor
    if exchange.user is None or anchor is None:
        return False
    if not isinstance(anchor.model_id, str) or not anchor.model_id.strip():
        return False
    metadata = anchor.metadata if isinstance(anchor.metadata, dict) else {}
    if CONVERSATION_TURN_METADATA_KEY not in metadata:
        return True
    turn = parse_conversation_turn_metadata(metadata)
    if turn is None:
        return False
    return turn.route == ConversationTurnRoute.DIRECT and turn.lifecycle == ConversationTurnLifecycle.COMPLETED


def exchange_needs_summary(exchange: ConversationExchange) -> bool:
    """True when no current summary exists and the retry limit for this exact text is not exhausted."""
    if not is_summarizable_exchange(exchange):
        return False
    fingerprint = exchange_current_fingerprint(exchange)
    anchor = exchange.anchor
    if fingerprint is None or anchor is None:
        return False
    record = parse_turn_summary(anchor.metadata)
    if record is None or record.version != SUMMARY_FORMAT_VERSION or record.source_fingerprint != fingerprint:
        return True
    if record.status == TurnSummaryStatus.COMPLETED:
        return False
    return record.attempt_count < MAX_TURN_SUMMARY_ATTEMPTS


def prior_failed_attempts(exchange: ConversationExchange, fingerprint: str) -> int:
    """Count earlier failed attempts for this exact exchange text."""
    anchor = exchange.anchor
    record = parse_turn_summary(anchor.metadata) if anchor is not None else None
    if record is None or record.status != TurnSummaryStatus.FAILED or record.source_fingerprint != fingerprint:
        return 0
    return record.attempt_count


def summary_coverage_entries(exchanges: Sequence[ConversationExchange]) -> List[SummaryCoverageEntry]:
    """List exchanges with a current summary, oldest first."""
    entries: List[SummaryCoverageEntry] = []
    for exchange in exchanges:
        record = current_exchange_summary(exchange)
        anchor = exchange.anchor
        if record is None or record.text is None or anchor is None:
            continue
        entries.append(
            SummaryCoverageEntry(
                anchor_id=anchor.id,
                source_fingerprint=record.source_fingerprint,
                text=record.text,
                model_id=record.model_id,
            )
        )
    return entries


def coverage_fingerprint_for(entries: Sequence[SummaryCoverageEntry]) -> str:
    return coverage_fingerprint([(entry.anchor_id, entry.source_fingerprint) for entry in entries])


def valid_conversation_brief(
    exchanges: Sequence[ConversationExchange],
    conversation_metadata: Any,
) -> Optional[ConversationBriefRecord]:
    """Return the brief only while it covers an unchanged, ordered prefix of the current summaries."""
    brief = parse_conversation_brief(conversation_metadata)
    if brief is None or brief.version != SUMMARY_FORMAT_VERSION:
        return None
    entries = summary_coverage_entries(exchanges)
    covered_count = len(brief.covered_anchor_ids)
    if covered_count > len(entries):
        return None
    prefix = entries[:covered_count]
    if tuple(entry.anchor_id for entry in prefix) != brief.covered_anchor_ids:
        return None
    if coverage_fingerprint_for(prefix) != brief.covered_fingerprint:
        return None
    return brief
