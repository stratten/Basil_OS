"""Regression coverage for local context-window overflow detection and
pairing-aware scratchpad compaction in LlamaCppLangChainAdapter.

Covers Package 1 (typed, non-regex overflow detection computed from the
model's own tokenizer) and Package 2 (compaction that never separates a tool
call from its response, always preserves leading system/human messages and
the most recent turn) from the Context Window Overflow Recovery plan.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from api.services.agent_processing.lifecycle.execution_graph.conversation_turns import mark_turn_input

from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import (
    LocalModelContextWindowExceeded,
    _detect_context_window_overflow,
    compact_scratchpad_for_context_window,
)


class _FakeLlama:
    """A minimal stand-in for ``llama_cpp.Llama`` whose token count is exactly
    one token per whitespace-separated word, so tests can reason about exact
    budgets without depending on a real tokenizer/model file."""

    def __init__(self, context_window: int) -> None:
        self._context_window = context_window

    def n_ctx(self) -> int:
        return self._context_window

    def tokenize(self, text_bytes: bytes, add_bos: bool = False):
        text = text_bytes.decode("utf-8", errors="ignore")
        return text.split() or [""]


def test_detect_context_window_overflow_returns_none_when_prompt_fits():
    llama = _FakeLlama(context_window=100)
    converted_messages = [{"role": "user", "content": "short prompt"}]

    assert _detect_context_window_overflow(llama, converted_messages) is None


def test_detect_context_window_overflow_flags_oversized_prompt():
    llama = _FakeLlama(context_window=5)
    converted_messages = [{"role": "user", "content": "one two three four five six seven"}]

    overflow = _detect_context_window_overflow(llama, converted_messages)

    assert overflow is not None
    actual_tokens, max_tokens = overflow
    assert actual_tokens >= 5
    assert max_tokens == 5


def test_local_model_context_window_exceeded_is_not_a_value_error():
    exc = LocalModelContextWindowExceeded(actual_tokens=200, max_tokens=100)

    assert isinstance(exc, RuntimeError)
    assert not isinstance(exc, ValueError)
    assert exc.actual_tokens == 200
    assert exc.max_tokens == 100


def test_compaction_preserves_system_and_first_human_message():
    llama = _FakeLlama(context_window=20)
    messages = [
        SystemMessage(content="system prompt"),
        HumanMessage(content="original task words here"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call_0", "name": "tool_a", "args": {}}],
        ),
        ToolMessage(content="observation one two three four five six seven eight", tool_call_id="call_0"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "tool_b", "args": {}}],
        ),
        ToolMessage(content="latest observation nine ten eleven twelve", tool_call_id="call_1"),
    ]

    compacted = compact_scratchpad_for_context_window(llama, messages, max_generation_tokens=1)

    assert isinstance(compacted[0], SystemMessage)
    assert isinstance(compacted[1], HumanMessage)
    assert compacted[1].content == "original task words here"


def test_compaction_never_separates_a_tool_call_from_its_response():
    llama = _FakeLlama(context_window=15)
    messages = [
        HumanMessage(content="task"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call_0", "name": "tool_a", "args": {}}],
        ),
        ToolMessage(content="first observation with several words padding it out", tool_call_id="call_0"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "tool_b", "args": {}}],
        ),
        ToolMessage(content="second observation also padded with extra words", tool_call_id="call_1"),
    ]

    compacted = compact_scratchpad_for_context_window(llama, messages, max_generation_tokens=1)

    for idx, message in enumerate(compacted):
        if isinstance(message, ToolMessage):
            assert idx > 0
            previous = compacted[idx - 1]
            assert isinstance(previous, (AIMessage, ToolMessage))
            if isinstance(previous, AIMessage):
                tool_call_ids = {tc["id"] for tc in (previous.tool_calls or [])}
                assert message.tool_call_id in tool_call_ids


def test_compaction_always_keeps_at_least_the_most_recent_turn():
    llama = _FakeLlama(context_window=1)
    messages = [
        HumanMessage(content="task"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call_0", "name": "tool_a", "args": {}}],
        ),
        ToolMessage(content="oldest observation padded with many words here", tool_call_id="call_0"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "tool_b", "args": {}}],
        ),
        ToolMessage(content="most recent observation padded with many words", tool_call_id="call_1"),
    ]

    compacted = compact_scratchpad_for_context_window(llama, messages, max_generation_tokens=1)

    tool_messages = [m for m in compacted if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "call_1"


def test_compaction_inserts_a_visible_marker_when_turns_are_dropped():
    llama = _FakeLlama(context_window=1)
    messages = [
        HumanMessage(content="task"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call_0", "name": "tool_a", "args": {}}],
        ),
        ToolMessage(content="oldest observation padded with many words here", tool_call_id="call_0"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "tool_b", "args": {}}],
        ),
        ToolMessage(content="most recent observation padded with many words", tool_call_id="call_1"),
    ]

    compacted = compact_scratchpad_for_context_window(llama, messages, max_generation_tokens=1)

    marker_candidates = [
        m for m in compacted
        if isinstance(m, AIMessage) and "omitted" in str(m.content)
    ]
    assert len(marker_candidates) == 1


def test_compaction_returns_original_messages_unchanged_when_nothing_dropped():
    llama = _FakeLlama(context_window=10_000)
    messages = [
        HumanMessage(content="task"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call_0", "name": "tool_a", "args": {}}],
        ),
        ToolMessage(content="observation", tool_call_id="call_0"),
    ]

    compacted = compact_scratchpad_for_context_window(llama, messages, max_generation_tokens=1)

    assert compacted == messages


def test_compaction_pins_the_current_request_and_drops_earlier_turns_first():
    llama = _FakeLlama(context_window=60)
    earlier_request = mark_turn_input(HumanMessage(content="first question words"))
    current_request = mark_turn_input(HumanMessage(content="second question"))
    messages = [
        SystemMessage(content="system prompt"),
        earlier_request,
        AIMessage(content="", tool_calls=[{"id": "old", "name": "tool_a", "args": {}}]),
        ToolMessage(content="old observation " + "w " * 20, tool_call_id="old"),
        AIMessage(content="first answer"),
        current_request,
        AIMessage(content="", tool_calls=[{"id": "new", "name": "tool_b", "args": {}}]),
        ToolMessage(content="new observation", tool_call_id="new"),
    ]

    compacted = compact_scratchpad_for_context_window(llama, messages, max_generation_tokens=1)

    assert compacted[0].content == "system prompt"
    assert compacted[1].content.startswith("[2 earlier tool-call turn(s) omitted")
    assert compacted[2].content == "first answer"
    assert compacted[3] is current_request
    assert compacted[4].tool_calls[0]["id"] == "new"
    assert compacted[5].content == "new observation"
    assert earlier_request not in compacted
