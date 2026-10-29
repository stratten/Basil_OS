"""Tests that bare-word ASR tokens (Parakeet) are never run together when lines are built from tokens."""

from api.services.whisper_live_core.timed_objects import (
    ASRToken,
    Line,
    Segment,
    join_text_fragments,
    join_token_texts,
)


def tokens(*words: str):
    return [ASRToken(float(index), float(index) + 0.5, word) for index, word in enumerate(words)]


def test_join_text_fragments_adds_one_space_between_bare_words():
    assert join_text_fragments("", "whatever") == "whatever"
    assert join_text_fragments("whatever", "time") == "whatever time"
    assert join_text_fragments("whatever", " time") == "whatever time"
    assert join_text_fragments("whatever ", "time") == "whatever time"
    assert join_text_fragments("discuss", ",") == "discuss,"


def test_join_token_texts_handles_both_token_conventions():
    assert join_token_texts(tokens("she", "sent", "it")) == "she sent it"
    assert join_token_texts(tokens(" she", " sent", " it")) == " she sent it"
    assert join_token_texts([]) == ""


def test_segment_and_line_built_from_bare_word_tokens_keep_their_spaces():
    words = tokens("probably", "move", "forward")
    assert Segment.from_tokens(words).text == "probably move forward"
    assert Line().build_from_tokens(words).text == "probably move forward"
