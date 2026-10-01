"""Fits a direct conversation into the answering model's input budget using stored summaries."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, tzinfo
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from ...core.models.token_utils import estimate_tokens
from .conversation_context_builder import (
    ConversationContextParts,
    build_runtime_preamble,
    compose_base_system_message,
    conversation_input_budget_tokens,
    render_exchange_messages,
    resolve_current_model_name,
    split_conversation_exchanges,
)
from .conversation_exchange_summaries import current_exchange_summary, valid_conversation_brief
from .conversation_inline_note import INLINE_NOTE_INSTRUCTION, append_inline_note_reminder
from .conversation_turn_summarizer import SUMMARY_ELIGIBILITY_TOKENS, conversation_history_tokens
from .conversation_models import Message

logger = logging.getLogger(__name__)

TokenCounter = Callable[[str], int]

MESSAGE_OVERHEAD_TOKENS = 8
ESTIMATED_COUNT_SAFETY_RATIO = 0.9
VERBATIM_SHARE_WITH_SUMMARIES = 0.6
MINIMUM_NEWEST_CONTENT_TOKENS = 256
OMITTED_NOTE_RESERVE_TOKENS = 24
CONDENSED_CONTEXT_HEADER = "Condensed earlier conversation (from Basil, not written by the user). The full conversation is too long for your context window, so older exchanges appear here in condensed form, and the most recent exchanges follow as normal messages."
BRIEF_HEADING = "Running brief of the earliest exchanges:"
SUMMARIES_HEADING = "Summaries of later exchanges, oldest first:"
TRIMMED_CONTENT_MARKER = "\n\n[Basil removed the middle of this message because it is too long for the model's context window.]\n\n"


def make_token_counter(llm_model: Any) -> Tuple[TokenCounter, bool]:
    """Use the model's own tokenizer when it reports exact counts, otherwise the character estimate."""
    tokenizer = getattr(llm_model, "tokenizer", None)
    if getattr(tokenizer, "exact_token_counts", False) is not True:
        return estimate_tokens, False
    encode = tokenizer.encode

    def count_tokens(text: str) -> int:
        try:
            return len(encode(text))
        except Exception:
            return estimate_tokens(text)

    return count_tokens, True


def _content_text(content: Any) -> str:
    return content if isinstance(content, str) else json.dumps(content, default=str)


def _messages_tokens(messages: Sequence[Dict[str, Any]], count_tokens: TokenCounter) -> int:
    return sum(
        count_tokens(_content_text(message.get("content", ""))) + MESSAGE_OVERHEAD_TOKENS
        for message in messages
    )


def exchange_time_label(timestamp: datetime, local_tz: tzinfo) -> str:
    """Stored timestamps are naive UTC; label them in the user's local zone."""
    aware = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=timezone.utc)
    local = aware.astimezone(local_tz)
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"{local.strftime('%a, %b')} {local.day}, {hour}:{local.strftime('%M %p')}"


def _trim_content(content: Any, target_tokens: int, count_tokens: TokenCounter) -> Any:
    if not isinstance(content, str):
        return content
    current_tokens = count_tokens(content)
    if current_tokens <= target_tokens:
        return content
    keep_chars = max(2, int(len(content) * target_tokens / current_tokens) - len(TRIMMED_CONTENT_MARKER))
    head_chars = (keep_chars * 2) // 3
    tail_chars = keep_chars - head_chars
    return f"{content[:head_chars]}{TRIMMED_CONTENT_MARKER}{content[len(content) - tail_chars:]}"


def _condensed_section(brief_text: Optional[str], summary_lines: Sequence[str], omitted_count: int) -> str:
    sections = [CONDENSED_CONTEXT_HEADER]
    if brief_text:
        sections.append(f"{BRIEF_HEADING}\n{brief_text}")
    if summary_lines:
        sections.append("\n".join([SUMMARIES_HEADING, *summary_lines]))
    if omitted_count == 1:
        sections.append("1 older exchange is not included at all.")
    elif omitted_count > 1:
        sections.append(f"{omitted_count} older exchanges are not included at all.")
    return "\n\n".join(sections)


def fit_conversation_context(
    parts: ConversationContextParts,
    *,
    base_system_message: str,
    current_model_name: Optional[str],
    conversation_metadata: Any,
    newest_content_override: Any,
    budget_tokens: Optional[int],
    count_tokens: TokenCounter,
    local_tz: tzinfo,
    remind_inline_note: bool = False,
) -> List[Dict[str, Any]]:
    """Keep recent exchanges verbatim and represent older ones by the brief and summaries when everything does not fit."""
    rendered = [render_exchange_messages(exchange, current_model_name) for exchange in parts.exchanges]
    if newest_content_override is not None and rendered and rendered[-1]:
        rendered[-1][-1]["content"] = newest_content_override
    if remind_inline_note and rendered and rendered[-1] and rendered[-1][-1].get("role") == "user":
        rendered[-1][-1]["content"] = append_inline_note_reminder(rendered[-1][-1].get("content", ""))
    system_message = {"role": "system", "content": base_system_message}
    full_messages = [system_message, *(message for group in rendered for message in group)]
    if budget_tokens is None or not rendered:
        return full_messages
    if _messages_tokens(full_messages, count_tokens) <= budget_tokens:
        return full_messages

    older_exchanges = parts.exchanges[:-1]
    older_rendered = rendered[:-1]
    newest_messages = rendered[-1]
    fixed_tokens = (
        _messages_tokens([system_message], count_tokens)
        + count_tokens(CONDENSED_CONTEXT_HEADER)
        + count_tokens(BRIEF_HEADING)
        + count_tokens(SUMMARIES_HEADING)
        + OMITTED_NOTE_RESERVE_TOKENS
    )
    newest_tokens = _messages_tokens(newest_messages, count_tokens)
    newest_allowance = budget_tokens - fixed_tokens
    if newest_messages and newest_tokens > newest_allowance:
        earlier_newest_tokens = _messages_tokens(newest_messages[:-1], count_tokens)
        target_tokens = max(
            MINIMUM_NEWEST_CONTENT_TOKENS,
            newest_allowance - earlier_newest_tokens - MESSAGE_OVERHEAD_TOKENS,
        )
        last_message = dict(newest_messages[-1])
        last_message["content"] = _trim_content(last_message.get("content", ""), target_tokens, count_tokens)
        newest_messages = [*newest_messages[:-1], last_message]
        newest_tokens = _messages_tokens(newest_messages, count_tokens)
    remaining_tokens = max(0, budget_tokens - fixed_tokens - newest_tokens)

    brief = valid_conversation_brief(parts.exchanges, conversation_metadata)
    summaries: Dict[int, str] = {}
    for index, exchange in enumerate(older_exchanges):
        record = current_exchange_summary(exchange)
        if record is not None and record.text:
            summaries[index] = record.text
    has_condensed_material = brief is not None or bool(summaries)
    verbatim_limit = (
        int(remaining_tokens * VERBATIM_SHARE_WITH_SUMMARIES)
        if has_condensed_material
        else remaining_tokens
    )

    verbatim_start = len(older_exchanges)
    verbatim_tokens = 0
    for index in range(len(older_exchanges) - 1, -1, -1):
        exchange_tokens = _messages_tokens(older_rendered[index], count_tokens)
        if verbatim_tokens + exchange_tokens > verbatim_limit:
            break
        verbatim_tokens += exchange_tokens
        verbatim_start = index

    condensed_exchanges = older_exchanges[:verbatim_start]
    condensed_budget = remaining_tokens - verbatim_tokens
    condensed_tokens = 0
    brief_text: Optional[str] = None
    covered_ids: Set[str] = set()
    if brief is not None:
        condensed_anchor_ids = {
            exchange.anchor.id for exchange in condensed_exchanges if exchange.anchor is not None
        }
        brief_tokens = count_tokens(brief.text)
        if condensed_anchor_ids.intersection(brief.covered_anchor_ids) and brief_tokens <= condensed_budget:
            brief_text = brief.text
            covered_ids = set(brief.covered_anchor_ids)
            condensed_tokens += brief_tokens

    summary_lines: List[str] = []
    omitted_count = 0
    budget_exhausted = False
    for index in range(len(condensed_exchanges) - 1, -1, -1):
        exchange = condensed_exchanges[index]
        anchor = exchange.anchor
        if anchor is not None and anchor.id in covered_ids:
            continue
        summary_text = summaries.get(index)
        if summary_text is None or budget_exhausted:
            omitted_count += 1
            continue
        stamp_source = exchange.user if exchange.user is not None else anchor
        line = f"- [{exchange_time_label(stamp_source.timestamp, local_tz)}] {summary_text}"
        line_tokens = count_tokens(line) + 1
        if condensed_tokens + line_tokens > condensed_budget:
            budget_exhausted = True
            omitted_count += 1
            continue
        condensed_tokens += line_tokens
        summary_lines.append(line)
    summary_lines.reverse()

    system_content = base_system_message
    if condensed_exchanges:
        system_content = f"{base_system_message}\n\n{_condensed_section(brief_text, summary_lines, omitted_count)}"
    verbatim_messages = [message for group in older_rendered[verbatim_start:] for message in group]
    logger.info(
        "Fitted conversation into a %d-token budget: %d older exchanges verbatim, %d summaries, brief included: %s, %d omitted",
        budget_tokens,
        len(older_exchanges) - verbatim_start,
        len(summary_lines),
        brief_text is not None,
        omitted_count,
    )
    return [{"role": "system", "content": system_content}, *verbatim_messages, *newest_messages]


def build_fitted_conversation_messages(
    messages: Sequence[Message],
    *,
    llm_model: Any,
    requested_model_id: Optional[str],
    conversation_metadata: Any,
    newest_content_override: Any = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Build the model-facing messages for a direct turn and fit them to the answering model's input budget."""
    current_now = now or datetime.now().astimezone()
    local_tz = current_now.tzinfo or datetime.now().astimezone().tzinfo or timezone.utc
    current_model_name = resolve_current_model_name(llm_model, requested_model_id)
    parts = split_conversation_exchanges(messages)
    base_system_message = compose_base_system_message(
        parts.system_content,
        build_runtime_preamble(current_model_name, current_now),
    )
    request_inline_note = conversation_history_tokens(parts.exchanges) >= SUMMARY_ELIGIBILITY_TOKENS
    if request_inline_note:
        base_system_message = f"{base_system_message}\n\n{INLINE_NOTE_INSTRUCTION}"
    count_tokens, exact_counts = make_token_counter(llm_model)
    budget_tokens = conversation_input_budget_tokens(llm_model)
    if budget_tokens is not None and not exact_counts:
        budget_tokens = int(budget_tokens * ESTIMATED_COUNT_SAFETY_RATIO)
    return fit_conversation_context(
        parts,
        base_system_message=base_system_message,
        current_model_name=current_model_name,
        conversation_metadata=conversation_metadata,
        newest_content_override=newest_content_override,
        budget_tokens=budget_tokens,
        count_tokens=count_tokens,
        local_tz=local_tz,
        remind_inline_note=request_inline_note,
    )
