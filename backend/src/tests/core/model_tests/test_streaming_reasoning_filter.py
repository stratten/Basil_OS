"""Unit tests for StreamingReasoningFilter: real-time <think> suppression on a
live token stream, including tags split across chunk boundaries.
"""

from __future__ import annotations

import importlib

import pytest

_base_reasoning = importlib.import_module("api.core.models.reasoning.base_reasoning")

if not hasattr(_base_reasoning, "StreamingReasoningFilter"):
    pytest.skip(
        "StreamingReasoningFilter not present in current build",
        allow_module_level=True,
    )

from api.core.models.reasoning.base_reasoning import StreamingReasoningFilter  # noqa: E402


def _feed_all(filt: StreamingReasoningFilter, chunks: list[str]) -> str:
    return "".join(filt.feed(chunk) for chunk in chunks)


def test_passes_through_plain_text_with_no_reasoning():
    filt = StreamingReasoningFilter("<think>", "</think>")
    out = _feed_all(filt, ["Hello ", "world."])
    assert out == "Hello world."
    assert filt.flush() == ""
    assert filt.inside_reasoning is False


def test_suppresses_a_reasoning_block_delivered_in_one_chunk():
    filt = StreamingReasoningFilter("<think>", "</think>")
    out = _feed_all(filt, ["<think>secret reasoning</think>The answer."])
    assert out == "The answer."
    assert filt.inside_reasoning is False


def test_suppresses_a_reasoning_block_split_across_many_small_chunks():
    filt = StreamingReasoningFilter("<think>", "</think>")
    raw = "<think>Let me think this through carefully.</think>Here is the answer."
    out = "".join(filt.feed(raw[i : i + 3]) for i in range(0, len(raw), 3))
    assert out == "Here is the answer."
    assert filt.inside_reasoning is False


def test_open_tag_split_exactly_across_a_chunk_boundary():
    """The classic failure case this exists for: '<thi' + 'nk>' must still be
    recognized as one opening tag, not leaked as visible text."""
    filt = StreamingReasoningFilter("<think>", "</think>")
    out = _feed_all(filt, ["<thi", "nk>reasoning</th", "ink>answer"])
    assert out == "answer"
    assert filt.inside_reasoning is False


def test_close_tag_split_exactly_across_a_chunk_boundary():
    filt = StreamingReasoningFilter("<think>", "</think>")
    out = _feed_all(filt, ["<think>reasoning</th", "ink>", "answer"])
    assert out == "answer"


def test_unterminated_reasoning_block_suppresses_everything_and_flags_inside():
    """Generation stopped mid-think: nothing after the open tag is a real answer."""
    filt = StreamingReasoningFilter("<think>", "</think>")
    out = _feed_all(filt, ["<think>still reasoning, generation cut off here"])
    assert out == ""
    assert filt.inside_reasoning is True
    # flush() must not leak the held-back reasoning tail as visible text either.
    assert filt.flush() == ""


def test_text_before_and_after_reasoning_block_is_preserved():
    filt = StreamingReasoningFilter("<think>", "</think>")
    out = _feed_all(filt, ["Preamble. ", "<think>hidden</think>", " Conclusion."])
    assert out == "Preamble.  Conclusion."


def test_ambiguous_partial_tag_resolves_correctly_once_disproven_mid_stream():
    """A held-back '<' that turns out not to start a real tag must be released
    as soon as the next chunk disproves it, with no characters lost or reordered."""
    filt = StreamingReasoningFilter("<think>", "</think>")
    out = _feed_all(filt, ["The answer is <", "5, not thinking."])
    assert out == "The answer is <5, not thinking."
    assert filt.flush() == ""


def test_ambiguous_partial_tag_flushed_as_visible_when_stream_ends_unresolved():
    """A held-back tag-prefix that the stream simply ends on (no more input to
    prove or disprove it) is genuine visible text and must not be dropped."""
    filt = StreamingReasoningFilter("<think>", "</think>")
    out = _feed_all(filt, ["The answer is <thi"])
    assert out == "The answer is "
    assert filt.flush() == "<thi"
    assert filt.inside_reasoning is False


def test_no_reasoning_capability_never_suppresses_anything():
    filt = StreamingReasoningFilter("<think>", "</think>")
    out = _feed_all(filt, ["Just a normal streamed answer with no tags at all."])
    assert out == "Just a normal streamed answer with no tags at all."
    assert filt.inside_reasoning is False
    assert filt.flush() == ""
