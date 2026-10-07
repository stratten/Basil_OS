"""Mark and find the current turn inside a conversation that carries earlier turns."""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

TURN_INPUT_KEY = "basil_turn_input"
CURRENT_REQUEST_MARKER = "Current request: "
RECAP_HEADER = "EARLIER IN THIS CONVERSATION (older messages condensed to fit the model's context window):"
RECAP_MAX_EXCHANGES = 8
RECAP_MAX_CHARS_PER_MESSAGE = 600
CLIPPED_SUFFIX = " (truncated)"


def message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "\n".join(part for part in parts if part)
    return "" if content is None else str(content)


def clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + CLIPPED_SUFFIX


def mark_turn_input(message: HumanMessage) -> HumanMessage:
    kwargs = dict(message.additional_kwargs or {})
    kwargs[TURN_INPUT_KEY] = True
    return message.model_copy(update={"additional_kwargs": kwargs})


def is_turn_input(message: BaseMessage) -> bool:
    return isinstance(message, HumanMessage) and bool((message.additional_kwargs or {}).get(TURN_INPUT_KEY))


def turn_input_index(messages: Sequence[BaseMessage]) -> Optional[int]:
    for index in range(len(messages) - 1, -1, -1):
        if is_turn_input(messages[index]):
            return index
    return None


def current_turn_messages(messages: Sequence[BaseMessage]) -> List[BaseMessage]:
    index = turn_input_index(messages)
    return list(messages[index:]) if index is not None else list(messages)


def turn_input_text(messages: Sequence[BaseMessage]) -> str:
    index = turn_input_index(messages)
    if index is not None:
        return message_text(messages[index].content)
    for message in messages:
        if isinstance(message, HumanMessage):
            return message_text(message.content)
    return ""


def request_text(content: Any) -> str:
    text = message_text(content)
    marker_at = text.rfind(CURRENT_REQUEST_MARKER)
    if marker_at < 0:
        return text.strip()
    return text[marker_at + len(CURRENT_REQUEST_MARKER):].strip()


def render_thread_recap(
    messages: Sequence[BaseMessage],
    *,
    max_exchanges: int = RECAP_MAX_EXCHANGES,
    max_chars: int = RECAP_MAX_CHARS_PER_MESSAGE,
) -> str:
    """Condense earlier turns into "User:" / "You:" lines; tool results are left out."""
    flagged = any(is_turn_input(message) for message in messages)
    exchanges: List[List[str]] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            if flagged and not is_turn_input(message):
                continue
            request = " ".join(request_text(message.content).split())
            exchanges.append([f"User: {clip_text(request, max_chars)}"])
        elif isinstance(message, AIMessage) and exchanges:
            names = [str(call.get("name") or "") for call in message.tool_calls or [] if call.get("name")]
            if names:
                exchanges[-1].append(f"You ran: {', '.join(names)}")
            text = " ".join(message_text(message.content).split())
            if text:
                exchanges[-1].append(f"You: {clip_text(text, max_chars)}")
    if not exchanges:
        return ""
    lines = [RECAP_HEADER]
    for exchange in exchanges[-max_exchanges:]:
        lines.extend(exchange)
    return "\n".join(lines)
