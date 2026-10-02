from types import SimpleNamespace

from api.services.assistant_sessions.assistant_session_router_components import paste_directive
from api.services.assistant_sessions.assistant_session_router_components.paste_directive import (
    PASTE_DECISION_INSTRUCTION,
    PasteDirectiveFilter,
    resolve_paste_mode,
    with_paste_instruction,
)


def _run(tokens):
    paste_filter = PasteDirectiveFilter()
    visible = "".join(paste_filter.feed(token) for token in tokens) + paste_filter.finish()
    return visible, paste_filter


def test_strips_trailing_directive_and_records_insert():
    visible, paste_filter = _run(["Hi Sam,\n\nThanks!\n", "<basil_paste>insert</basil_paste>"])
    assert visible == "Hi Sam,\n\nThanks!\n"
    assert paste_filter.decision == "insert"
    assert paste_filter.removed_directive is True


def test_directive_split_at_every_character_never_leaks():
    text = "Answer.\n<basil_paste>show</basil_paste>"
    paste_filter = PasteDirectiveFilter()
    streamed = [paste_filter.feed(character) for character in text]
    streamed.append(paste_filter.finish())
    assert "".join(streamed) == "Answer.\n"
    assert "<" not in "".join(streamed)
    assert paste_filter.decision == "show"


def test_missing_directive_passes_text_through_with_no_decision():
    visible, paste_filter = _run(["Plain ", "answer with a < sign and <b>tags</b>"])
    assert visible == "Plain answer with a < sign and <b>tags</b>"
    assert paste_filter.decision is None
    assert paste_filter.removed_directive is False


def test_text_after_directive_is_kept():
    visible, paste_filter = _run(["Draft body\n<basil_paste>insert</basil_paste>\nP.S. extra"])
    assert visible == "Draft body\n\nP.S. extra"
    assert paste_filter.decision == "insert"


def test_unrecognized_value_is_removed_without_a_decision():
    visible, paste_filter = _run(["Body\n<basil_paste>maybe</basil_paste>"])
    assert visible == "Body\n"
    assert paste_filter.decision is None
    assert paste_filter.removed_directive is True


def test_value_is_case_and_whitespace_insensitive():
    _, paste_filter = _run(["x<basil_paste> INSERT </basil_paste>"])
    assert paste_filter.decision == "insert"


def test_open_tag_without_close_inside_window_is_literal_text():
    text = "Use the <basil_paste> tag like this: it marks the decision for Basil."
    visible, paste_filter = _run([text])
    assert visible == text
    assert paste_filter.decision is None
    assert paste_filter.removed_directive is False


def test_truncated_directive_at_stream_end_is_dropped():
    visible, paste_filter = _run(["Reply text\n", "<basil_paste>ins"])
    assert visible == "Reply text\n"
    assert paste_filter.decision is None
    assert paste_filter.removed_directive is True


def test_partial_open_tag_at_stream_end_is_flushed_as_text():
    visible, paste_filter = _run(["5 < 6 and <bas"])
    assert visible == "5 < 6 and <bas"
    assert paste_filter.removed_directive is False


def test_directive_inside_think_block_is_removed_and_last_valid_tag_wins():
    tokens = [
        "<think>I could end with <basil_paste>show</basil_paste> but",
        " it is a reply</think>",
        "Hi!\n",
        "<basil_paste>insert</basil_paste>",
    ]
    visible, paste_filter = _run(tokens)
    assert visible == "<think>I could end with  but it is a reply</think>Hi!\n"
    assert paste_filter.decision == "insert"


def test_empty_stream():
    visible, paste_filter = _run([])
    assert visible == ""
    assert paste_filter.decision is None


def test_long_reply_with_special_characters_is_unchanged_apart_from_the_tag():
    body = "Ünïcödé — emoji 🎉, quotes \"x\" and 'y', backslash \\ and {braces}\n" * 200
    visible, paste_filter = _run([body, "<basil_paste>show</basil_paste>"])
    assert visible == body
    assert paste_filter.decision == "show"


def test_with_paste_instruction_appends_instruction():
    assert with_paste_instruction("BASE") == f"BASE\n\n{PASTE_DECISION_INSTRUCTION}"
    assert "<basil_paste>insert</basil_paste>" in PASTE_DECISION_INSTRUCTION
    assert "<basil_paste>show</basil_paste>" in PASTE_DECISION_INSTRUCTION


def test_resolve_paste_mode_reads_preferences(monkeypatch):
    monkeypatch.setattr(
        paste_directive,
        "load_preferences",
        lambda: SimpleNamespace(models=SimpleNamespace(assistant_output_paste_mode="auto")),
    )
    assert resolve_paste_mode() == "auto"


def test_resolve_paste_mode_falls_back_to_always_when_preferences_fail(monkeypatch):
    def _raise():
        raise OSError("preferences unreadable")

    monkeypatch.setattr(paste_directive, "load_preferences", _raise)
    assert resolve_paste_mode() == "always"
