from api.services.conversation import conversation_summary_contract as contract
from api.services.conversation.conversation_context_builder import split_conversation_exchanges
from api.services.conversation.conversation_exchange_summaries import (
    coverage_fingerprint_for,
    current_exchange_summary,
    exchange_needs_summary,
    is_summarizable_exchange,
    prior_failed_attempts,
    summary_coverage_entries,
    valid_conversation_brief,
)
from api.services.conversation.conversation_models import Message, MessageRole
from api.services.conversation.conversation_turn_contract import CONVERSATION_TURN_METADATA_KEY


def message(message_id, role, content, model_id=None, metadata=None):
    return Message(id=message_id, content=content, role=role, model_id=model_id, metadata=metadata or {})


def summary_metadata(user_text, assistant_text, *, status="completed", text="Summary.", attempt_count=1, fingerprint=None):
    return {
        contract.TURN_SUMMARY_METADATA_KEY: {
            "status": status,
            "text": text if status == "completed" else None,
            "source_fingerprint": fingerprint or contract.exchange_fingerprint(user_text, assistant_text),
            "model_id": "model-a",
            "attempt_count": attempt_count,
            "version": contract.SUMMARY_FORMAT_VERSION,
        }
    }


def exchange_for(assistant_metadata=None, model_id="model-a", user_text="Question", assistant_text="Answer"):
    parts = split_conversation_exchanges([
        message("u", MessageRole.USER, user_text),
        message("a", MessageRole.ASSISTANT, assistant_text, model_id=model_id, metadata=assistant_metadata),
    ])
    return parts.exchanges[0]


def test_exchange_fingerprint_is_stable_and_text_sensitive():
    assert contract.exchange_fingerprint("u", "a") == contract.exchange_fingerprint("u", "a")
    assert contract.exchange_fingerprint("u", "a") != contract.exchange_fingerprint("u", "b")
    assert contract.exchange_fingerprint("ua", "") != contract.exchange_fingerprint("u", "a")


def test_parse_turn_summary_rejects_malformed_records():
    valid = summary_metadata("u", "a")
    assert contract.parse_turn_summary(valid).text == "Summary."
    for broken in (
        None,
        {},
        {contract.TURN_SUMMARY_METADATA_KEY: "text"},
        {contract.TURN_SUMMARY_METADATA_KEY: {**valid[contract.TURN_SUMMARY_METADATA_KEY], "status": "unknown"}},
        {contract.TURN_SUMMARY_METADATA_KEY: {**valid[contract.TURN_SUMMARY_METADATA_KEY], "text": "   "}},
        {contract.TURN_SUMMARY_METADATA_KEY: {**valid[contract.TURN_SUMMARY_METADATA_KEY], "version": True}},
        {contract.TURN_SUMMARY_METADATA_KEY: {**valid[contract.TURN_SUMMARY_METADATA_KEY], "attempt_count": -1}},
        {contract.TURN_SUMMARY_METADATA_KEY: {**valid[contract.TURN_SUMMARY_METADATA_KEY], "source_fingerprint": ""}},
    ):
        assert contract.parse_turn_summary(broken) is None


def test_failed_record_parses_without_text():
    record = contract.parse_turn_summary(summary_metadata("u", "a", status="failed", attempt_count=2))
    assert record.status == contract.TurnSummaryStatus.FAILED
    assert record.text is None
    assert record.attempt_count == 2


def test_parse_conversation_brief_rejects_malformed_records():
    valid = contract.ConversationBriefRecord(
        text="Brief.",
        covered_anchor_ids=("a1",),
        covered_fingerprint="f",
        model_id="model-a",
    ).to_metadata()
    assert contract.parse_conversation_brief({contract.CONVERSATION_BRIEF_METADATA_KEY: valid}).covered_anchor_ids == ("a1",)
    for broken in ({**valid, "covered_anchor_ids": []}, {**valid, "covered_anchor_ids": ["a1", ""]}, {**valid, "text": ""}, {**valid, "covered_fingerprint": None}):
        assert contract.parse_conversation_brief({contract.CONVERSATION_BRIEF_METADATA_KEY: broken}) is None
    assert contract.parse_conversation_brief(None) is None


def test_current_summary_requires_completed_status_and_matching_text():
    assert current_exchange_summary(exchange_for(summary_metadata("Question", "Answer"))).text == "Summary."
    assert current_exchange_summary(exchange_for(summary_metadata("Question", "Old answer"))) is None
    assert current_exchange_summary(exchange_for(summary_metadata("Question", "Answer", status="failed"))) is None
    assert current_exchange_summary(exchange_for()) is None


def test_summarizable_exchanges_are_completed_direct_turns_with_a_model():
    direct_completed = {CONVERSATION_TURN_METADATA_KEY: {"route": "direct", "lifecycle": "completed"}}
    direct_running = {CONVERSATION_TURN_METADATA_KEY: {"route": "direct", "lifecycle": "running"}}
    agent_task = {CONVERSATION_TURN_METADATA_KEY: {"route": "agent_task", "lifecycle": "completed"}}
    malformed = {CONVERSATION_TURN_METADATA_KEY: {"route": "nonsense", "lifecycle": "completed"}}
    assert is_summarizable_exchange(exchange_for()) is True
    assert is_summarizable_exchange(exchange_for(direct_completed)) is True
    assert is_summarizable_exchange(exchange_for(direct_running)) is False
    assert is_summarizable_exchange(exchange_for(agent_task)) is False
    assert is_summarizable_exchange(exchange_for(malformed)) is False
    assert is_summarizable_exchange(exchange_for(model_id=None)) is False
    leading_reply = split_conversation_exchanges([message("a", MessageRole.ASSISTANT, "Hi", model_id="model-a")]).exchanges[0]
    assert is_summarizable_exchange(leading_reply) is False


def test_needs_summary_honors_fingerprint_and_retry_limit():
    assert exchange_needs_summary(exchange_for()) is True
    assert exchange_needs_summary(exchange_for(summary_metadata("Question", "Answer"))) is False
    assert exchange_needs_summary(exchange_for(summary_metadata("Question", "Edited"))) is True
    limit = contract.MAX_TURN_SUMMARY_ATTEMPTS
    assert exchange_needs_summary(exchange_for(summary_metadata("Question", "Answer", status="failed", attempt_count=limit - 1))) is True
    assert exchange_needs_summary(exchange_for(summary_metadata("Question", "Answer", status="failed", attempt_count=limit))) is False
    exhausted = exchange_for(summary_metadata("Question", "Answer", status="failed", attempt_count=limit))
    fingerprint = contract.exchange_fingerprint("Question", "Answer")
    assert prior_failed_attempts(exhausted, fingerprint) == limit
    assert prior_failed_attempts(exhausted, "other") == 0


def _summarized_parts(count):
    messages = []
    for index in range(count):
        user_text = f"Question {index}"
        assistant_text = f"Answer {index}"
        messages.append(message(f"u{index}", MessageRole.USER, user_text))
        messages.append(message(f"a{index}", MessageRole.ASSISTANT, assistant_text, model_id="model-a", metadata=summary_metadata(user_text, assistant_text, text=f"Summary {index}")))
    return split_conversation_exchanges(messages)


def _brief_metadata(entries, fingerprint=None):
    record = contract.ConversationBriefRecord(
        text="Brief.",
        covered_anchor_ids=tuple(entry.anchor_id for entry in entries),
        covered_fingerprint=fingerprint or coverage_fingerprint_for(entries),
        model_id="model-a",
    )
    return {contract.CONVERSATION_BRIEF_METADATA_KEY: record.to_metadata()}


def test_brief_is_valid_only_for_an_unchanged_ordered_prefix():
    parts = _summarized_parts(4)
    entries = summary_coverage_entries(parts.exchanges)
    assert [entry.anchor_id for entry in entries] == ["a0", "a1", "a2", "a3"]
    assert valid_conversation_brief(parts.exchanges, _brief_metadata(entries[:2])).text == "Brief."
    assert valid_conversation_brief(parts.exchanges, _brief_metadata([entries[1], entries[0]])) is None
    assert valid_conversation_brief(parts.exchanges, _brief_metadata(entries[:2], fingerprint="stale")) is None
    assert valid_conversation_brief(_summarized_parts(1).exchanges, _brief_metadata(entries[:2])) is None
    assert valid_conversation_brief(parts.exchanges, {}) is None
