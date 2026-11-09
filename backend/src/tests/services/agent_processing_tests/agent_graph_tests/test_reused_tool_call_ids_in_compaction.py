"""Regression tests: when a model adapter reuses one tool-call id on every turn, compaction, elision, and summaries must still act on the right results.

Local adapters once numbered calls by position within one reply, so a model making one call per reply produced the same id on every turn.
The adapters now assign unique ids, but the recovery layer keys elision and saved-result handles on the id, so it must not depend on every adapter getting that right.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from api.services.agent_processing.lifecycle.execution_graph.agent_loop_model_recovery import (
    COMPACTED_TOOL_RESULT,
    ROUTINE_KEEP_RECENT_RESULTS,
    AgentRunFlags,
    ModelRecoveryMiddleware,
    _elision_candidates,
    apply_routine_elision,
    compact_messages,
)
from api.services.agent_processing.lifecycle.execution_graph.conversation_summary import (
    ConversationSummary,
    _fingerprint,
    choose_cut,
    head_end_index,
)
from api.services.agent_processing.lifecycle.execution_graph.agent_conversation_thread import ensure_unique_tool_call_ids
from api.services.agent_processing.lifecycle.execution_graph.conversation_turns import message_text

REUSED_ID = "call_0_shell_service_execute_command"
RESULT_FILLER = "z" * 3_000


class _Request:
    def __init__(self, messages):
        self.messages = list(messages)

    def override(self, **kwargs):
        return _Request(kwargs.get("messages", self.messages))


def _conversation(count: int, ids=None) -> list:
    """A request plus ``count`` shell calls, each with a distinct, long result. ``ids`` defaults to one reused id."""
    messages: list = [HumanMessage(content="Look through the project and report what you find.")]
    for index in range(count):
        call_id = ids[index] if ids else REUSED_ID
        messages.append(AIMessage(content="", tool_calls=[{"name": "shell_service_execute_command", "args": {"n": index}, "id": call_id, "type": "tool_call"}]))
        messages.append(ToolMessage(content=f"RESULT-{index}-{RESULT_FILLER}", tool_call_id=call_id, name="shell_service_execute_command"))
    return messages


def _results(messages) -> list[ToolMessage]:
    return [message for message in messages if isinstance(message, ToolMessage)]


def _middleware() -> ModelRecoveryMiddleware:
    middleware = ModelRecoveryMiddleware(AgentRunFlags(), completed_model_calls=1)
    middleware.backoff_base_seconds = 0
    return middleware


def test_level_one_compaction_replaces_only_the_older_results_when_ids_are_reused():
    view = _middleware()._view(_Request(_conversation(8)))

    compacted = compact_messages(view, 1)

    results = _results(compacted)
    assert [message_text(r.content) for r in results[:5]] == [COMPACTED_TOOL_RESULT] * 5
    assert [message_text(r.content).split("-")[1] for r in results[5:]] == ["5", "6", "7"]


def test_routine_elision_keeps_the_newest_results_whole_when_ids_are_reused(monkeypatch):
    saved: list[str] = []
    monkeypatch.setattr(
        "api.services.agent_processing.tools.internal_basil_tools.stored_result.store.save_result",
        lambda text: saved.append(text) or {"result_id": f"r-{len(saved)}"},
    )
    middleware = _middleware()
    view = middleware._view(_Request(_conversation(10)))
    candidates = _elision_candidates(view, set())
    middleware._elided_call_ids.update(m.tool_call_id for m in candidates)
    middleware._save_elided_results(candidates)

    elided = apply_routine_elision(view, middleware._elided_call_ids, middleware._stored_result_ids)

    results = _results(elided)
    older, newest = results[:-ROUTINE_KEEP_RECENT_RESULTS], results[-ROUTINE_KEEP_RECENT_RESULTS:]
    assert len(older) == 4
    assert all(message_text(r.content).startswith("[Earlier result trimmed") for r in older)
    assert [message_text(r.content).startswith(f"RESULT-{i}-") for i, r in enumerate(newest, start=4)] == [True] * ROUTINE_KEEP_RECENT_RESULTS
    assert len(set(message_text(r.content) for r in newest)) == ROUTINE_KEEP_RECENT_RESULTS


def test_each_elided_result_points_to_its_own_saved_record_when_ids_are_reused(monkeypatch):
    saved: list[str] = []
    monkeypatch.setattr(
        "api.services.agent_processing.tools.internal_basil_tools.stored_result.store.save_result",
        lambda text: saved.append(text) or {"result_id": f"r-{len(saved)}"},
    )
    middleware = _middleware()
    view = middleware._view(_Request(_conversation(10)))
    candidates = _elision_candidates(view, set())
    middleware._elided_call_ids.update(m.tool_call_id for m in candidates)
    middleware._save_elided_results(candidates)

    older = _results(apply_routine_elision(view, middleware._elided_call_ids, middleware._stored_result_ids))[:4]

    pointers = [next(word for word in message_text(r.content).split() if word.startswith("r-")).rstrip(";,.") for r in older]
    assert len(saved) == 4
    assert pointers == ["r-1", "r-2", "r-3", "r-4"]
    assert [text.startswith(f"RESULT-{i}-") for i, text in enumerate(saved)] == [True] * 4


def test_a_history_with_unique_ids_reaches_the_model_unchanged():
    messages = _conversation(6, ids=[f"call-{i}" for i in range(6)])

    view = _middleware()._view(_Request(messages))

    assert all(shown is original for shown, original in zip(view, messages))


def test_the_ids_in_the_view_do_not_change_as_the_history_grows():
    middleware = _middleware()

    shorter = [r.tool_call_id for r in _results(middleware._view(_Request(_conversation(8))))]
    longer = [r.tool_call_id for r in _results(middleware._view(_Request(_conversation(10))))]

    assert len(set(longer)) == 10
    assert longer[:8] == shorter


def test_the_summary_is_built_from_a_history_with_unique_ids_and_then_applies(monkeypatch):
    import asyncio

    import api.services.agent_processing.lifecycle.execution_graph.agent_loop_model_recovery as recovery

    seen: dict = {}

    async def fake_build_summary(model, messages, *, head_end, cut, previous, prompt_budget_tokens):
        seen["ids"] = [m.tool_call_id for m in messages if isinstance(m, ToolMessage)]
        return ConversationSummary(
            text="BUILT SUMMARY", head_end=head_end, cut=cut, boundary=_fingerprint(messages[cut - 1]), messages_covered=cut - head_end,
        )

    monkeypatch.setattr(recovery, "build_summary", fake_build_summary)
    middleware = _middleware()
    middleware.summarize_history = True
    request = _Request(_conversation(14))
    request.model = object()

    made = asyncio.run(middleware._make_summary(request, estimate=30_000, budget=34_000))

    assert made is True
    assert len(set(seen["ids"])) == 14
    view = middleware._view(request)
    assert "BUILT SUMMARY" in message_text(view[0].content)
    assert len(view) < len(request.messages)


def test_a_saved_summary_still_applies_to_a_history_with_reused_ids():
    messages = _conversation(14)
    normalized = ensure_unique_tool_call_ids(messages)
    head_end = head_end_index(normalized)
    cut = choose_cut(normalized, head_end)
    assert cut is not None and isinstance(normalized[cut - 1], ToolMessage)
    middleware = _middleware()
    middleware._summary = ConversationSummary(
        text="EARLIER STEPS SUMMARY", head_end=head_end, cut=cut, boundary=_fingerprint(normalized[cut - 1]), messages_covered=cut - head_end,
    )

    view = middleware._view(_Request(messages))

    assert len(view) == len(messages) - (cut - head_end)
    assert "EARLIER STEPS SUMMARY" in message_text(view[0].content)
    assert len(set(r.tool_call_id for r in _results(view))) == len(_results(view))
