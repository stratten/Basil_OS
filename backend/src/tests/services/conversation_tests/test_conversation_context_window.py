from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from api.services.conversation import conversation_context_builder as builder
from api.services.conversation import conversation_context_window as window
from api.services.conversation import conversation_summary_contract as contract
from api.services.conversation.conversation_context_builder import split_conversation_exchanges
from api.services.conversation.conversation_exchange_summaries import (
    coverage_fingerprint_for,
    summary_coverage_entries,
)
from api.services.conversation.conversation_models import Message, MessageRole

EASTERN = timezone(timedelta(hours=-4), "EDT")
FIXED_NOW = datetime(2026, 9, 30, 8, 27, tzinfo=EASTERN)
BASE_TIME = datetime(2026, 9, 30, 12, 0)


def count(text):
    return len(text) // 4


def summary_metadata(user_text, assistant_text, text):
    return {
        contract.TURN_SUMMARY_METADATA_KEY: {
            "status": "completed",
            "text": text,
            "source_fingerprint": contract.exchange_fingerprint(user_text, assistant_text),
            "model_id": "model-a",
            "attempt_count": 1,
            "version": contract.SUMMARY_FORMAT_VERSION,
        }
    }


def build_messages(exchange_count=6, summarized=(), newest="Newest question"):
    messages = []
    for index in range(exchange_count):
        user_text = f"u{index} " + "x" * 397
        assistant_text = f"a{index} " + "y" * 397
        timestamp = BASE_TIME + timedelta(minutes=index)
        metadata = summary_metadata(user_text, assistant_text, f"Summary {index}") if index in summarized else {}
        messages.append(Message(id=f"u{index}", content=user_text, role=MessageRole.USER, timestamp=timestamp))
        messages.append(Message(id=f"a{index}", content=assistant_text, role=MessageRole.ASSISTANT, timestamp=timestamp, model_id="model-a", metadata=metadata))
    messages.append(Message(id="newest", content=newest, role=MessageRole.USER, timestamp=BASE_TIME + timedelta(minutes=exchange_count)))
    return messages


def fit(parts, budget, metadata=None, override=None):
    return window.fit_conversation_context(
        parts,
        base_system_message="BASE",
        current_model_name=None,
        conversation_metadata=metadata,
        newest_content_override=override,
        budget_tokens=budget,
        count_tokens=count,
        local_tz=EASTERN,
    )


def prefixes(result):
    return [item["content"][:2] for item in result[1:-1]]


def test_everything_verbatim_when_it_fits_or_no_budget_is_known():
    parts = split_conversation_exchanges(build_messages())
    unbounded = fit(parts, None)
    assert unbounded[0] == {"role": "system", "content": "BASE"}
    assert len(unbounded) == 14
    assert fit(parts, 100000) == unbounded


def test_override_replaces_the_newest_message_content():
    parts = split_conversation_exchanges(build_messages())
    override = [{"type": "text", "text": "describe"}, {"type": "image", "source": "data"}]
    assert fit(parts, None, override=override)[-1]["content"] is override


def test_older_exchanges_become_labeled_summaries_oldest_first():
    parts = split_conversation_exchanges(build_messages(summarized=(0, 1, 2, 3)))
    result = fit(parts, 900)
    system = result[0]["content"]
    assert system.startswith("BASE\n\n" + window.CONDENSED_CONTEXT_HEADER)
    assert window.SUMMARIES_HEADING in system
    expected_lines = [f"- [Wed, Sep 30, 8:0{index} AM] Summary {index}" for index in range(4)]
    positions = [system.index(line) for line in expected_lines]
    assert positions == sorted(positions)
    assert "not included at all" not in system
    assert prefixes(result) == ["u4", "a4", "u5", "a5"]
    assert result[-1] == {"role": "user", "content": "Newest question"}


def test_exchanges_without_summaries_are_counted_as_omitted():
    parts = split_conversation_exchanges(build_messages(summarized=(0, 2, 3)))
    system = fit(parts, 900)[0]["content"]
    assert "Summary 0" in system and "Summary 2" in system and "Summary 3" in system
    assert "1 older exchange is not included at all." in system


def test_valid_brief_replaces_the_summaries_it_covers():
    parts = split_conversation_exchanges(build_messages(summarized=(0, 1, 2, 3)))
    entries = summary_coverage_entries(parts.exchanges)
    brief = contract.ConversationBriefRecord(
        text="Brief of the first two exchanges.",
        covered_anchor_ids=tuple(entry.anchor_id for entry in entries[:2]),
        covered_fingerprint=coverage_fingerprint_for(entries[:2]),
        model_id="model-a",
    )
    system = fit(parts, 900, metadata={contract.CONVERSATION_BRIEF_METADATA_KEY: brief.to_metadata()})[0]["content"]
    assert f"{window.BRIEF_HEADING}\nBrief of the first two exchanges." in system
    assert "Summary 0" not in system and "Summary 1" not in system
    assert "Summary 2" in system and "Summary 3" in system
    assert system.index(window.BRIEF_HEADING) < system.index(window.SUMMARIES_HEADING)


def test_stale_brief_is_ignored():
    parts = split_conversation_exchanges(build_messages(summarized=(0, 1, 2, 3)))
    entries = summary_coverage_entries(parts.exchanges)
    stale = contract.ConversationBriefRecord(
        text="Stale brief.",
        covered_anchor_ids=tuple(entry.anchor_id for entry in entries[:2]),
        covered_fingerprint="stale",
        model_id="model-a",
    )
    system = fit(parts, 900, metadata={contract.CONVERSATION_BRIEF_METADATA_KEY: stale.to_metadata()})[0]["content"]
    assert window.BRIEF_HEADING not in system
    assert all(f"Summary {index}" in system for index in range(4))


def test_without_summaries_verbatim_uses_the_whole_remaining_budget():
    parts = split_conversation_exchanges(build_messages())
    result = fit(parts, 900)
    assert prefixes(result) == ["u3", "a3", "u4", "a4", "u5", "a5"]
    assert "3 older exchanges are not included at all." in result[0]["content"]
    assert window.SUMMARIES_HEADING not in result[0]["content"]


def test_oversized_newest_text_keeps_its_start_and_end():
    newest = "start " + "z" * 40000 + " end"
    parts = split_conversation_exchanges(build_messages(newest=newest))
    result = fit(parts, 900)
    content = result[-1]["content"]
    assert len(result) == 2
    assert window.TRIMMED_CONTENT_MARKER in content
    assert content.startswith("start ")
    assert content.endswith(" end")
    assert count(content) <= 900
    assert "6 older exchanges are not included at all." in result[0]["content"]


def test_oversized_list_content_is_never_cut():
    override = [{"type": "text", "text": "z" * 40000}]
    parts = split_conversation_exchanges(build_messages())
    result = fit(parts, 900, override=override)
    assert result[-1]["content"] is override


def test_time_label_treats_naive_timestamps_as_utc():
    assert window.exchange_time_label(datetime(2026, 9, 30, 12, 5), EASTERN) == "Wed, Sep 30, 8:05 AM"
    assert window.exchange_time_label(datetime(2026, 9, 30, 20, 5, tzinfo=EASTERN), EASTERN) == "Wed, Sep 30, 8:05 PM"


def test_token_counter_uses_exact_tokenizer_only_when_it_says_so():
    exact_model = SimpleNamespace(tokenizer=SimpleNamespace(exact_token_counts=True, encode=str.split))
    counter, exact = window.make_token_counter(exact_model)
    assert exact is True
    assert counter("three short words") == 3
    estimate_counter, estimate_exact = window.make_token_counter(SimpleNamespace(tokenizer=SimpleNamespace(encode=str.split)))
    assert estimate_exact is False
    assert estimate_counter is window.estimate_tokens


def test_wrapper_applies_safety_ratio_only_to_estimated_counts():
    captured = []

    def capture(parts, **kwargs):
        captured.append(kwargs["budget_tokens"])
        return []

    messages = build_messages(exchange_count=1)
    with patch.object(window, "conversation_input_budget_tokens", return_value=1000), patch.object(window, "fit_conversation_context", side_effect=capture):
        window.build_fitted_conversation_messages(messages, llm_model=SimpleNamespace(model_name="m"), requested_model_id=None, conversation_metadata={}, now=FIXED_NOW)
        window.build_fitted_conversation_messages(
            messages,
            llm_model=SimpleNamespace(model_name="m", tokenizer=SimpleNamespace(exact_token_counts=True, encode=str.split)),
            requested_model_id=None,
            conversation_metadata={},
            now=FIXED_NOW,
        )
    assert captured == [900, 1000]


def test_wrapper_matches_the_full_builder_when_no_budget_is_known():
    registry = {"Qwen-qwen3-8b-instruct-q4km": {"display_name": "Qwen3-8B Instruct Q4_K_M"}, "qwen3-coder-30b": {"display_name": "Qwen3 Coder 30B"}}
    messages = [
        Message(id="s", content="You are Basil.", role=MessageRole.SYSTEM),
        Message(id="u1", content="Hi", role=MessageRole.USER),
        Message(id="a1", content="Coder reply", role=MessageRole.ASSISTANT, model_id="qwen3-coder-30b"),
        Message(id="u2", content="Again", role=MessageRole.USER, metadata={"display_markdown": "**Again**"}),
    ]
    model = SimpleNamespace(model_name="ignored")
    with patch.object(builder, "get_model", side_effect=registry.get), patch.object(window, "conversation_input_budget_tokens", return_value=None):
        fitted = window.build_fitted_conversation_messages(messages, llm_model=model, requested_model_id="Qwen/qwen3-8b-instruct-q4km", conversation_metadata={}, now=FIXED_NOW)
        full = builder.build_conversation_model_messages(messages, llm_model=model, requested_model_id="Qwen/qwen3-8b-instruct-q4km", now=FIXED_NOW)
    assert fitted == full
    assert fitted[2]["content"] == "[Earlier reply from Qwen3 Coder 30B]\nCoder reply"
