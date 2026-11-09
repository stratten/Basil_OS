"""A long agent run is condensed into a saved record, and older tool results that are trimmed stay recoverable."""

from __future__ import annotations

import asyncio
import dataclasses
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from api.core.config import api_settings
from api.services.agent_processing.lifecycle.execution_graph import agent_loop_model_recovery as recovery
from api.services.agent_processing.lifecycle.execution_graph import conversation_summary as summary_module
from api.services.agent_processing.lifecycle.execution_graph.conversation_summary import (
    SUMMARY_HEADER,
    SUMMARY_MAX_CHARS,
    apply_summary,
    build_summary,
    choose_cut,
    head_end_index,
    summary_trigger_tokens,
)
from api.services.agent_processing.lifecycle.execution_graph.conversation_turns import is_turn_input, mark_turn_input
from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import LocalModelContextWindowExceeded
from api.services.agent_processing.shared.agent_runtime_context import reset_current_agent_context, set_current_agent_context
from api.services.agent_processing.tools.internal_basil_tools.stored_result import store

BUDGET = 3_000


class StubRequest:
    """A model request that, unlike the older test stubs, carries the model the middleware wraps."""

    def __init__(self, messages, model=None):
        self.messages = list(messages)
        self.model = model
        self.tools = []
        self.system_prompt = ""
        self.system_message = None

    def override(self, **kwargs):
        return StubRequest(kwargs.get("messages", self.messages), self.model)


class FakeModel:
    def __init__(self, reply="GOAL: finish the report\nDONE: read twelve files", error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return AIMessage(content=self.reply)

    def prompt(self, index=-1):
        return self.calls[index][0].content


def _conversation(pairs, size=1_000, prefix="c", marked=True):
    """A request message followed by assistant tool calls and their results, newest last."""
    head = HumanMessage(content="Do the task")
    messages = [mark_turn_input(head) if marked else head]
    for index in range(pairs):
        call_id = f"{prefix}{index}"
        messages.append(AIMessage(content="", tool_calls=[{"name": "some_tool", "args": {"i": index}, "id": call_id, "type": "tool_call"}]))
        messages.append(ToolMessage(content=f"R{index} " + "x" * size, tool_call_id=call_id, name="some_tool"))
    return messages


def _middleware(summarize=True, budget=BUDGET):
    return recovery.ModelRecoveryMiddleware(
        recovery.AgentRunFlags(),
        completed_model_calls=1,
        prompt_budget_tokens=budget,
        summarize_history=summarize,
    )


async def _call(middleware, messages, model):
    seen = []

    async def handler(request):
        seen.append(request)
        return AIMessage(content="ok")

    await middleware.awrap_model_call(StubRequest(messages, model), handler)
    return seen[-1]


def _tool_pairs_intact(messages):
    called = {call["id"] for message in messages if isinstance(message, AIMessage) for call in message.tool_calls}
    answered = {message.tool_call_id for message in messages if isinstance(message, ToolMessage)}
    return called == answered


@pytest.fixture
def chain(monkeypatch, tmp_path):
    monkeypatch.setattr(api_settings.settings, "STORAGE_DIR", tmp_path)
    token = set_current_agent_context({"root_task_id": "chain-1", "agent_task_id": "turn-1"})
    yield tmp_path
    reset_current_agent_context(token)


def _saved_files(root):
    return sorted(root.glob("agent_task_workspaces/*/.tool_results/*.txt"))


def test_the_trigger_is_seventy_percent_of_the_budget_and_never_more_than_the_cap():
    assert summary_trigger_tokens(3_000) == 2_100
    assert summary_trigger_tokens(10_000_000) == summary_module.SUMMARY_TRIGGER_CAP_TOKENS
    assert summary_trigger_tokens(1) == 1
    for unknown in (None, 0, -5, True):
        assert summary_trigger_tokens(unknown) is None


def test_the_cut_moves_back_to_an_assistant_message():
    messages = _conversation(12)[:-1]

    cut = choose_cut(messages, 1)

    assert cut == 15
    assert isinstance(messages[cut], AIMessage)


def test_the_cut_is_none_when_too_little_would_be_condensed():
    assert choose_cut(_conversation(5), 1) is None
    assert choose_cut([HumanMessage(content="hi")], 1) is None


def test_the_head_ends_after_the_marked_request_else_the_first_user_message_else_nothing():
    marked = [HumanMessage(content="older"), AIMessage(content="a"), mark_turn_input(HumanMessage(content="current")), AIMessage(content="b")]

    assert head_end_index(marked) == 3
    assert head_end_index(_conversation(3, marked=False)) == 1
    assert head_end_index([AIMessage(content="only an assistant")]) is None


@pytest.mark.asyncio
async def test_the_record_is_merged_into_the_request_and_the_newest_steps_are_kept():
    messages = _conversation(12)
    model = FakeModel()

    summary = await build_summary(model, messages, head_end=1, cut=17, previous=None, prompt_budget_tokens=BUDGET)
    view = apply_summary(messages, summary)

    assert len(view) == 1 + len(messages) - 17
    assert view[0].content.startswith("Do the task")
    assert SUMMARY_HEADER in view[0].content
    assert "GOAL: finish the report" in view[0].content
    assert is_turn_input(view[0])
    assert view[1:] == messages[17:]
    assert _tool_pairs_intact(view)
    assert messages[0].content == "Do the task"
    assert len(messages) == 25


@pytest.mark.asyncio
async def test_a_request_with_structured_content_keeps_its_blocks_and_gains_the_record():
    messages = _conversation(12)
    messages[0] = mark_turn_input(HumanMessage(content=[{"type": "text", "text": "Do the task"}]))
    summary = await build_summary(FakeModel(), messages, head_end=1, cut=17, previous=None, prompt_budget_tokens=BUDGET)

    head = apply_summary(messages, summary)[0]

    assert head.content[0] == {"type": "text", "text": "Do the task"}
    assert SUMMARY_HEADER in head.content[-1]["text"]


@pytest.mark.asyncio
async def test_the_record_names_the_saved_history_so_the_agent_can_search_it():
    messages = _conversation(12)
    summary = await build_summary(FakeModel(), messages, head_end=1, cut=17, previous=None, prompt_budget_tokens=BUDGET)

    view = apply_summary(messages, dataclasses.replace(summary, stored_result_id="r-12345678"))

    assert "saved as r-12345678" in view[0].content
    assert "stored_result" in view[0].content
    assert "saved as" not in apply_summary(messages, summary)[0].content


@pytest.mark.asyncio
async def test_a_summary_that_no_longer_matches_the_history_leaves_it_unchanged():
    messages = _conversation(12)
    summary = await build_summary(FakeModel(), messages, head_end=1, cut=17, previous=None, prompt_budget_tokens=BUDGET)
    shorter = messages[:10]
    other_history = _conversation(12, prefix="other")
    shifted = [HumanMessage(content="earlier"), *messages]

    assert apply_summary(shorter, summary) is shorter
    assert apply_summary(other_history, summary) is other_history
    assert apply_summary(shifted, summary) is shifted


@pytest.mark.asyncio
async def test_a_later_summary_carries_the_earlier_record_and_reads_only_the_new_steps():
    first = await build_summary(FakeModel(reply="GOAL: first record"), _conversation(12), head_end=1, cut=17, previous=None, prompt_budget_tokens=1_000_000)
    second_model = FakeModel(reply="GOAL: second record")

    second = await build_summary(second_model, _conversation(30), head_end=1, cut=53, previous=first, prompt_budget_tokens=1_000_000)

    prompt = second_model.prompt()
    assert "GOAL: first record" in prompt
    assert "which you must carry forward" in prompt
    assert "R2 " not in prompt
    assert "R9 " in prompt
    assert second.text == "GOAL: second record"
    assert (second.head_end, second.cut, second.messages_covered) == (1, 53, 52)


@pytest.mark.asyncio
async def test_the_model_sees_clipped_steps_within_its_share_of_the_budget():
    messages = _conversation(12, size=5_000)
    model = FakeModel()

    await build_summary(model, messages, head_end=1, cut=17, previous=None, prompt_budget_tokens=BUDGET)

    prompt = model.prompt()
    assert "x" * 2_000 not in prompt
    assert "earlier step(s) are not shown here" in prompt
    assert len(prompt) < 12_000


@pytest.mark.asyncio
async def test_reasoning_tags_are_removed_and_a_long_reply_is_bounded():
    messages = _conversation(12)

    tagged = await build_summary(FakeModel(reply="<think>planning</think>GOAL: g"), messages, head_end=1, cut=17, previous=None, prompt_budget_tokens=BUDGET)
    long = await build_summary(FakeModel(reply="z" * 20_000), messages, head_end=1, cut=17, previous=None, prompt_budget_tokens=BUDGET)

    assert tagged.text == "GOAL: g"
    assert len(long.text) == SUMMARY_MAX_CHARS


@pytest.mark.asyncio
async def test_a_reply_with_nothing_but_reasoning_gives_no_summary():
    for reply in ("", "   ", "<think>only thoughts</think>"):
        assert await build_summary(FakeModel(reply=reply), _conversation(12), head_end=1, cut=17, previous=None, prompt_budget_tokens=BUDGET) is None


@pytest.mark.asyncio
async def test_the_saved_history_holds_every_condensed_step_in_full(chain):
    messages = _conversation(12, size=5_000)

    summary = await build_summary(FakeModel(), messages, head_end=1, cut=17, previous=None, prompt_budget_tokens=BUDGET)

    saved = store.load_result(summary.stored_result_id)
    assert "x" * 5_000 in saved
    assert "R0 " in saved and "R7 " in saved
    assert "R8 " not in saved
    assert "Do the task" not in saved
    assert summary.messages_covered == 16


@pytest.mark.asyncio
async def test_outside_an_agent_run_the_summary_is_made_without_a_saved_history(monkeypatch, tmp_path):
    monkeypatch.setattr(api_settings.settings, "STORAGE_DIR", tmp_path)

    summary = await build_summary(FakeModel(), _conversation(12), head_end=1, cut=17, previous=None, prompt_budget_tokens=BUDGET)

    assert summary.stored_result_id is None
    assert "saved as" not in apply_summary(_conversation(12), summary)[0].content
    assert not list(tmp_path.rglob("*.txt"))


@pytest.mark.asyncio
async def test_the_middleware_condenses_a_long_run_once_and_reuses_the_record(chain):
    messages = _conversation(12)
    model = FakeModel()
    middleware = _middleware()

    first = await _call(middleware, messages, model)
    second = await _call(middleware, messages, model)

    assert len(model.calls) == 1
    assert len(first.messages) == 9
    assert len(second.messages) == 9
    assert SUMMARY_HEADER in first.messages[0].content
    assert is_turn_input(first.messages[0])
    assert first.messages[-1] is messages[-1]
    assert _tool_pairs_intact(first.messages)
    assert len(messages) == 25 and messages[0].content == "Do the task"
    assert store.load_result(middleware._summary.stored_result_id).count("[tool result: some_tool]") == 8


@pytest.mark.asyncio
async def test_a_small_amount_of_growth_does_not_trigger_another_summary_but_a_large_amount_does():
    model = FakeModel()
    middleware = _middleware()
    await _call(middleware, _conversation(12), model)

    await _call(middleware, _conversation(13), model)
    assert len(model.calls) == 1

    await _call(middleware, _conversation(32), model)
    assert len(model.calls) == 2
    assert middleware._summaries_made == 2
    assert "which you must carry forward" in model.prompt()


@pytest.mark.asyncio
async def test_no_more_than_the_cap_of_summaries_is_made_in_one_run(monkeypatch):
    monkeypatch.setattr(recovery, "MAX_SUMMARIES_PER_RUN", 1)
    model = FakeModel()
    middleware = _middleware()
    await _call(middleware, _conversation(12), model)

    await _call(middleware, _conversation(40), model)

    assert len(model.calls) == 1
    assert middleware._summaries_made == 1


@pytest.mark.asyncio
async def test_a_failed_summary_lets_the_run_continue_and_is_retried_only_after_growth():
    model = FakeModel(error=RuntimeError("model unavailable"))
    middleware = _middleware()

    request = await _call(middleware, _conversation(12), model)
    await _call(middleware, _conversation(12), model)

    assert request is not None
    assert middleware._summary is None
    assert len(model.calls) == 1

    await _call(middleware, _conversation(30), model)
    assert len(model.calls) == 2


@pytest.mark.asyncio
async def test_cancellation_during_a_summary_is_not_swallowed():
    model = FakeModel(error=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await _call(_middleware(), _conversation(12), model)


@pytest.mark.asyncio
async def test_an_empty_summary_reply_is_not_applied_and_not_retried_at_once():
    model = FakeModel(reply="<think>nothing useful</think>")
    middleware = _middleware()

    seen = await _call(middleware, _conversation(12), model)
    await _call(middleware, _conversation(12), model)

    assert middleware._summary is None
    assert len(model.calls) == 1
    assert SUMMARY_HEADER not in seen.messages[0].content


@pytest.mark.asyncio
async def test_a_request_without_a_marked_turn_input_still_uses_the_first_user_message():
    model = FakeModel()

    seen = await _call(_middleware(), _conversation(12, marked=False), model)

    assert len(model.calls) == 1
    assert SUMMARY_HEADER in seen.messages[0].content


@pytest.mark.asyncio
async def test_the_summary_tier_is_idle_when_it_is_off_unbudgeted_modelless_or_the_run_is_short():
    off, unbudgeted, short = FakeModel(), FakeModel(), FakeModel()

    seen_off = await _call(_middleware(summarize=False), _conversation(12), off)
    await _call(_middleware(budget=None), _conversation(12), unbudgeted)
    await _call(_middleware(budget=300), _conversation(4), short)
    seen_modelless = await _call(_middleware(), _conversation(12), None)

    assert off.calls == [] and unbudgeted.calls == [] and short.calls == []
    assert SUMMARY_HEADER not in seen_off.messages[0].content
    assert SUMMARY_HEADER not in seen_modelless.messages[0].content


def test_a_trimmed_result_names_its_saved_copy_and_is_unchanged_when_nothing_was_saved():
    message = ToolMessage(content="A" * 2_000, tool_call_id="call-1", name="some_tool")

    with_id = recovery.apply_routine_elision([message], {"call-1"}, {"call-1": "r-aaaaaaaa"})[0].content
    without_id = recovery.apply_routine_elision([message], {"call-1"})[0].content

    assert "the full result is saved as r-aaaaaaaa; use the stored_result tool (search or read) to recover it, or call the tool again." in with_id
    assert without_id.endswith("[1600 characters omitted; call the tool again if you need them.]")
    assert recovery.apply_routine_elision([message], set()) == [message]


def _elide(middleware, messages, monkeypatch):
    monkeypatch.setattr(recovery, "ROUTINE_COMPACTION_TRIGGER_TOKENS", 2_000)
    middleware._elide_routinely(StubRequest(messages))
    return recovery.apply_routine_elision(messages, middleware._elided_call_ids, middleware._stored_result_ids)


def test_elision_saves_each_trimmed_result_in_full_and_points_to_it(chain, monkeypatch):
    messages = [ToolMessage(content=f"result-{n} " + "D" * 9_000, tool_call_id=f"call-{n}", name="some_tool") for n in range(10)]
    middleware = recovery.ModelRecoveryMiddleware(recovery.AgentRunFlags())

    shown = _elide(middleware, messages, monkeypatch)

    trimmed = sorted(middleware._elided_call_ids)
    assert trimmed == [f"call-{n}" for n in range(10 - recovery.ROUTINE_KEEP_RECENT_RESULTS)]
    assert set(middleware._stored_result_ids) == set(trimmed)
    for message, original in zip(shown, messages):
        if original.tool_call_id in middleware._elided_call_ids:
            result_id = middleware._stored_result_ids[original.tool_call_id]
            assert f"saved as {result_id}" in message.content
            assert store.load_result(result_id) == original.content
        else:
            assert message.content == original.content
    assert len(_saved_files(chain)) == len(trimmed)


def test_elision_reuses_the_id_of_a_result_that_was_already_stored(chain, monkeypatch):
    stored_reply = json.dumps({"ok": True, "stored": True, "result_id": "r-1a2b3c4d", "preview": "p" * 9_000})
    messages = [ToolMessage(content=stored_reply, tool_call_id="call-0", name="some_tool")]
    messages += [ToolMessage(content="E" * 9_000, tool_call_id=f"call-{n}", name="some_tool") for n in range(1, 10)]
    middleware = recovery.ModelRecoveryMiddleware(recovery.AgentRunFlags())

    shown = _elide(middleware, messages, monkeypatch)

    assert middleware._stored_result_ids["call-0"] == "r-1a2b3c4d"
    assert "saved as r-1a2b3c4d" in shown[0].content
    assert len(_saved_files(chain)) == len(middleware._elided_call_ids) - 1


def test_elision_outside_an_agent_run_saves_nothing_and_keeps_the_old_text(monkeypatch, tmp_path):
    monkeypatch.setattr(api_settings.settings, "STORAGE_DIR", tmp_path)
    messages = [ToolMessage(content="F" * 9_000, tool_call_id=f"call-{n}", name="some_tool") for n in range(10)]
    middleware = recovery.ModelRecoveryMiddleware(recovery.AgentRunFlags())

    shown = _elide(middleware, messages, monkeypatch)

    assert middleware._stored_result_ids == {}
    assert shown[0].content.endswith("[8600 characters omitted; call the tool again if you need them.]")
    assert not list(tmp_path.rglob("*"))

async def _overflow_run(middleware, messages, model, overflows):
    """Run one model call whose first `overflows` attempts are refused as too long, then answered."""
    seen = []

    async def handler(request):
        seen.append(request)
        if len(seen) <= overflows:
            raise LocalModelContextWindowExceeded(9_000, 8_000)
        return AIMessage(content="ok")

    response = await middleware.awrap_model_call(StubRequest(messages, model), handler)
    return response, seen


@pytest.mark.asyncio
async def test_an_overflow_is_answered_by_condensing_the_older_steps_and_retrying():
    model = FakeModel()
    middleware = _middleware(budget=None)

    response, seen = await _overflow_run(middleware, _conversation(12), model, overflows=1)

    assert response.content == "ok"
    assert len(model.calls) == 1
    assert len(seen) == 2 and len(seen[0].messages) == 25 and len(seen[1].messages) == 9
    assert SUMMARY_HEADER in seen[1].messages[0].content
    assert middleware.compaction_level == 0
    assert middleware.prompt_budget_tokens == 6_400


@pytest.mark.asyncio
async def test_a_second_overflow_moves_on_to_the_blunt_levels_and_each_removed_result_is_saved(chain):
    model = FakeModel()
    middleware = _middleware(budget=None)
    messages = _conversation(12, size=2_000)

    response, seen = await _overflow_run(middleware, messages, model, overflows=2)

    assert response.content == "ok"
    assert len(model.calls) == 1 and len(seen) == 3
    assert middleware.compaction_level == 1
    assert SUMMARY_HEADER in seen[2].messages[0].content
    placeholders = [message.content for message in seen[2].messages if isinstance(message, ToolMessage) and "removed to fit" in message.content]
    assert placeholders and all("saved as r-" in text and "stored_result" in text for text in placeholders)
    saved_id = placeholders[0].split("saved as ")[1].split(".")[0]
    assert store.load_result(saved_id).startswith("R8 ")


@pytest.mark.asyncio
async def test_a_level_saves_the_results_it_replaces_once_each_and_names_them(chain):
    messages = _conversation(5, size=2_000)
    middleware = _middleware(summarize=False, budget=None)

    response, seen = await _overflow_run(middleware, messages, FakeModel(), overflows=1)
    again = middleware._compacted(StubRequest(messages))

    assert response.content == "ok" and middleware.compaction_level == 1
    contents = [message.content for message in seen[-1].messages if isinstance(message, ToolMessage)]
    assert contents[2:] == [message.content for message in messages if isinstance(message, ToolMessage)][2:]
    assert all("saved as r-" in text for text in contents[:2])
    first_id = contents[0].split("saved as ")[1].split(".")[0]
    assert store.load_result(first_id) == messages[2].content
    assert len(_saved_files(chain)) == 2
    assert [message.content for message in again.messages if isinstance(message, ToolMessage)][:2] == contents[:2]
    assert len(_saved_files(chain)) == 2


def test_a_level_uses_the_old_placeholder_when_no_copy_was_saved():
    messages = _conversation(5)

    unnamed = recovery.compact_messages(messages, 1)
    named = recovery.compact_messages(messages, 1, stored_result_ids={"c0": "r-aaaaaaaa"})

    unnamed_results = [message.content for message in unnamed if isinstance(message, ToolMessage)]
    named_results = [message.content for message in named if isinstance(message, ToolMessage)]
    assert unnamed_results[:2] == [recovery.COMPACTED_TOOL_RESULT] * 2
    assert "saved as r-aaaaaaaa" in named_results[0] and named_results[1] == recovery.COMPACTED_TOOL_RESULT


@pytest.mark.asyncio
async def test_an_overflow_condenses_even_below_the_trigger():
    model = FakeModel()
    middleware = _middleware(budget=1_000_000)

    response, seen = await _overflow_run(middleware, _conversation(12), model, overflows=1)

    assert response.content == "ok" and len(model.calls) == 1
    assert SUMMARY_HEADER in seen[1].messages[0].content
    assert middleware.prompt_budget_tokens == 1_000_000


@pytest.mark.asyncio
async def test_an_overflow_falls_back_to_the_levels_when_no_summary_can_be_made(monkeypatch):
    short, failing, capped, off = FakeModel(), FakeModel(error=RuntimeError("model unavailable")), FakeModel(), FakeModel()
    monkeypatch.setattr(recovery, "MAX_SUMMARIES_PER_RUN", 0)
    capped_middleware = _middleware(budget=None)
    monkeypatch.setattr(recovery, "MAX_SUMMARIES_PER_RUN", 6)

    cases = [
        (_middleware(budget=None), _conversation(4), short),
        (_middleware(budget=None), _conversation(12), failing),
        (_middleware(summarize=False, budget=None), _conversation(12), off),
    ]
    for middleware, messages, model in cases:
        response, seen = await _overflow_run(middleware, messages, model, overflows=1)
        assert response.content == "ok"
        assert middleware.compaction_level == 1
        assert middleware.prompt_budget_tokens is None
        assert SUMMARY_HEADER not in seen[-1].messages[0].content

    assert short.calls == [] and off.calls == [] and len(failing.calls) == 1
    monkeypatch.setattr(recovery, "MAX_SUMMARIES_PER_RUN", 0)
    response, _seen = await _overflow_run(capped_middleware, _conversation(12), capped, overflows=1)
    assert response.content == "ok" and capped.calls == [] and capped_middleware.compaction_level == 1


@pytest.mark.asyncio
async def test_the_run_is_stopped_with_the_existing_message_when_nothing_helps():
    middleware = recovery.ModelRecoveryMiddleware(recovery.AgentRunFlags(), completed_model_calls=1, context_window_tokens=16_000, model_label="Local Qwen", summarize_history=True)
    model = FakeModel()
    attempts = []

    async def handler(_request):
        attempts.append(1)
        raise LocalModelContextWindowExceeded(9_000, 8_000)

    response = await middleware.awrap_model_call(StubRequest(_conversation(12), model), handler)

    assert response.content.startswith("Stopped: this task needed more context than Local Qwen's 8,000-token context window holds")
    assert len(model.calls) == 1
    assert len(attempts) == 1 + 1 + recovery.MAX_COMPACTION_LEVEL
