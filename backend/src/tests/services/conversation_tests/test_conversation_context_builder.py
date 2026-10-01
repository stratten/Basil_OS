from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api.services.conversation import conversation_context_builder as builder
from api.services.conversation.conversation_models import Message, MessageRole

EASTERN = timezone(timedelta(hours=-4), "EDT")
FIXED_NOW = datetime(2026, 9, 30, 8, 27, tzinfo=EASTERN)
REGISTRY = {
    "Qwen-qwen3-8b-instruct-q4km": {"display_name": "Qwen3-8B Instruct Q4_K_M"},
    "qwen3-coder-30b": {"display_name": "Qwen3 Coder 30B"},
}


def fake_get_model(model_id):
    return REGISTRY.get(model_id)


def message(message_id, role, content, model_id=None, metadata=None):
    return Message(id=message_id, content=content, role=role, model_id=model_id, metadata=metadata or {})


def build(messages, requested_model_id="Qwen/qwen3-8b-instruct-q4km"):
    with patch.object(builder, "get_model", side_effect=fake_get_model):
        return builder.build_conversation_model_messages(
            messages,
            llm_model=SimpleNamespace(model_name="ignored-model-name"),
            requested_model_id=requested_model_id,
            now=FIXED_NOW,
        )


def test_display_name_falls_back_from_slash_id_to_dash_id_and_then_raw_id():
    with patch.object(builder, "get_model", side_effect=fake_get_model):
        assert builder.model_display_name("Qwen/qwen3-8b-instruct-q4km") == "Qwen3-8B Instruct Q4_K_M"
        assert builder.model_display_name("unknown/model") == "unknown/model"
        assert builder.model_display_name(None) is None


def test_preamble_names_model_and_local_time_and_is_appended_to_system_message():
    result = build([
        message("s", MessageRole.SYSTEM, "You are Basil."),
        message("u", MessageRole.USER, "Who are you?"),
    ])
    assert result[0]["role"] == "system"
    assert result[0]["content"].startswith("You are Basil.\n\nRuntime context from Basil (not written by the user):")
    assert "\"Qwen3-8B Instruct Q4_K_M\"" in result[0]["content"]
    assert "Wednesday, September 30, 2026 at 8:27 AM EDT" in result[0]["content"]
    assert result[1] == {"role": "user", "content": "Who are you?"}


def test_preamble_becomes_the_system_message_when_none_is_stored():
    result = build([message("u", MessageRole.USER, "Hi")])
    assert result[0]["content"].startswith("Runtime context from Basil")
    assert [item["role"] for item in result] == ["system", "user"]


def test_only_first_system_message_is_kept():
    result = build([
        message("s1", MessageRole.SYSTEM, "First"),
        message("s2", MessageRole.SYSTEM, "Second"),
        message("u", MessageRole.USER, "Hi"),
    ])
    assert [item["role"] for item in result] == ["system", "user"]
    assert "Second" not in result[0]["content"]


def test_error_rows_and_empty_assistant_rows_are_dropped():
    result = build([
        message("u1", MessageRole.USER, "First"),
        message("e1", MessageRole.ERROR, "Error: model unavailable"),
        message("a1", MessageRole.ASSISTANT, "   "),
        message("u2", MessageRole.USER, "Second"),
    ])
    assert [item["content"] for item in result[1:]] == ["First", "Second"]


def test_user_turns_use_display_markdown_when_present():
    result = build([
        message("u1", MessageRole.USER, "Plain bold", metadata={"display_markdown": "Plain **bold**"}),
        message("u2", MessageRole.USER, "No markdown", metadata={"display_markdown": "   "}),
    ])
    assert result[1]["content"] == "Plain **bold**"
    assert result[2]["content"] == "No markdown"


def test_replies_from_other_models_are_attributed_and_own_replies_are_not():
    result = build([
        message("u1", MessageRole.USER, "Hi"),
        message("a1", MessageRole.ASSISTANT, "Coder reply", model_id="qwen3-coder-30b"),
        message("u2", MessageRole.USER, "Again"),
        message("a2", MessageRole.ASSISTANT, "Own reply", model_id="Qwen-qwen3-8b-instruct-q4km"),
        message("u3", MessageRole.USER, "Who answered?"),
    ])
    assert result[2]["content"] == "[Earlier reply from Qwen3 Coder 30B]\nCoder reply"
    assert result[4]["content"] == "Own reply"


def test_input_budget_guard_rejects_unusable_values():
    with patch.object(builder, "resolve_generation_budget", return_value=SimpleNamespace(input_budget_tokens=0)):
        assert builder.conversation_input_budget_tokens(MagicMock()) is None
    with patch.object(builder, "resolve_generation_budget", return_value=SimpleNamespace(input_budget_tokens=MagicMock())):
        assert builder.conversation_input_budget_tokens(MagicMock()) is None
    with patch.object(builder, "resolve_generation_budget", side_effect=RuntimeError("no profile")):
        assert builder.conversation_input_budget_tokens(MagicMock()) is None
    with patch.object(builder, "resolve_generation_budget", return_value=SimpleNamespace(input_budget_tokens=168000)):
        assert builder.conversation_input_budget_tokens(MagicMock()) == 168000


def test_split_groups_messages_into_exchanges_and_keeps_leading_replies():
    parts = builder.split_conversation_exchanges([
        message("s", MessageRole.SYSTEM, "System"),
        message("a0", MessageRole.ASSISTANT, "Greeting"),
        message("u1", MessageRole.USER, "First"),
        message("a1", MessageRole.ASSISTANT, "Reply one"),
        message("a1b", MessageRole.ASSISTANT, "Reply one, continued"),
        message("e1", MessageRole.ERROR, "Error"),
        message("u2", MessageRole.USER, "Second"),
    ])
    assert parts.system_content == "System"
    assert [(exchange.user.id if exchange.user else None, [reply.id for reply in exchange.assistants]) for exchange in parts.exchanges] == [
        (None, ["a0"]),
        ("u1", ["a1", "a1b"]),
        ("u2", []),
    ]
    assert parts.exchanges[1].anchor.id == "a1b"
    assert parts.exchanges[2].anchor is None


def test_preamble_describes_condensed_history():
    result = build([message("u", MessageRole.USER, "Hi")])
    assert "older exchanges arrive as a running brief and short summaries" in result[0]["content"]
