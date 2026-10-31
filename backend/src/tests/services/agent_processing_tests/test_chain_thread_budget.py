"""A replayed conversation is reduced step by step to fit its share of the prompt budget."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from api.services.agent_processing.lifecycle.execution_graph.chain_thread_budget import (
    OLD_TOOL_RESULT_STUB,
    REPEATED_REQUEST_STUB,
    fit_prior_messages,
    history_budget_tokens,
)
from api.services.agent_processing.lifecycle.execution_graph.context_window_budget import estimate_prompt_tokens
from api.services.agent_processing.lifecycle.execution_graph.conversation_turns import is_turn_input, mark_turn_input


def _exchange(n, *, tool_chars=10_000, answer="answer", request=None):
    request = request or f"check mail {n}"
    return [
        mark_turn_input(HumanMessage(content=f"RUNTIME CONTEXT {n}\n\nCurrent request: {request}")),
        AIMessage(content="", tool_calls=[{"name": "gmail_search", "args": {"q": "in:inbox"}, "id": f"call-{n}"}]),
        ToolMessage(content="x" * tool_chars, tool_call_id=f"call-{n}"),
        AIMessage(content=answer),
    ]


def _thread(*exchanges):
    return [message for exchange in exchanges for message in exchange]


def _assert_tool_calls_are_paired(messages):
    for index, message in enumerate(messages):
        if isinstance(message, ToolMessage):
            previous = messages[index - 1]
            assert isinstance(previous, AIMessage)
            assert any(call["id"] == message.tool_call_id for call in previous.tool_calls)


def test_a_thread_that_fits_is_returned_untouched():
    thread = _thread(_exchange(1, tool_chars=100), _exchange(2, tool_chars=100))
    result = fit_prior_messages(thread, 50_000)
    assert result.messages == thread and result.levels == [] and result.dropped_exchanges == 0


def test_no_budget_means_no_change():
    thread = _thread(_exchange(1), _exchange(2))
    assert fit_prior_messages(thread, None).messages == thread
    assert fit_prior_messages(thread, 0).messages == thread
    assert fit_prior_messages([], 100).messages == []


def test_old_tool_results_are_stubbed_first_and_the_latest_exchange_is_untouched():
    thread = _thread(_exchange(1), _exchange(2), _exchange(3))
    result = fit_prior_messages(thread, 5_000)
    assert result.levels == ["stub_old_tool_results"]
    tool_results = [m.content for m in result.messages if isinstance(m, ToolMessage)]
    assert tool_results[:2] == [OLD_TOOL_RESULT_STUB, OLD_TOOL_RESULT_STUB]
    assert tool_results[2] == "x" * 10_000
    assert len(result.messages) == len(thread)
    _assert_tool_calls_are_paired(result.messages)


def test_older_exchanges_shrink_to_request_and_answer_when_stubbing_is_not_enough():
    thread = _thread(*[_exchange(n, answer="A" * 3_000) for n in range(1, 6)], _exchange(6, tool_chars=100))
    result = fit_prior_messages(thread, 4_000)
    assert "keep_requests_and_answers" in result.levels
    assert not any(isinstance(m, ToolMessage) and m.tool_call_id in {f"call-{n}" for n in range(1, 6)} for m in result.messages)
    assert result.messages[-1].content == "answer"
    _assert_tool_calls_are_paired(result.messages)


def test_older_requests_identical_to_the_latest_are_replaced_by_a_stub():
    big = "R" * 9_000
    thread = _thread(*[_exchange(n, tool_chars=10, request=big) for n in range(1, 7)])
    result = fit_prior_messages(thread, 4_000)
    assert result.levels == ["stub_old_tool_results", "collapse_repeated_requests"]
    humans = [m for m in result.messages if isinstance(m, HumanMessage)]
    assert [m.content for m in humans[:-1]] == [REPEATED_REQUEST_STUB] * 5
    assert big in humans[-1].content


def test_oldest_exchanges_are_dropped_with_a_visible_note_and_the_latest_is_kept():
    thread = _thread(*[_exchange(n, answer="A" * 3_000) for n in range(1, 7)], _exchange(7, tool_chars=100))
    result = fit_prior_messages(thread, 1_500)
    assert "drop_oldest_exchanges" in result.levels and result.dropped_exchanges >= 3
    assert isinstance(result.messages[0], HumanMessage) and "earlier exchange" in result.messages[0].content
    assert result.messages[-1].content == "answer"
    assert result.messages[-3].tool_calls and result.messages[-2].content == "x" * 100
    _assert_tool_calls_are_paired(result.messages)
    assert estimate_prompt_tokens(result.messages) <= 1_500 + 200


def test_the_last_exchange_is_never_dropped_even_when_it_alone_exceeds_the_budget():
    thread = _thread(_exchange(1, tool_chars=50_000, answer="B" * 9_000))
    result = fit_prior_messages(thread, 500)
    assert result.dropped_exchanges == 0
    assert len(result.messages) == 4
    assert isinstance(result.messages[0], HumanMessage)
    assert "clip_answers" in result.levels
    assert result.messages[-1].content.endswith("(truncated)")


def test_a_thread_without_turn_markers_is_split_on_human_messages():
    thread = [
        HumanMessage(content="first"),
        AIMessage(content="A" * 6_000),
        HumanMessage(content="second"),
        AIMessage(content="short"),
    ]
    result = fit_prior_messages(thread, 800)
    assert result.messages[-1].content == "short"
    assert result.dropped_exchanges + len(result.levels) > 0


def test_turn_markers_survive_the_reduction():
    thread = _thread(_exchange(1), _exchange(2), _exchange(3))
    result = fit_prior_messages(thread, 1_200)
    assert is_turn_input(result.messages[-4]) or any(is_turn_input(m) for m in result.messages)


def test_history_budget_is_half_the_prompt_budget_and_capped_for_scheduled_turns():
    assert history_budget_tokens(None, scheduled=False) is None
    assert history_budget_tokens(100_000, scheduled=False) == 50_000
    assert history_budget_tokens(100_000, scheduled=True) == 24_000
    assert history_budget_tokens(20_000, scheduled=True) == 10_000
    assert history_budget_tokens(None, scheduled=True) == 24_000
