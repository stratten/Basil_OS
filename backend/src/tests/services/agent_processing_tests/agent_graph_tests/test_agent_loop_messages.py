"""Tests for converting the inner agent loop's messages to Basil's step and resume shapes."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from api.services.agent_processing.lifecycle.execution_graph.agent_loop_messages import (
    EMPTY_RESUME_INPUT,
    INTERRUPTED_TOOL_CALL_RESULT,
    count_ai_messages,
    deserialize_agent_messages,
    final_agent_output,
    first_human_text,
    messages_to_intermediate_steps,
    seed_resumed_messages,
    serialize_agent_messages,
)


def _call(name: str, call_id: str, **args):
    return {"name": name, "args": dict(args), "id": call_id, "type": "tool_call"}


def _paused_conversation():
    return [
        HumanMessage(content="Paint the wall"),
        AIMessage(
            content="Checking first.",
            tool_calls=[
                _call("request_user_input", "call-ask", prompt="Which color?"),
                _call("shell_service_execute_command", "call-shell", command="ls"),
            ],
        ),
    ]


def test_steps_pair_answered_calls_and_skip_unanswered_calls():
    messages = [
        *_paused_conversation(),
        ToolMessage(content="file-a", tool_call_id="call-shell", name="shell_service_execute_command"),
    ]

    steps = messages_to_intermediate_steps(messages)

    assert len(steps) == 1
    action, observation = steps[0]
    assert action.tool == "shell_service_execute_command"
    assert action.tool_input == {"command": "ls"}
    assert "Checking first." in action.log
    assert observation == "file-a"


def test_final_output_is_closing_ai_text():
    messages = [HumanMessage(content="hi"), AIMessage(content="All done.")]

    assert final_agent_output(messages) == "All done."


def test_final_output_is_empty_while_a_tool_call_is_pending():
    assert final_agent_output(_paused_conversation()) == ""


def test_final_output_uses_last_tool_result_after_return_direct():
    messages = [
        HumanMessage(content="finalize"),
        AIMessage(content="", tool_calls=[_call("finalize_agent_task_result", "call-final")]),
        ToolMessage(content='{"status": "completed"}', tool_call_id="call-final", name="finalize_agent_task_result"),
    ]

    assert final_agent_output(messages) == '{"status": "completed"}'


def test_first_human_text_and_ai_count():
    messages = [SystemMessage(content="system"), *_paused_conversation(), AIMessage(content="done")]

    assert first_human_text(messages) == "Paint the wall"
    assert count_ai_messages(messages) == 2


def test_serialization_round_trip_preserves_tool_calls():
    restored = deserialize_agent_messages(serialize_agent_messages(_paused_conversation()))

    assert isinstance(restored[1], AIMessage)
    assert [call["id"] for call in restored[1].tool_calls] == ["call-ask", "call-shell"]


def test_deserialize_rejects_non_list_and_malformed_payloads():
    assert deserialize_agent_messages(None) == []
    assert deserialize_agent_messages("not a list") == []
    assert deserialize_agent_messages([{"type": "unknown", "data": {}}]) == []


def test_seed_answers_pending_call_and_marks_sibling_interrupted():
    seeded = seed_resumed_messages(serialize_agent_messages(_paused_conversation()), "Blue", "call-ask")

    tool_results = {message.tool_call_id: message.content for message in seeded if isinstance(message, ToolMessage)}
    assert tool_results == {"call-ask": "Blue", "call-shell": INTERRUPTED_TOOL_CALL_RESULT}
    assert isinstance(seeded[-1], ToolMessage)


def test_seed_uses_first_unanswered_call_when_pending_id_is_unknown():
    seeded = seed_resumed_messages(serialize_agent_messages(_paused_conversation()), "Blue", None)

    tool_results = {message.tool_call_id: message.content for message in seeded if isinstance(message, ToolMessage)}
    assert tool_results["call-ask"] == "Blue"


def test_seed_appends_user_message_when_nothing_is_pending():
    conversation = [HumanMessage(content="hi"), AIMessage(content="Need anything else?")]

    seeded = seed_resumed_messages(serialize_agent_messages(conversation), "No thanks", None)

    assert isinstance(seeded[-1], HumanMessage)
    assert seeded[-1].content == "No thanks"


def test_seed_substitutes_text_for_blank_response():
    seeded = seed_resumed_messages(serialize_agent_messages(_paused_conversation()), "   ", "call-ask")

    answered = next(message for message in seeded if isinstance(message, ToolMessage) and message.tool_call_id == "call-ask")
    assert answered.content == EMPTY_RESUME_INPUT


def test_seed_returns_empty_list_without_saved_messages():
    assert seed_resumed_messages(None, "Blue", "call-ask") == []
