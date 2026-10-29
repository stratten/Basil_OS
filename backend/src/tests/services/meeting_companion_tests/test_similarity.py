from api.services.meeting_companion.similarity import (
    content_tokens,
    is_backchannel,
    jaccard,
    looks_like_question,
    normalize_text,
)


def test_normalize_text_collapses_whitespace():
    assert normalize_text("  hello \n  world\t ") == "hello world"


def test_content_tokens_drop_stopwords_and_short_words():
    assert content_tokens("The retry logic is in the API gateway") == {"retry", "logic", "api", "gateway"}


def test_jaccard_empty_sets_are_not_similar():
    assert jaccard(set(), set()) == 0.0
    assert jaccard({"a"}, set()) == 0.0


def test_jaccard_partial_overlap():
    assert jaccard({"alpha", "beta"}, {"beta", "gamma"}) == 1 / 3


def test_backchannel_detection():
    assert is_backchannel("yeah okay")
    assert is_backchannel("uh huh")
    assert is_backchannel("yeah right okay sure")
    assert not is_backchannel("what does the billing endpoint return")


def test_question_with_mark_without_interrogative():
    assert looks_like_question("The invoice goes out on the first?")


def test_question_without_mark_when_recognizer_omits_it():
    assert looks_like_question("how does the retry policy handle timeouts")


def test_statement_is_not_a_question():
    assert not looks_like_question("The retry policy handles timeouts by backing off")


def test_short_or_filler_text_is_never_a_question():
    assert not looks_like_question("right?")
    assert not looks_like_question("okay so yeah")
