from dataclasses import dataclass

from api.services.transcription.output_text_replacements import apply_text_replacements


@dataclass
class ReplacementRule:
    source: str
    replacement: str


def test_returns_original_text_when_no_rules() -> None:
    assert apply_text_replacements("hello world", []) == "hello world"


def test_returns_original_text_when_text_is_empty() -> None:
    assert apply_text_replacements("", [ReplacementRule("slash", "/")]) == ""


def test_replaces_single_word_case_insensitively() -> None:
    result = apply_text_replacements(
        "go slash home then SLASH again",
        [ReplacementRule("slash", "/")],
    )

    assert result == "go / home then / again"


def test_does_not_match_inside_a_longer_word() -> None:
    result = apply_text_replacements(
        "do not backslash the slashed path",
        [ReplacementRule("slash", "/")],
    )

    assert result == "do not backslash the slashed path"


def test_replaces_multi_word_phrase_with_flexible_whitespace() -> None:
    result = apply_text_replacements(
        "please open new   line here",
        [ReplacementRule("new line", "\n")],
    )

    assert result == "please open \n here"


def test_longer_source_wins_over_overlapping_shorter_source() -> None:
    result = apply_text_replacements(
        "start new line end",
        [
            ReplacementRule("new", "incorrect"),
            ReplacementRule("new line", "\n"),
        ],
    )

    assert result == "start \n end"


def test_replacement_text_is_not_recursively_rematched() -> None:
    result = apply_text_replacements(
        "a",
        [
            ReplacementRule("a", "a a"),
            ReplacementRule("a a", "incorrect"),
        ],
    )

    assert result == "a a"


def test_preserves_empty_replacement_text() -> None:
    result = apply_text_replacements(
        "please remove filler word",
        [ReplacementRule("filler word", "")],
    )

    assert result == "please remove "


def test_applies_multiple_independent_rules_in_one_pass() -> None:
    result = apply_text_replacements(
        "slash then dash",
        [
            ReplacementRule("slash", "/"),
            ReplacementRule("dash", "-"),
        ],
    )

    assert result == "/ then -"
