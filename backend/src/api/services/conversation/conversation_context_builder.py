"""Builds the model-facing message list for direct conversation turns."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ...core.models.models_registry import get_model
from ...core.models.reasoning.streaming_contract import resolve_generation_budget
from .conversation_models import Message, MessageRole

logger = logging.getLogger(__name__)

MODEL_FACING_ROLES = (MessageRole.SYSTEM, MessageRole.USER, MessageRole.ASSISTANT)
MINIMUM_TRIMMABLE_INPUT_BUDGET = 512
RUNTIME_PREAMBLE_HEADER = "Runtime context from Basil (not written by the user):"


@dataclass(frozen=True)
class ConversationExchange:
    """One user message and the assistant replies that followed it."""

    user: Optional[Message]
    assistants: Tuple[Message, ...]

    @property
    def anchor(self) -> Optional[Message]:
        return self.assistants[-1] if self.assistants else None


@dataclass(frozen=True)
class ConversationContextParts:
    """The stored system instructions plus the conversation grouped into exchanges, oldest first."""

    system_content: Optional[str]
    exchanges: Tuple[ConversationExchange, ...]


def model_display_name(model_id: Optional[str]) -> Optional[str]:
    """Return the registry display name for a model id, falling back to the id itself."""
    if not model_id:
        return None
    for candidate in (model_id, model_id.replace("/", "-")):
        try:
            config = get_model(candidate)
        except Exception:
            config = None
        if isinstance(config, dict):
            display_name = config.get("display_name")
            if isinstance(display_name, str) and display_name.strip():
                return display_name.strip()
    return model_id


def user_message_model_content(message: Message) -> str:
    """Prefer the composer's Markdown so formatting survives into the prompt."""
    metadata = message.metadata if isinstance(message.metadata, dict) else {}
    display_markdown = metadata.get("display_markdown")
    if isinstance(display_markdown, str) and display_markdown.strip():
        return display_markdown
    return message.content


def _current_model_id(llm_model: Any, requested_model_id: Optional[str]) -> Optional[str]:
    if isinstance(requested_model_id, str) and requested_model_id.strip():
        return requested_model_id.strip()
    model_name = getattr(llm_model, "model_name", None)
    if isinstance(model_name, str) and model_name.strip():
        return model_name.strip()
    return None


def resolve_current_model_name(llm_model: Any, requested_model_id: Optional[str]) -> Optional[str]:
    return model_display_name(_current_model_id(llm_model, requested_model_id))


def _local_time_description(now: datetime) -> str:
    local_now = now if now.tzinfo is not None else now.astimezone()
    hour = local_now.strftime("%I").lstrip("0") or "12"
    zone = local_now.strftime("%Z").strip()
    description = f"{local_now.strftime('%A, %B')} {local_now.day}, {local_now.year} at {hour}:{local_now.strftime('%M %p')}"
    return f"{description} {zone}" if zone else description


def build_runtime_preamble(current_model_name: Optional[str], now: datetime) -> str:
    lines = [RUNTIME_PREAMBLE_HEADER]
    if current_model_name:
        lines.append(
            f"- \"Basil\" is the name of the assistant app the user is talking to, not a language model. The language model writing this reply is \"{current_model_name}\". When the user asks which model you are, answer that you are {current_model_name}, running inside Basil."
        )
    lines.append(f"- The user's local date and time is {_local_time_description(now)}.")
    lines.append(
        "- Every turn, you receive this conversation's earlier user messages and assistant replies, oldest first. When the conversation is too long for your context window, the most recent exchanges still arrive in full, older exchanges arrive as a running brief and short summaries in this system message, and any that still do not fit are left out. If the user asks what context you receive, describe it that way."
    )
    lines.append(
        "- Earlier assistant replies in this conversation may have been written by other models; those replies are labeled \"[Earlier reply from <model>]\". Treat them as conversation history, and do not add such a label to your own reply."
    )
    lines.append(
        "- If an earlier reply in this conversation described its own identity incorrectly, do not repeat that description; this runtime context is authoritative."
    )
    return "\n".join(lines)


def split_conversation_exchanges(messages: Sequence[Message]) -> ConversationContextParts:
    """Group model-facing messages into exchanges; error rows and empty replies are dropped."""
    system_content: Optional[str] = None
    grouped: List[Tuple[Optional[Message], List[Message]]] = []
    for message in messages:
        if message.role not in MODEL_FACING_ROLES:
            continue
        if message.role == MessageRole.SYSTEM:
            if system_content is None and message.content.strip():
                system_content = message.content
            continue
        if message.role == MessageRole.USER:
            grouped.append((message, []))
            continue
        if not message.content.strip():
            continue
        if not grouped:
            grouped.append((None, []))
        grouped[-1][1].append(message)
    return ConversationContextParts(
        system_content=system_content,
        exchanges=tuple(
            ConversationExchange(user=user, assistants=tuple(assistants))
            for user, assistants in grouped
        ),
    )


def render_exchange_messages(
    exchange: ConversationExchange,
    current_model_name: Optional[str],
) -> List[Dict[str, Any]]:
    """Render one exchange as model-facing messages, labeling replies written by other models."""
    rendered: List[Dict[str, Any]] = []
    if exchange.user is not None:
        rendered.append({"role": "user", "content": user_message_model_content(exchange.user)})
    for assistant in exchange.assistants:
        content = assistant.content
        author_name = model_display_name(assistant.model_id)
        if author_name and current_model_name and author_name != current_model_name:
            content = f"[Earlier reply from {author_name}]\n{content}"
        rendered.append({"role": "assistant", "content": content})
    return rendered


def compose_base_system_message(system_content: Optional[str], preamble: str) -> str:
    return f"{system_content}\n\n{preamble}" if system_content else preamble


def build_conversation_model_messages(
    messages: Sequence[Message],
    *,
    llm_model: Any,
    requested_model_id: Optional[str],
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Convert stored conversation messages into the full, untrimmed list sent to the model."""
    current_model_name = resolve_current_model_name(llm_model, requested_model_id)
    preamble = build_runtime_preamble(current_model_name, now or datetime.now().astimezone())
    parts = split_conversation_exchanges(messages)
    turns = [
        rendered
        for exchange in parts.exchanges
        for rendered in render_exchange_messages(exchange, current_model_name)
    ]
    return [{"role": "system", "content": compose_base_system_message(parts.system_content, preamble)}, *turns]


def conversation_input_budget_tokens(llm_model: Any) -> Optional[int]:
    """Return a usable prompt budget, or None when the model profile cannot provide one."""
    try:
        budget = resolve_generation_budget(llm_model).input_budget_tokens
    except Exception:
        logger.debug("Conversation input budget unavailable", exc_info=True)
        return None
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < MINIMUM_TRIMMABLE_INPUT_BUDGET:
        return None
    return budget
