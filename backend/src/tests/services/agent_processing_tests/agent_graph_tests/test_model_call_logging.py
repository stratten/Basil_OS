"""The per-call timing line the local adapter logs, so a slow call can be traced to prompt reading, thinking, or answering."""

from __future__ import annotations

import logging
from typing import Any, Iterator

import pytest
from langchain_core.messages import HumanMessage

from api.core.models.reasoning.mlx_prompt_cache import PATH_FRESH, PromptCacheStats
from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import (
    LlamaCppLangChainAdapter,
    _ReplyTally,
    describe_model_call,
)


def _content(text: str) -> dict[str, Any]:
    return {"choices": [{"delta": {"content": text}}]}


def _reasoning(text: str) -> dict[str, Any]:
    return {"choices": [{"delta": {"reasoning_content": text}}]}


def _tally(*chunks: Any) -> _ReplyTally:
    tally = _ReplyTally()
    for chunk in chunks:
        tally.add(chunk)
    return tally


def _stats() -> PromptCacheStats:
    return PromptCacheStats(
        path=PATH_FRESH,
        prompt_tokens=15_000,
        reused_tokens=9_000,
        prefill_tokens=6_000,
        first_token_seconds=4.26,
        prompt_tps=1_400.4,
        generation_tokens=420,
        generation_tps=38.46,
    )


def test_thinking_ends_at_the_close_tag_and_the_rest_is_the_answer():
    tally = _tally(_content("<think>"), _content("weigh the options"), _content("</think>"), _content("Here you go."))

    assert tally.thinking_and_answer_chars() == (len("<think>weigh the options"), len("Here you go."))


def test_a_close_tag_split_across_chunks_is_still_found():
    tally = _tally(_content("<think>abc</th"), _content("ink>done"))

    assert tally.thinking_and_answer_chars() == (len("<think>abc"), len("done"))


def test_an_unfinished_think_block_counts_everything_as_thinking():
    tally = _tally(_content("<think>still going"))

    assert tally.thinking_and_answer_chars() == (len("<think>still going"), 0)


def test_a_reply_without_thinking_is_all_answer():
    assert _tally(_content("Plain answer")).thinking_and_answer_chars() == (0, len("Plain answer"))


def test_reasoning_content_deltas_count_as_thinking():
    tally = _tally(_reasoning("hmm "), _reasoning("ok"), _content("Done"))

    assert tally.thinking_and_answer_chars() == (len("hmm ok"), len("Done"))


@pytest.mark.parametrize("chunk", [None, {}, {"choices": []}, {"choices": [None]}, {"choices": [{"delta": None}]}, {"choices": [{"delta": {"content": None}}]}])
def test_malformed_chunks_are_ignored(chunk: Any):
    assert _tally(chunk, _content("ok")).thinking_and_answer_chars() == (0, 2)


def test_the_line_reports_every_stage_when_the_engine_reports_stats():
    line = describe_model_call(
        native_seconds=14.84,
        chunk_count=61,
        stopped=False,
        stats=_stats(),
        tally=_tally(_content("<think>abcd</think>xy")),
    )

    assert line == (
        "[ModelCall] seconds=14.8 first_token_seconds=4.3 prompt_tokens=15000 reused_tokens=9000 prefill_tokens=6000 "
        "prefill_tps=1400 completion_tokens=420 decode_tps=38.5 chunks=61 stopped=false thinking_chars=11 answer_chars=2"
    )


def test_the_line_still_reports_timing_for_an_engine_with_no_stats():
    line = describe_model_call(native_seconds=3.0, chunk_count=5, stopped=True, stats=None, tally=_tally(_content("hi")))

    assert line == "[ModelCall] seconds=3.0 chunks=5 stopped=true thinking_chars=0 answer_chars=2"


def test_missing_rates_print_as_not_available_instead_of_failing():
    stats = PromptCacheStats(path=PATH_FRESH, prompt_tokens=100)

    line = describe_model_call(native_seconds=1.0, chunk_count=0, stopped=False, stats=stats, tally=_ReplyTally())

    assert "first_token_seconds=n/a" in line
    assert "prefill_tps=n/a" in line
    assert "decode_tps=n/a" in line


class _FakeEngine:
    """Streams a thinking block then an answer, and reports prompt-cache stats the way the MLX engine does."""

    last_prompt_stats = _stats()

    def n_ctx(self) -> int:
        return 32_768

    def tokenize(self, text: bytes, *_args: Any, **_kwargs: Any) -> list[int]:
        return list(range(max(1, len(text) // 4)))

    def create_chat_completion(self, **_kwargs: Any) -> Iterator[dict[str, Any]]:
        def _stream() -> Iterator[dict[str, Any]]:
            yield _content("<think>look at the request")
            yield _content("</think>")
            yield _content("Your most recent email is from Ana.")

        return _stream()


@pytest.mark.asyncio
async def test_a_real_stream_logs_one_model_call_line(caplog: pytest.LogCaptureFixture):
    adapter = LlamaCppLangChainAdapter(model_name="test-model")
    adapter._llama_instance = _FakeEngine()

    with caplog.at_level(logging.INFO):
        await adapter._agenerate([HumanMessage(content="What is my most recent email?")])

    lines = [record.getMessage() for record in caplog.records if record.getMessage().startswith("[ModelCall]")]
    assert len(lines) == 1
    assert "prompt_tokens=15000" in lines[0]
    assert "reused_tokens=9000" in lines[0]
    assert f"thinking_chars={len('<think>look at the request')}" in lines[0]
    assert f"answer_chars={len('Your most recent email is from Ana.')}" in lines[0]
    assert "stopped=false" in lines[0]
