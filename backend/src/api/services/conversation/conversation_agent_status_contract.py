"""Constrained websocket contract for Conversation-linked Agent Task status."""

from __future__ import annotations

from typing import Any, Final

from .conversation_turn_contract import ConversationTurnLifecycle


MAX_CONVERSATION_AGENT_STATUS_CHARS: Final = 240


def truncate_conversation_agent_status_text(value: str | None) -> str | None:
    """Return safe bounded status text without coercing arbitrary values."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized[:MAX_CONVERSATION_AGENT_STATUS_CHARS] or None


def _optional_nonblank_text(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string when provided")
    return value.strip()


def _normalize_attention_ids(
    attention_id: str | None,
    attention_ids: list[str] | None,
) -> list[str]:
    normalized = []
    normalized_attention_id = _optional_nonblank_text("attention_id", attention_id)
    if normalized_attention_id is not None:
        normalized.append(normalized_attention_id)
    for value in attention_ids or []:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("attention_ids must contain only non-empty strings")
        value = value.strip()
        if value not in normalized:
            normalized.append(value)
    return normalized


def build_conversation_agent_status_payload(
    *,
    conversation_id: str,
    placeholder_message_id: str,
    agent_task_id: str,
    lifecycle: ConversationTurnLifecycle,
    status_text: str | None,
    terminal_outcome: str | None,
    agent_status: str | None = None,
    narration_state: str | None = None,
    requires_user_attention: bool = False,
    attention_id: str | None = None,
    attention_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build the public event without exposing Agent Task internals."""
    for field_name, value in {
        "conversation_id": conversation_id,
        "placeholder_message_id": placeholder_message_id,
        "agent_task_id": agent_task_id,
    }.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")
    if not isinstance(requires_user_attention, bool):
        raise ValueError("requires_user_attention must be a boolean")
    normalized_agent_status = _optional_nonblank_text("agent_status", agent_status)
    normalized_narration_state = _optional_nonblank_text(
        "narration_state",
        narration_state,
    )
    normalized_attention_ids = _normalize_attention_ids(attention_id, attention_ids)
    if requires_user_attention and not normalized_attention_ids:
        raise ValueError("requires_user_attention=True requires attention_id")
    if normalized_attention_ids and not requires_user_attention:
        if attention_ids is None:
            raise ValueError("attention_id requires requires_user_attention=True")
        raise ValueError("attention_ids require requires_user_attention=True")
    payload = {
        "event_type": "conversation_agent_status",
        "conversation_id": conversation_id,
        "placeholder_message_id": placeholder_message_id,
        "agent_task_id": agent_task_id,
        "lifecycle": lifecycle.value,
        "status_text": truncate_conversation_agent_status_text(status_text),
        "terminal_outcome": truncate_conversation_agent_status_text(terminal_outcome),
        "deep_link_id": agent_task_id,
        "requires_user_attention": requires_user_attention,
    }
    if normalized_agent_status is not None:
        payload["agent_status"] = normalized_agent_status
    if normalized_narration_state is not None:
        payload["narration_state"] = normalized_narration_state
    if normalized_attention_ids:
        payload["attention_id"] = normalized_attention_ids[0]
        if len(normalized_attention_ids) > 1:
            payload["attention_ids"] = normalized_attention_ids
    return payload
