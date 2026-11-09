"""Summarize the older part of a long agent run so the run can continue inside the model's context window.

The summary is a request-only copy, like the elision of older tool results beside it: the run's own message history is never rewritten. The kept head is the current turn's request, which receives the summary, and the kept tail is the newest messages, starting at an assistant message so a tool call is never separated from its results. The full text of what was condensed is saved in the stored-result store so the agent can search it for an exact value.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from api.core.logging.api_logger import api_logger

from .context_window_budget import CHARS_PER_TOKEN_ESTIMATE
from .conversation_turns import clip_text, message_text, turn_input_index

logger = api_logger.getChild("conversation_summary")

SUMMARY_TRIGGER_FRACTION = 0.7
SUMMARY_TRIGGER_CAP_TOKENS = 250_000
KEEP_RECENT_MESSAGES = 8
MIN_MESSAGES_TO_SUMMARIZE = 6
MAX_SUMMARIES_PER_RUN = 6
TRANSCRIPT_RESULT_CHARS = 1_500
TRANSCRIPT_TEXT_CHARS = 1_500
TRANSCRIPT_ARGS_CHARS = 400
TRANSCRIPT_BUDGET_SHARE = 0.4
MIN_TRANSCRIPT_CHARS = 2_000
HISTORY_FILE_MAX_CHARS = 4_000_000
SUMMARY_MAX_CHARS = 8_000
UNKNOWN_BUDGET_TRANSCRIPT_CHARS = 24_000
SUMMARY_HEADER = "PROGRESS SO FAR (the earlier steps of this same task, condensed to fit the model's context window):"

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

SUMMARY_PROMPT = """You are condensing the earlier part of an AI agent's work on one task, so the agent can carry on from a short record instead of the full history.

{previous_section}Steps to condense:
{transcript}

Write the record as plain text under 600 words, in these sections: GOAL (what the user asked for and any instructions or limits they gave), DONE (what was completed, with exact names, ids, file paths, and values), FINDINGS (facts the agent will need again, quoted exactly), PROBLEMS (what failed or was refused, and what was tried), NEXT (what remains to be done). Use only what is in the steps. Do not guess, do not call tools, and do not add anything that is not there."""


@dataclass(frozen=True)
class ConversationSummary:
    """A saved record of the steps before a cut, and what it takes to apply it again to a longer history."""

    text: str
    head_end: int
    cut: int
    boundary: str
    stored_result_id: Optional[str] = None
    messages_covered: int = 0


def summary_trigger_tokens(prompt_budget_tokens: Optional[int]) -> Optional[int]:
    """The prompt size at which a summary is made, or None when the run's budget is unknown."""
    if not isinstance(prompt_budget_tokens, int) or isinstance(prompt_budget_tokens, bool) or prompt_budget_tokens <= 0:
        return None
    return max(1, min(int(prompt_budget_tokens * SUMMARY_TRIGGER_FRACTION), SUMMARY_TRIGGER_CAP_TOKENS))


def head_end_index(messages: Sequence[BaseMessage]) -> Optional[int]:
    """One past the current turn's request message (or the first user message), or None when there is none."""
    index = turn_input_index(messages)
    if index is None:
        index = next((position for position, message in enumerate(messages) if isinstance(message, HumanMessage)), None)
    return None if index is None else index + 1


def choose_cut(messages: Sequence[BaseMessage], start: int) -> Optional[int]:
    """Where the kept newest messages begin: an assistant message, with enough older messages after start to be worth condensing."""
    cut = len(messages) - KEEP_RECENT_MESSAGES
    while cut > start and not isinstance(messages[cut], AIMessage):
        cut -= 1
    return cut if cut - start >= MIN_MESSAGES_TO_SUMMARIZE else None


def _fingerprint(message: BaseMessage) -> str:
    identity = getattr(message, "tool_call_id", None) or getattr(message, "id", None) or ""
    raw = f"{type(message).__name__}|{identity}|{message_text(message.content)[:200]}"
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def _summary_block(summary: ConversationSummary) -> str:
    footer = (
        f"\nThe full text of these earlier steps, with every tool result in full, is saved as {summary.stored_result_id}. "
        "If you need an exact value that this record leaves out, use the stored_result tool (action search or read) on it instead of repeating the work."
        if summary.stored_result_id
        else ""
    )
    return f"{SUMMARY_HEADER}\n{summary.text}{footer}"


def _merged_head(head: BaseMessage, summary: ConversationSummary) -> BaseMessage:
    block = _summary_block(summary)
    content = head.content
    if isinstance(content, list):
        merged: Any = [*content, {"type": "text", "text": f"\n\n{block}"}]
    else:
        merged = f"{message_text(content)}\n\n{block}"
    return head.model_copy(update={"content": merged})


def apply_summary(messages: List[BaseMessage], summary: ConversationSummary) -> List[BaseMessage]:
    """The history with the steps before the cut replaced by the record, or the history unchanged when it no longer matches the summary."""
    if (
        summary.cut > len(messages)
        or summary.head_end < 1
        or head_end_index(messages) != summary.head_end
        or _fingerprint(messages[summary.cut - 1]) != summary.boundary
    ):
        return messages
    head = messages[summary.head_end - 1]
    return [*messages[: summary.head_end - 1], _merged_head(head, summary), *messages[summary.cut:]]


def _limit(text: str, limit: Optional[int]) -> str:
    return text if limit is None else clip_text(text, limit)


def _call_text(call: dict, limit: Optional[int]) -> str:
    arguments = json.dumps(call.get("args") or {}, ensure_ascii=False, default=str)
    return f"{call.get('name') or 'tool'}({_limit(arguments, limit)})"


def render_message(message: BaseMessage, *, clipped: bool) -> str:
    """One message as a labeled block of text, clipped for the summarizer or in full for the saved history."""
    text = message_text(message.content).strip()
    if isinstance(message, ToolMessage):
        return f"[tool result: {message.name or 'tool'}]\n{_limit(text, TRANSCRIPT_RESULT_CHARS if clipped else None)}"
    if isinstance(message, AIMessage):
        calls = "; ".join(_call_text(call, TRANSCRIPT_ARGS_CHARS if clipped else None) for call in message.tool_calls or [])
        pieces = [piece for piece in (_limit(text, TRANSCRIPT_TEXT_CHARS if clipped else None), f"called: {calls}" if calls else "") if piece]
        return "[assistant]\n" + "\n".join(pieces) if pieces else "[assistant]"
    label = "user" if isinstance(message, HumanMessage) else "system" if isinstance(message, SystemMessage) else type(message).__name__
    return f"[{label}]\n{_limit(text, TRANSCRIPT_TEXT_CHARS if clipped else None)}"


def full_transcript(messages: Sequence[BaseMessage]) -> str:
    """Every message in full, for the saved history file."""
    text = "\n\n".join(render_message(message, clipped=False) for message in messages)
    if len(text) > HISTORY_FILE_MAX_CHARS:
        text = text[:HISTORY_FILE_MAX_CHARS] + "\n\n[The rest of this history was left out because it is very long.]"
    return text


def compact_transcript(messages: Sequence[BaseMessage], max_chars: int) -> str:
    """The newest messages that fit max_chars, each clipped, with a note when older ones were left out."""
    entries = [render_message(message, clipped=True) for message in messages]
    kept: List[str] = []
    size = 0
    for entry in reversed(entries):
        if kept and size + len(entry) > max_chars:
            break
        kept.append(entry)
        size += len(entry) + 2
    kept.reverse()
    omitted = len(entries) - len(kept)
    note = f"[{omitted} earlier step(s) are not shown here.]\n\n" if omitted else ""
    return note + "\n\n".join(kept)


def _clean_reply(content: Any) -> str:
    text = _THINK_BLOCK.sub("", message_text(content)).strip()
    return text[:SUMMARY_MAX_CHARS]


def _save_history(messages: Sequence[BaseMessage]) -> Optional[str]:
    try:
        from ...tools.internal_basil_tools.stored_result.store import save_result

        stored = save_result(full_transcript(messages))
        return stored["result_id"] if stored else None
    except Exception as error:
        logger.warning("The condensed history could not be saved: %s", error)
        return None


async def build_summary(
    model: Any,
    messages: Sequence[BaseMessage],
    *,
    head_end: int,
    cut: int,
    previous: Optional[ConversationSummary],
    prompt_budget_tokens: Optional[int],
) -> Optional[ConversationSummary]:
    """Ask the model for a record of the steps between the kept head and the cut, or None when it returns nothing."""
    start = previous.cut if previous is not None else head_end
    budget = prompt_budget_tokens if isinstance(prompt_budget_tokens, int) and prompt_budget_tokens > 0 else 0
    max_chars = max(MIN_TRANSCRIPT_CHARS, int(budget * TRANSCRIPT_BUDGET_SHARE * CHARS_PER_TOKEN_ESTIMATE)) if budget else UNKNOWN_BUDGET_TRANSCRIPT_CHARS
    previous_section = (
        f"The record so far, which you must carry forward and extend with the steps below:\n{previous.text}\n\n" if previous is not None else ""
    )
    prompt = SUMMARY_PROMPT.format(
        previous_section=previous_section,
        transcript=compact_transcript(messages[start:cut], max_chars),
    )
    reply = await model.ainvoke([HumanMessage(content=prompt)])
    text = _clean_reply(getattr(reply, "content", reply))
    if not text:
        return None
    return ConversationSummary(
        text=text,
        head_end=head_end,
        cut=cut,
        boundary=_fingerprint(messages[cut - 1]),
        stored_result_id=_save_history(messages[head_end:cut]),
        messages_covered=cut - head_end,
    )
