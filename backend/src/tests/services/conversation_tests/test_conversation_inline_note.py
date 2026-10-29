from types import SimpleNamespace
from unittest.mock import patch

from api.services.conversation import conversation_context_window as window
from api.services.conversation import conversation_summary_contract as contract
from api.services.conversation.conversation_inline_note import (
    INLINE_NOTE_INSTRUCTION,
    INLINE_NOTE_REMINDER,
    InlineNoteStreamFilter,
    append_inline_note_reminder,
    build_inline_turn_summary,
    split_inline_note,
)
from api.services.conversation.conversation_models import Message, MessageRole


def run(chunks):
    note_filter = InlineNoteStreamFilter()
    visible = "".join(note_filter.feed(chunk) for chunk in chunks)
    outcome = note_filter.finish()
    return visible + outcome.visible_tail, outcome.note


def test_note_split_across_single_characters_is_withheld_and_captured():
    text = "Answer text.\n<basil_note>Asked X; answered Y.</basil_note>"
    visible, note = run(list(text))
    assert visible == "Answer text.\n"
    assert note == "Asked X; answered Y."


def test_marker_mentioned_inside_reasoning_is_neutralized_but_does_not_start_a_note():
    text = "<think>I will add <basil_note> later</think>Answer<basil_note>N</basil_note>"
    chunks = [text[index:index + 3] for index in range(0, len(text), 3)]
    visible, note = run(chunks)
    assert visible == "<think>I will add <recap> later</think>Answer"
    assert note == "N"


def test_reasoning_term_split_across_every_chunk_boundary_is_replaced():
    text = "<think>Remember to add the basil_note at the end.</think>Reply."
    for size in range(1, 12):
        chunks = [text[index:index + size] for index in range(0, len(text), size)]
        assert run(chunks) == ("<think>Remember to add the recap at the end.</think>Reply.", None)


def test_unclosed_reasoning_tail_is_neutralized_and_answer_text_is_untouched():
    assert run(["<think>plan the basil_", "note"]) == ("<think>plan the recap", None)
    assert run(["The tag basil_note in an answer stays."]) == ("The tag basil_note in an answer stays.", None)


def test_partial_marker_is_held_then_released_when_it_is_not_a_marker():
    note_filter = InlineNoteStreamFilter()
    assert note_filter.feed("a <") == "a "
    assert note_filter.feed("b>") == "<b>"
    assert note_filter.feed("end <th") == "end "
    outcome = note_filter.finish()
    assert outcome.visible_tail == "<th"
    assert outcome.note is None


def test_text_after_the_closing_marker_is_discarded():
    assert run(["A<basil_note>N</basil_note>extra"]) == ("A", "N")


def test_unclosed_or_empty_note_yields_no_summary():
    assert run(["Answer<basil_note>cut off mid"]) == ("Answer", None)
    assert run(["Answer<basil_note>   </basil_note>"]) == ("Answer", None)


def test_note_without_any_answer_is_released_as_the_reply():
    assert run(["<basil_note>Only a note</basil_note>"]) == ("Only a note", None)
    assert run(["<think>reasoning</think><basil_note>Only a note</basil_note>"]) == ("<think>reasoning</think>Only a note", None)


def test_text_without_markers_is_unchanged():
    assert run(["Plain ", "reply with <b>bold</b> HTML."]) == ("Plain reply with <b>bold</b> HTML.", None)


def test_split_inline_note_for_complete_responses():
    split = split_inline_note("Reply.\n<basil_note>Note.</basil_note>")
    assert split.reply == "Reply."
    assert split.note == "Note."
    assert split_inline_note("No note here.").reply == "No note here."


def test_build_inline_turn_summary_matches_the_stored_reply():
    metadata = build_inline_turn_summary("Note.", user_text="Question", reply_text="Reply.", model_id="model-a")
    record = contract.parse_turn_summary({contract.TURN_SUMMARY_METADATA_KEY: metadata})
    assert record.status == contract.TurnSummaryStatus.COMPLETED
    assert record.text == "Note."
    assert record.source_fingerprint == contract.exchange_fingerprint("Question", "Reply.")
    assert record.model_id == "model-a"
    assert build_inline_turn_summary(None, user_text="Question", reply_text="Reply.", model_id="model-a") is None
    assert build_inline_turn_summary("Note.", user_text="Question", reply_text="  ", model_id="model-a") is None


def _messages(characters_per_message):
    return [
        Message(id="u1", content="q" * characters_per_message, role=MessageRole.USER),
        Message(id="a1", content="r" * characters_per_message, role=MessageRole.ASSISTANT),
        Message(id="u2", content="Newest", role=MessageRole.USER),
    ]


def test_instruction_is_added_only_once_the_conversation_is_eligible():
    model = SimpleNamespace(model_name="m")
    with patch.object(window, "conversation_input_budget_tokens", return_value=None):
        short = window.build_fitted_conversation_messages(_messages(100), llm_model=model, requested_model_id=None, conversation_metadata={})
        long = window.build_fitted_conversation_messages(_messages(9000), llm_model=model, requested_model_id=None, conversation_metadata={})
    assert INLINE_NOTE_INSTRUCTION not in short[0]["content"]
    assert short[-1]["content"] == "Newest"
    assert long[0]["content"].endswith(INLINE_NOTE_INSTRUCTION)
    assert long[-1]["content"] == f"Newest\n\n{INLINE_NOTE_REMINDER}"
    assert all(INLINE_NOTE_REMINDER not in str(message["content"]) for message in long[:-1])


def test_reminder_survives_trimming_of_an_oversized_newest_message():
    messages = [
        Message(id="u1", content="q" * 9000, role=MessageRole.USER),
        Message(id="a1", content="r" * 9000, role=MessageRole.ASSISTANT),
        Message(id="u2", content="n" * 40000, role=MessageRole.USER),
    ]
    model = SimpleNamespace(model_name="m")
    with patch.object(window, "conversation_input_budget_tokens", return_value=4000):
        fitted = window.build_fitted_conversation_messages(messages, llm_model=model, requested_model_id=None, conversation_metadata={})
    assert window.TRIMMED_CONTENT_MARKER in fitted[-1]["content"]
    assert fitted[-1]["content"].endswith(INLINE_NOTE_REMINDER)


def test_append_inline_note_reminder_handles_each_content_shape():
    assert append_inline_note_reminder("Hi") == f"Hi\n\n{INLINE_NOTE_REMINDER}"
    parts = [{"type": "image_url", "image_url": {"url": "data:x"}}]
    assert append_inline_note_reminder(parts) == [*parts, {"type": "text", "text": INLINE_NOTE_REMINDER}]
    assert parts == [{"type": "image_url", "image_url": {"url": "data:x"}}]
    assert append_inline_note_reminder(None) is None
    assert "<basil_note>" not in INLINE_NOTE_REMINDER
