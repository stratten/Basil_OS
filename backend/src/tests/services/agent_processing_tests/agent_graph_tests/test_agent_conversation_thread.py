"""Storing, repairing, normalizing, and replaying the agent's conversation thread."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from api.services.agent_processing.lifecycle.execution_graph import agent_conversation_thread as thread_module
from api.services.agent_processing.lifecycle.execution_graph.agent_conversation_thread import (
    FAST_LANE_DEFAULT_HISTORY_CHARS,
    FAST_LANE_MAX_HISTORY_CHARS,
    FAST_LANE_MIN_HISTORY_CHARS,
    MAX_STORED_TOOL_RESULT_CHARS,
    NEUTRAL_MODEL_FAMILY,
    REMOVED_TOOL_RESULT,
    THREAD_FORMAT_VERSION,
    TRUNCATED_TOOL_RESULT_SUFFIX,
    UNANSWERED_TOOL_CALL_RESULT,
    StoredConversationThread,
    build_fast_lane_messages,
    build_thread_for_storage,
    cap_for_storage,
    fast_lane_history_char_budget,
    load_prior_thread,
    load_thread_for_task,
    prepare_thread_for_model,
    save_agent_turn_thread,
    save_fast_lane_thread,
    save_thread,
    thread_to_chat_turns,
)
from api.services.agent_processing.lifecycle.execution_graph.conversation_turns import is_turn_input, mark_turn_input


class InMemoryThreadRepository:
    def __init__(self):
        self.rows = {}
        self.fail_reads = False

    async def save_thread(self, **row):
        self.rows[row["agent_task_id"]] = dict(row)

    async def get_thread(self, agent_task_id):
        if self.fail_reads:
            raise RuntimeError("database is locked")
        return self.rows.get(agent_task_id)


class FakeLlm:
    def __init__(self, llm_type, model):
        self._llm_type = llm_type
        self.model = model


def _call(name, call_id, **args):
    return {"name": name, "args": dict(args), "id": call_id, "type": "tool_call"}


def _turn(request, call_id, result, answer):
    return [
        mark_turn_input(HumanMessage(content=f"Current request: {request}")),
        AIMessage(content="", tool_calls=[_call("read_file", call_id, path="/tmp/a")]),
        ToolMessage(content=result, tool_call_id=call_id, name="read_file"),
        AIMessage(content=answer),
    ]


def test_stored_thread_drops_system_and_ends_with_the_shown_answer():
    thread = build_thread_for_storage([SystemMessage(content="sys"), *_turn("read", "c1", "alpha", "draft")], "Final answer.")

    assert not any(isinstance(message, SystemMessage) for message in thread)
    assert len(thread) == 4
    assert thread[-1].content == "Final answer."


def test_unanswered_call_is_closed_and_answer_appended():
    messages = [mark_turn_input(HumanMessage(content="Current request: go")), AIMessage(content="", tool_calls=[_call("slow_tool", "c9")])]

    thread = build_thread_for_storage(messages, "Stopped early.")

    assert isinstance(thread[2], ToolMessage)
    assert thread[2].tool_call_id == "c9"
    assert thread[2].content == UNANSWERED_TOOL_CALL_RESULT
    assert thread[2].status == "error"
    assert thread[-1].content == "Stopped early."


def test_reused_tool_call_ids_are_renamed_per_turn():
    messages = [
        *_turn("first", "slim_call_0_read_file", "alpha", "A"),
        *_turn("second", "slim_call_0_read_file", "beta", "B"),
    ]

    thread = build_thread_for_storage(messages, "B")
    call_ids = [call["id"] for message in thread if isinstance(message, AIMessage) for call in message.tool_calls]
    result_ids = [message.tool_call_id for message in thread if isinstance(message, ToolMessage)]

    assert call_ids == ["slim_call_0_read_file", "slim_call_0_read_file__2"]
    assert result_ids == call_ids


def test_orphan_tool_results_and_empty_ai_messages_are_dropped():
    messages = [
        mark_turn_input(HumanMessage(content="Current request: hi")),
        ToolMessage(content="ghost", tool_call_id="ghost"),
        AIMessage(content=""),
    ]

    thread = build_thread_for_storage(messages, "Hello.")

    assert [type(message).__name__ for message in thread] == ["HumanMessage", "AIMessage"]


def test_long_tool_results_are_truncated_for_storage():
    thread = cap_for_storage(_turn("big", "c1", "y" * 20_000, "done"))
    tool = next(message for message in thread if isinstance(message, ToolMessage))

    assert len(tool.content) == MAX_STORED_TOOL_RESULT_CHARS + len(TRUNCATED_TOOL_RESULT_SUFFIX)


def test_oversized_threads_blank_old_results_then_drop_old_turns():
    messages = [*_turn("one", "c1", "a" * 5_000, "A"), *_turn("two", "c2", "b" * 5_000, "B")]

    blanked = cap_for_storage(messages, max_chars=9_000)
    dropped = cap_for_storage(messages, max_chars=1_000)

    assert [message.content for message in blanked if isinstance(message, ToolMessage)] == [REMOVED_TOOL_RESULT, "b" * 5_000]
    assert is_turn_input(dropped[0])
    assert dropped[0].content == "Current request: two"


def test_same_model_reuses_the_raw_thread():
    raw = [AIMessage(content=[{"type": "thinking", "thinking": "hmm", "signature": "s"}, {"type": "text", "text": "hi"}])]
    thread = StoredConversationThread("t1", "anthropic-chat", "claude-x", raw)

    prepared = prepare_thread_for_model(thread, FakeLlm("anthropic-chat", "claude-x"))

    assert prepared[0].content[0]["type"] == "thinking"


def test_different_model_gets_a_provider_neutral_copy():
    raw = [
        mark_turn_input(HumanMessage(content=[{"type": "text", "text": "Current request: hi"}])),
        AIMessage(
            content=[{"type": "thinking", "thinking": "hmm", "signature": "sig"}, {"type": "text", "text": "Reading."}],
            tool_calls=[_call("read_file", "c1", path="/tmp/a")],
            response_metadata={"model": "claude"},
        ),
        ToolMessage(content=[{"type": "text", "text": "alpha"}], tool_call_id="c1", name="read_file"),
        AIMessage(content=[{"type": "thinking", "thinking": "only thinking", "signature": "sig"}]),
    ]
    thread = StoredConversationThread("t1", "anthropic-chat", "claude-x", raw)

    prepared = prepare_thread_for_model(thread, FakeLlm("llama_cpp", "qwen"))

    assert [type(message).__name__ for message in prepared] == ["HumanMessage", "AIMessage", "ToolMessage"]
    assert is_turn_input(prepared[0])
    assert prepared[0].content == "Current request: hi"
    assert prepared[1].content == "Reading."
    assert prepared[1].tool_calls[0]["id"] == "c1"
    assert prepared[1].response_metadata == {}
    assert prepared[2].content == "alpha"
    assert prepared[2].name == "read_file"


def test_neutral_threads_are_always_normalized():
    raw = [AIMessage(content=[{"type": "text", "text": "plain"}])]
    thread = StoredConversationThread("t1", NEUTRAL_MODEL_FAMILY, "", raw)

    assert prepare_thread_for_model(thread, FakeLlm(NEUTRAL_MODEL_FAMILY, ""))[0].content == "plain"
    assert prepare_thread_for_model(None, FakeLlm("x", "y")) == []


@pytest.mark.asyncio
async def test_agent_turn_thread_round_trips_through_the_repository():
    repo = InMemoryThreadRepository()

    saved = await save_agent_turn_thread(
        context={"agent_task_id": "task-2", "root_task_id": "root-1"},
        langchain_llm=FakeLlm("anthropic-chat", "claude-x"),
        messages=_turn("read", "c1", "alpha", "draft"),
        answer_text="The code word is alpha.",
        repository=repo,
    )
    loaded = await load_prior_thread({"previous_task_id": "task-2"}, repository=repo)

    assert saved is True
    assert repo.rows["task-2"]["root_task_id"] == "root-1"
    assert repo.rows["task-2"]["model_family"] == "anthropic-chat"
    assert repo.rows["task-2"]["format_version"] == THREAD_FORMAT_VERSION
    assert loaded.model_id == "claude-x"
    assert loaded.messages[-1].content == "The code word is alpha."
    assert is_turn_input(loaded.messages[0])


@pytest.mark.asyncio
async def test_missing_unsupported_unreadable_or_failing_threads_load_as_none():
    repo = InMemoryThreadRepository()
    repo.rows["old"] = {"format_version": 99, "messages_json": "[]", "model_family": "x", "model_id": ""}
    repo.rows["bad"] = {"format_version": THREAD_FORMAT_VERSION, "messages_json": "{not json", "model_family": "x", "model_id": ""}

    assert await load_prior_thread({}, repository=repo) is None
    assert await load_prior_thread("not a dict", repository=repo) is None
    assert await load_prior_thread({"previous_task_id": "missing"}, repository=repo) is None
    assert await load_thread_for_task("old", repository=repo) is None
    assert await load_thread_for_task("bad", repository=repo) is None
    repo.fail_reads = True
    assert await load_thread_for_task("old", repository=repo) is None


@pytest.mark.asyncio
async def test_save_failures_are_reported_not_raised(monkeypatch):
    class BrokenRepository:
        async def save_thread(self, **_row):
            raise RuntimeError("disk full")

    monkeypatch.setattr(thread_module, "_knowledge_thread_repository", lambda: None)

    assert await save_thread(
        agent_task_id="t",
        root_task_id=None,
        model_family="f",
        model_id="",
        messages=[HumanMessage(content="x")],
        repository=BrokenRepository(),
    ) is False
    assert await load_prior_thread({"previous_task_id": "x"}) is None
    assert await save_agent_turn_thread(
        context={"agent_task_id": "x"},
        langchain_llm=None,
        messages=[HumanMessage(content="x")],
        answer_text="y",
    ) is False


def test_fast_lane_history_flattens_tools_and_drops_oldest_turns():
    messages = [*_turn("first question", "c1", "alpha " * 10, "A1"), *_turn("second question", "c2", "beta", "A2")]

    turns = thread_to_chat_turns(messages, char_budget=100_000)
    trimmed = thread_to_chat_turns(messages, char_budget=60)

    assert [turn["role"] for turn in turns] == ["user", "assistant", "user", "assistant"]
    assert turns[0]["content"] == "first question"
    assert '[Called read_file with {"path": "/tmp/a"}]' in turns[1]["content"]
    assert "[read_file returned: alpha" in turns[1]["content"]
    assert turns[1]["content"].endswith("A1")
    assert trimmed[0] == {"role": "user", "content": "second question"}
    assert len(trimmed) == 2


def test_fast_lane_messages_merge_a_trailing_user_turn():
    merged = build_fast_lane_messages("sys", [{"role": "user", "content": "q"}], "next")
    appended = build_fast_lane_messages("sys", [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}], "next")

    assert merged == [{"role": "system", "content": "sys"}, {"role": "user", "content": "q\n\nnext"}]
    assert appended[-1] == {"role": "user", "content": "next"}


def test_fast_lane_history_budget_follows_the_context_window():
    assert fast_lane_history_char_budget(SimpleNamespace(max_context_length=16_384)) == 24_576
    assert fast_lane_history_char_budget(SimpleNamespace(max_context_length=1_000_000)) == FAST_LANE_MAX_HISTORY_CHARS
    assert fast_lane_history_char_budget(SimpleNamespace(max_context_length=1_000)) == FAST_LANE_MIN_HISTORY_CHARS
    assert fast_lane_history_char_budget(SimpleNamespace()) == FAST_LANE_DEFAULT_HISTORY_CHARS


@pytest.mark.asyncio
async def test_fast_lane_thread_keeps_text_history_only_without_a_prior_thread():
    repo = InMemoryThreadRepository()

    await save_fast_lane_thread(
        agent_task_id="fast-1",
        root_task_id="root-1",
        prior_thread=None,
        user_request="What next?",
        answer_text="Next is beta.",
        repository=repo,
        history_text="User: first\nYou: alpha",
    )
    first = await load_thread_for_task("fast-1", repository=repo)
    await save_fast_lane_thread(
        agent_task_id="fast-2",
        root_task_id="root-1",
        prior_thread=first,
        user_request="And after?",
        answer_text="Gamma.",
        repository=repo,
        history_text="ignored",
    )
    second = await load_thread_for_task("fast-2", repository=repo)

    assert first.model_family == NEUTRAL_MODEL_FAMILY
    assert first.messages[0].content == "User: first\nYou: alpha\n\nCurrent request: What next?"
    assert [message.content for message in second.messages] == [
        first.messages[0].content,
        "Next is beta.",
        "Current request: And after?",
        "Gamma.",
    ]
    assert is_turn_input(second.messages[2])
