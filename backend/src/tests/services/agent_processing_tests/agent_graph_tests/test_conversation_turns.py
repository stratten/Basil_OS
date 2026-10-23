"""Marking and finding the current turn in a multi-turn agent conversation."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from api.services.agent_processing.lifecycle.execution_graph.conversation_turns import (
    CLIPPED_SUFFIX,
    RECAP_HEADER,
    TURN_INPUT_KEY,
    current_turn_messages,
    is_turn_input,
    mark_turn_input,
    message_text,
    render_thread_recap,
    request_text,
    turn_input_index,
    turn_input_text,
)


def _thread():
    return [
        mark_turn_input(HumanMessage(content="CONTEXT\n\nCurrent request: Read the notes")),
        AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": "/tmp/a"}, "id": "c1", "type": "tool_call"}]),
        ToolMessage(content="alpha", tool_call_id="c1"),
        AIMessage(content="The code word is alpha."),
        HumanMessage(content="nudge"),
        mark_turn_input(HumanMessage(content="Current request: And the next one?")),
        AIMessage(content="Working on it."),
    ]


def test_mark_turn_input_copies_without_mutating():
    original = HumanMessage(content="hi")
    marked = mark_turn_input(original)

    assert is_turn_input(marked)
    assert not is_turn_input(original)
    assert TURN_INPUT_KEY not in original.additional_kwargs


def test_current_turn_starts_at_the_last_marked_message():
    thread = _thread()

    assert turn_input_index(thread) == 5
    assert current_turn_messages(thread) == thread[5:]
    assert turn_input_text(thread) == "Current request: And the next one?"


def test_unmarked_conversation_is_one_turn():
    messages = [HumanMessage(content="task"), AIMessage(content="done")]

    assert turn_input_index(messages) is None
    assert current_turn_messages(messages) == messages
    assert turn_input_text(messages) == "task"
    assert turn_input_text([]) == ""


def test_request_text_strips_assembled_context():
    assert request_text("SECTION\n\nCurrent request: Do it") == "Do it"
    assert request_text("plain request") == "plain request"
    assert request_text([{"type": "text", "text": "Current request: listed"}]) == "listed"


def test_message_text_keeps_text_blocks_only():
    content = [{"type": "thinking", "thinking": "secret"}, {"type": "text", "text": "a"}, "b"]

    assert message_text(content) == "a\nb"
    assert message_text(None) == ""


def test_recap_lists_requests_answers_and_tools_but_not_nudges():
    recap = render_thread_recap(_thread()[:5])

    assert recap.splitlines() == [
        RECAP_HEADER,
        "User: Read the notes",
        "You ran: read_file",
        "You: The code word is alpha.",
    ]


def test_recap_clips_long_text_and_keeps_the_last_exchanges():
    messages = []
    for index in range(10):
        messages.append(mark_turn_input(HumanMessage(content=f"Current request: question {index}")))
        messages.append(AIMessage(content="x" * 700))

    lines = render_thread_recap(messages, max_exchanges=3, max_chars=50).splitlines()

    assert len(lines) == 1 + 3 * 2
    assert lines[1] == "User: question 7"
    assert lines[2] == "You: " + "x" * 50 + CLIPPED_SUFFIX


def test_recap_is_empty_without_a_user_message():
    assert render_thread_recap([AIMessage(content="orphan")]) == ""
