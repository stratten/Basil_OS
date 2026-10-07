from __future__ import annotations

from types import SimpleNamespace

from api.core.models.reasoning.base_reasoning import BaseReasoningModel
from api.core.models.reasoning.streaming_contract import GenerationBudget
from api.core.models.token_utils import (
    count_conversation_tokens,
    truncate_conversation_to_fit,
)


def _request_message(size: int) -> dict:
    return {
        "role": "user",
        "content": "User request:\nSummarize the BasilAuthService folder.\n\n" + ("tool output line\n" * size),
    }


def test_single_oversize_user_message_is_shortened_not_dropped():
    messages = [
        {"role": "system", "content": "You write final answers."},
        _request_message(4000),
    ]

    truncated = truncate_conversation_to_fit(messages, max_tokens=1000)

    assert [message["role"] for message in truncated] == ["system", "user"]
    assert "Summarize the BasilAuthService folder." in truncated[1]["content"]
    assert "omitted to fit the model's context window" in truncated[1]["content"]
    assert count_conversation_tokens(truncated) <= 1000


def test_oversize_message_keeps_its_tail_as_well_as_its_head():
    content = "HEAD-MARKER " + ("filler text " * 5000) + " TAIL-MARKER"
    truncated = truncate_conversation_to_fit(
        [{"role": "system", "content": "s"}, {"role": "user", "content": content}],
        max_tokens=800,
    )

    shortened = truncated[1]["content"]
    assert shortened.startswith("HEAD-MARKER")
    assert shortened.endswith("TAIL-MARKER")


def test_message_that_fits_is_left_untouched():
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "short question"},
    ]

    assert truncate_conversation_to_fit(messages, max_tokens=1000) == messages


def test_older_messages_are_still_dropped_before_the_newest():
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "old " * 2000},
        {"role": "assistant", "content": "reply " * 2000},
        {"role": "user", "content": "latest question"},
    ]

    truncated = truncate_conversation_to_fit(messages, max_tokens=300)

    assert truncated[-1]["content"] == "latest question"
    assert all(message["content"] != "old " * 2000 for message in truncated)


def test_budget_truncation_does_not_subtract_the_output_reserve_twice():
    """input_budget_tokens is already window minus output; subtracting the reserve again left ~200 tokens and dropped the whole prompt."""
    import asyncio

    seen: dict = {}

    async def _stream(messages, *, max_tokens=None):
        seen["messages"] = messages
        yield "ok"

    fake = SimpleNamespace(
        n_ctx=32768,
        tokenizer=None,
        _generate_from_messages_streaming=_stream,
    )
    budget = GenerationBudget(
        purpose="final_synthesis",
        requested_output_tokens=16284,
        effective_output_tokens=16284,
        input_budget_tokens=16484,
        reserved_output_tokens=16284,
        model_id="local",
        context_window=32768,
        model_max_output_tokens=16384,
    )
    messages = [
        {"role": "system", "content": "You write final answers."},
        {"role": "user", "content": "User request:\nCount the files.\n" + ("x" * 4 * 15000)},
    ]

    async def _consume():
        return [
            token
            async for token in BaseReasoningModel._chat_completion_streaming_with_budget(
                fake, messages, budget
            )
        ]

    assert asyncio.run(_consume()) == ["ok"]

    sent = seen["messages"]
    assert [message["role"] for message in sent] == ["system", "user"]
    assert "Count the files." in sent[1]["content"]
    assert len(sent[1]["content"]) > 40000
