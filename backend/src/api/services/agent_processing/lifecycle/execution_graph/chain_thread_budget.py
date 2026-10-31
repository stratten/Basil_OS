"""Fit a replayed conversation into a share of the model's prompt budget before the turn starts.

The stored thread is never rewritten: only what is replayed to the model is reduced, so recall tools still see the full history.
The reactive compaction in ``agent_loop_model_recovery`` remains the safety net if an estimate is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from api.core.logging.api_logger import api_logger

from .context_window_budget import estimate_prompt_tokens
from .conversation_turns import clip_text, is_turn_input, message_text, request_text

logger = api_logger.getChild("chain_thread_budget")

HISTORY_SHARE_OF_PROMPT_BUDGET = 0.5
SCHEDULED_HISTORY_CEILING_TOKENS = 24_000
OLD_REQUEST_MAX_CHARS = 4_000
ANSWER_CLIP_CHARS = 1_500
OLD_TOOL_RESULT_STUB = "[Earlier tool result removed to fit the model's context window.]"
REPEATED_REQUEST_STUB = "[Same request as the most recent one below.]"
OMITTED_NOTE = "({count} earlier exchange{plural} left out to fit the model's context window; recall_agent_tasks(scope='detail') has the full history.)"


@dataclass
class FitResult:
    """The messages to replay, which reduction steps were needed, and how many exchanges were dropped."""

    messages: List[BaseMessage]
    levels: List[str] = field(default_factory=list)
    dropped_exchanges: int = 0


def history_budget_tokens(prompt_budget: Optional[int], *, scheduled: bool) -> Optional[int]:
    """Tokens the replayed conversation may use, or None when nothing bounds it."""
    candidates: List[int] = []
    if prompt_budget:
        candidates.append(int(prompt_budget * HISTORY_SHARE_OF_PROMPT_BUDGET))
    if scheduled:
        candidates.append(SCHEDULED_HISTORY_CEILING_TOKENS)
    return min(candidates) if candidates else None


def _split_exchanges(messages: Sequence[BaseMessage]) -> List[List[BaseMessage]]:
    flagged = any(is_turn_input(message) for message in messages)
    exchanges: List[List[BaseMessage]] = []
    for message in messages:
        starts = is_turn_input(message) if flagged else isinstance(message, HumanMessage)
        if starts or not exchanges:
            exchanges.append([message])
        else:
            exchanges[-1].append(message)
    return exchanges


def _flatten(exchanges: Sequence[Sequence[BaseMessage]]) -> List[BaseMessage]:
    return [message for exchange in exchanges for message in exchange]


def _tokens(exchanges: Sequence[Sequence[BaseMessage]]) -> int:
    return estimate_prompt_tokens(_flatten(exchanges))


def _with_content(message: BaseMessage, content: str) -> BaseMessage:
    return message.model_copy(update={"content": content})


def _stub_old_tool_results(exchanges: List[List[BaseMessage]]) -> List[List[BaseMessage]]:
    result: List[List[BaseMessage]] = []
    for index, exchange in enumerate(exchanges):
        if index == len(exchanges) - 1:
            result.append(exchange)
            continue
        result.append(
            [
                _with_content(message, OLD_TOOL_RESULT_STUB)
                if isinstance(message, ToolMessage) and len(message_text(message.content)) > len(OLD_TOOL_RESULT_STUB)
                else message
                for message in exchange
            ]
        )
    return result


def _final_answer(exchange: Sequence[BaseMessage]) -> Optional[BaseMessage]:
    for message in reversed(exchange[1:]):
        if isinstance(message, AIMessage) and not (message.tool_calls or []) and message_text(message.content).strip():
            return message
    return None


def _keep_requests_and_answers(exchanges: List[List[BaseMessage]]) -> List[List[BaseMessage]]:
    result: List[List[BaseMessage]] = []
    for index, exchange in enumerate(exchanges):
        if index == len(exchanges) - 1:
            result.append(exchange)
            continue
        request = exchange[0]
        if isinstance(request, HumanMessage):
            request = _with_content(request, clip_text(request_text(request.content), OLD_REQUEST_MAX_CHARS))
        kept = [request]
        answer = _final_answer(exchange)
        if answer is not None:
            kept.append(answer)
        result.append(kept)
    return result


def _collapse_repeated_requests(exchanges: List[List[BaseMessage]]) -> List[List[BaseMessage]]:
    if len(exchanges) < 2:
        return exchanges
    latest_request = request_text(exchanges[-1][0].content)
    if not latest_request:
        return exchanges
    result: List[List[BaseMessage]] = []
    for index, exchange in enumerate(exchanges):
        first = exchange[0]
        if index < len(exchanges) - 1 and isinstance(first, HumanMessage) and request_text(first.content) == latest_request:
            result.append([_with_content(first, REPEATED_REQUEST_STUB), *exchange[1:]])
        else:
            result.append(exchange)
    return result


def _clip_answers(exchanges: List[List[BaseMessage]]) -> List[List[BaseMessage]]:
    result: List[List[BaseMessage]] = []
    for exchange in exchanges:
        result.append(
            [
                _with_content(message, clip_text(message_text(message.content), ANSWER_CLIP_CHARS))
                if isinstance(message, AIMessage)
                and not (message.tool_calls or [])
                and len(message_text(message.content)) > ANSWER_CLIP_CHARS
                else message
                for message in exchange
            ]
        )
    return result


def _with_omitted_note(messages: List[BaseMessage], dropped: int) -> List[BaseMessage]:
    note = OMITTED_NOTE.format(count=dropped, plural="" if dropped == 1 else "s")
    for index, message in enumerate(messages):
        if isinstance(message, HumanMessage):
            messages[index] = _with_content(message, f"{note}\n\n{message_text(message.content)}")
            break
    return messages


def fit_prior_messages(messages: Sequence[BaseMessage], history_budget: Optional[int]) -> FitResult:
    """Reduce a replayed conversation, step by step, until it fits ``history_budget`` tokens; the latest exchange is never dropped."""
    flat = list(messages)
    if not history_budget or not flat or estimate_prompt_tokens(flat) <= history_budget:
        return FitResult(messages=flat)
    before = estimate_prompt_tokens(flat)
    exchanges = _split_exchanges(flat)
    levels: List[str] = []
    steps = (
        ("stub_old_tool_results", _stub_old_tool_results),
        ("collapse_repeated_requests", _collapse_repeated_requests),
        ("keep_requests_and_answers", _keep_requests_and_answers),
    )
    for name, step in steps:
        exchanges = step(exchanges)
        levels.append(name)
        if _tokens(exchanges) <= history_budget:
            return _finish(exchanges, levels, 0, before, history_budget)
    dropped = 0
    while len(exchanges) > 1 and _tokens(exchanges) > history_budget:
        exchanges = exchanges[1:]
        dropped += 1
    if dropped:
        levels.append("drop_oldest_exchanges")
    if _tokens(exchanges) > history_budget:
        exchanges = _clip_answers(exchanges)
        levels.append("clip_answers")
    return _finish(exchanges, levels, dropped, before, history_budget)


def _finish(
    exchanges: List[List[BaseMessage]], levels: List[str], dropped: int, before: int, history_budget: int
) -> FitResult:
    messages = _flatten(exchanges)
    if dropped:
        messages = _with_omitted_note(messages, dropped)
    logger.info(
        "🧵 Fitted the replayed conversation from about %s to about %s tokens (budget %s): %s, dropped %s exchange(s)",
        before,
        estimate_prompt_tokens(messages),
        history_budget,
        ", ".join(levels),
        dropped,
    )
    return FitResult(messages=messages, levels=levels, dropped_exchanges=dropped)
