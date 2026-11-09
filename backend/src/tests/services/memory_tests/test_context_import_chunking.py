"""Mechanical chunking and tolerant JSON reading, the two model-free helpers of the import."""

import pytest

from api.services.memory.context_import.chunking import clean_text, first_line_hint, split_into_chunks
from api.services.memory.context_import.model_json import ModelJsonError, parse_model_json


def test_clean_text_drops_nul_and_replacement_characters_and_normalizes_newlines():
    assert clean_text("a\x00b\ufffdc\r\nd\re  ") == "abc\nd\ne"


def test_small_text_is_one_chunk():
    assert split_into_chunks("one\n\ntwo") == ["one\n\ntwo"]


def test_empty_and_whitespace_text_has_no_chunks():
    assert split_into_chunks("  \n\n ") == []


def test_paragraphs_are_packed_up_to_the_target():
    paragraphs = ["p" * 40 for _ in range(10)]

    chunks = split_into_chunks("\n\n".join(paragraphs), target_chars=100)

    assert len(chunks) == 5
    assert all(len(chunk) <= 100 for chunk in chunks)
    assert "".join(chunks).replace("\n", "") == "p" * 400


def test_a_long_line_is_split_on_spaces_and_no_word_is_lost():
    words = " ".join(f"w{index}" for index in range(300))

    chunks = split_into_chunks(words, target_chars=120)

    assert all(len(chunk) <= 120 for chunk in chunks)
    assert " ".join(chunks).split() == words.split()


def test_one_unbroken_token_longer_than_the_target_is_hard_split():
    chunks = split_into_chunks("x" * 250, target_chars=100)

    assert [len(chunk) for chunk in chunks] == [100, 100, 50]


def test_first_line_hint_is_the_first_line_trimmed():
    assert first_line_hint("\n date,note \nx") == "date,note"


def test_the_hint_is_bounded():
    assert len(first_line_hint("h" * 1000)) == 300


def test_plain_fenced_and_prose_wrapped_json_are_all_read():
    assert parse_model_json('{"a": 1}') == {"a": 1}
    assert parse_model_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_model_json('Here you go: {"a": 1} Hope that helps.') == {"a": 1}


def test_thinking_blocks_are_ignored():
    assert parse_model_json('<think>{"a": 2}</think>{"a": 1}') == {"a": 1}


def test_the_last_complete_object_wins_when_the_model_drafts_and_then_answers():
    text = 'Draft: {"notes": ["one"]} Checking constraints... Final: {"notes": ["two", {"nested": 1}]}'
    assert parse_model_json(text) == {"notes": ["two", {"nested": 1}]}


def test_a_complete_draft_is_used_when_the_final_answer_is_cut_off():
    text = 'Thinking. `{"notes": ["a draft"]}` Now the real one: {"notes": ["cut off mid'
    assert parse_model_json(text) == {"notes": ["a draft"]}


def test_nested_objects_are_never_returned_as_the_answer():
    assert parse_model_json('Here: {"items": [{"text": "a"}, {"text": "b"}]}') == {"items": [{"text": "a"}, {"text": "b"}]}


@pytest.mark.parametrize("answer", ["", "no json here", "[1, 2]", '{"a": ', "{not json}"])
def test_unreadable_answers_raise(answer):
    with pytest.raises(ModelJsonError):
        parse_model_json(answer)
