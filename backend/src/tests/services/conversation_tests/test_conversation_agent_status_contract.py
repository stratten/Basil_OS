import pytest

from api.services.conversation.conversation_agent_status_contract import (
    MAX_CONVERSATION_AGENT_STATUS_CHARS,
    build_conversation_agent_status_payload,
)
from api.services.conversation.conversation_turn_contract import ConversationTurnLifecycle


def test_status_payload_is_constrained_and_truncated() -> None:
    payload = build_conversation_agent_status_payload(
        conversation_id="conversation-1",
        placeholder_message_id="assistant-1",
        agent_task_id="task-1",
        lifecycle=ConversationTurnLifecycle.RUNNING,
        status_text="s" * (MAX_CONVERSATION_AGENT_STATUS_CHARS + 1),
        terminal_outcome="o" * (MAX_CONVERSATION_AGENT_STATUS_CHARS + 1),
    )

    assert payload == {
        "event_type": "conversation_agent_status",
        "conversation_id": "conversation-1",
        "placeholder_message_id": "assistant-1",
        "agent_task_id": "task-1",
        "lifecycle": "running",
        "status_text": "s" * MAX_CONVERSATION_AGENT_STATUS_CHARS,
        "terminal_outcome": "o" * MAX_CONVERSATION_AGENT_STATUS_CHARS,
        "deep_link_id": "task-1",
        "requires_user_attention": False,
    }


def test_status_payload_rejects_missing_identifiers_and_omits_non_string_text() -> None:
    try:
        build_conversation_agent_status_payload(
            conversation_id="",
            placeholder_message_id="assistant-1",
            agent_task_id="task-1",
            lifecycle=ConversationTurnLifecycle.RUNNING,
            status_text=None,
            terminal_outcome=None,
        )
    except ValueError as exc:
        assert str(exc) == "conversation_id must be a non-empty string"
    else:
        raise AssertionError("Expected empty conversation ID to be rejected")

    payload = build_conversation_agent_status_payload(
        conversation_id="conversation-1",
        placeholder_message_id="assistant-1",
        agent_task_id="task-1",
        lifecycle=ConversationTurnLifecycle.COMPLETED,
        status_text=None,
        terminal_outcome=None,
    )

    assert payload["status_text"] is None
    assert payload["terminal_outcome"] is None
    assert set(payload) == {
        "event_type",
        "conversation_id",
        "placeholder_message_id",
        "agent_task_id",
        "lifecycle",
        "status_text",
        "terminal_outcome",
        "deep_link_id",
        "requires_user_attention",
    }


def test_status_payload_includes_valid_state_extensions_only_when_provided() -> None:
    payload = build_conversation_agent_status_payload(
        conversation_id="conversation-1",
        placeholder_message_id="assistant-1",
        agent_task_id="task-1",
        lifecycle=ConversationTurnLifecycle.RUNNING,
        status_text="Agent task is working.",
        terminal_outcome=None,
        agent_status="processing",
        narration_state="ready",
    )

    assert payload["agent_status"] == "processing"
    assert payload["narration_state"] == "ready"


@pytest.mark.parametrize("field_name", ["agent_status", "narration_state"])
def test_status_payload_rejects_invalid_optional_state(field_name: str) -> None:
    kwargs = {field_name: ""}

    with pytest.raises(ValueError, match=f"{field_name} must be a non-empty string when provided"):
        build_conversation_agent_status_payload(
            conversation_id="conversation-1",
            placeholder_message_id="assistant-1",
            agent_task_id="task-1",
            lifecycle=ConversationTurnLifecycle.RUNNING,
            status_text=None,
            terminal_outcome=None,
            **kwargs,
        )


def test_status_payload_includes_attention_id_when_attention_is_required() -> None:
    payload = build_conversation_agent_status_payload(
        conversation_id="conversation-1",
        placeholder_message_id="assistant-1",
        agent_task_id="task-1",
        lifecycle=ConversationTurnLifecycle.RUNNING,
        status_text="Agent task needs your input.",
        terminal_outcome=None,
        requires_user_attention=True,
        attention_id="checkpoint-1",
    )

    assert payload["requires_user_attention"] is True
    assert payload["attention_id"] == "checkpoint-1"


def test_status_payload_preserves_multiple_attention_ids() -> None:
    payload = build_conversation_agent_status_payload(
        conversation_id="conversation-1",
        placeholder_message_id="assistant-1",
        agent_task_id="task-1",
        lifecycle=ConversationTurnLifecycle.RUNNING,
        status_text="Agent task needs your input.",
        terminal_outcome=None,
        requires_user_attention=True,
        attention_ids=["approval-1", "approval-2", "approval-1"],
    )

    assert payload["attention_id"] == "approval-1"
    assert payload["attention_ids"] == ["approval-1", "approval-2"]


@pytest.mark.parametrize(
    ("requires_user_attention", "attention_id", "expected_message"),
    [
        (True, None, "requires_user_attention=True requires attention_id"),
        (False, "checkpoint-1", "attention_id requires requires_user_attention=True"),
        ("yes", "checkpoint-1", "requires_user_attention must be a boolean"),
        (True, "", "attention_id must be a non-empty string when provided"),
    ],
)
def test_status_payload_rejects_invalid_attention_fields(
    requires_user_attention,
    attention_id,
    expected_message: str,
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        build_conversation_agent_status_payload(
            conversation_id="conversation-1",
            placeholder_message_id="assistant-1",
            agent_task_id="task-1",
            lifecycle=ConversationTurnLifecycle.RUNNING,
            status_text=None,
            terminal_outcome=None,
            requires_user_attention=requires_user_attention,
            attention_id=attention_id,
        )
