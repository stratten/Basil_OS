from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from api.core.models.reasoning.model_runtime_profile import TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS
from api.services.agent_processing.lifecycle.execution_graph.agent_loop_messages import messages_to_intermediate_steps
from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import with_unique_tool_call_ids
from api.services.agent_processing.lifecycle.execution_graph.local_tool_call_parser import extract_text_tool_calls


def _reply(command: str) -> str:
    return (
        "<tool_call>\n<function=shell_service_execute_command>\n"
        f"<parameter=command>\n{command}\n</parameter>\n"
        "</function>\n</tool_call>"
    )


def test_one_call_per_reply_turns_keep_their_own_results() -> None:
    """The reported failure: three single-call turns, the last one denied, must not all read as denied."""
    commands = ["cat README.md", "cat counter.py", "find . | xargs ls"]
    results = ["README text", "counter source", "Command approval timed out"]
    messages = [HumanMessage(content="Tell me about this project.")]
    for command, result in zip(commands, results):
        parsed, _ = extract_text_tool_calls(_reply(command), TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS)
        calls = with_unique_tool_call_ids(parsed)
        messages.append(AIMessage(content="", tool_calls=calls))
        messages.append(ToolMessage(content=result, tool_call_id=calls[0]["id"]))

    steps = messages_to_intermediate_steps(messages)

    assert [(action.tool_input["command"], observation) for action, observation in steps] == list(zip(commands, results))


def test_the_same_parsed_call_gets_a_different_id_each_time() -> None:
    parsed, _ = extract_text_tool_calls(_reply("ls"), TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS)

    first = with_unique_tool_call_ids(parsed)[0]["id"]
    second = with_unique_tool_call_ids(parsed)[0]["id"]

    assert first != second
    assert first.startswith("call_0_shell_service_execute_command_")


def test_calls_in_one_reply_stay_distinct_and_keep_name_and_args() -> None:
    calls = [
        {"id": "slim_call_0_read_file", "name": "read_file", "args": {"path": "a"}},
        {"id": "slim_call_1_read_file", "name": "read_file", "args": {"path": "b"}},
    ]

    unique = with_unique_tool_call_ids(calls)

    assert len({call["id"] for call in unique}) == 2
    assert [(call["name"], call["args"]) for call in unique] == [("read_file", {"path": "a"}), ("read_file", {"path": "b"})]
    assert calls[0]["id"] == "slim_call_0_read_file"


def test_a_call_with_no_id_still_gets_one_and_an_empty_list_is_unchanged() -> None:
    assert with_unique_tool_call_ids([{"name": "t", "args": {}}])[0]["id"].startswith("call_")
    assert with_unique_tool_call_ids([]) == []


def _call(call_id: str, command: str) -> dict:
    return {"id": call_id, "name": "shell_service_execute_command", "args": {"command": command}}


def _paired(messages: list) -> list[tuple[str, str]]:
    return [(action.tool_input["command"], observation) for action, observation in messages_to_intermediate_steps(messages)]


def test_reused_ids_across_turns_still_pair_in_order_even_if_an_adapter_repeats_them() -> None:
    """Safety net: an adapter that reuses one id on every turn must not give every call the last result."""
    messages = [
        HumanMessage(content="go"),
        AIMessage(content="", tool_calls=[_call("same", "one")]),
        ToolMessage(content="result one", tool_call_id="same"),
        AIMessage(content="", tool_calls=[_call("same", "two")]),
        ToolMessage(content="result two", tool_call_id="same"),
        AIMessage(content="", tool_calls=[_call("same", "three")]),
        ToolMessage(content="result three", tool_call_id="same"),
    ]

    assert _paired(messages) == [("one", "result one"), ("two", "result two"), ("three", "result three")]


def test_a_call_with_no_result_does_not_take_a_later_calls_result() -> None:
    messages = [
        HumanMessage(content="go"),
        AIMessage(content="", tool_calls=[_call("same", "interrupted")]),
        AIMessage(content="", tool_calls=[_call("same", "answered")]),
        ToolMessage(content="the answer", tool_call_id="same"),
    ]

    assert _paired(messages) == [("answered", "the answer")]


def test_parallel_calls_in_one_turn_with_one_id_each_pair_by_id_and_unique_ids_are_unchanged() -> None:
    messages = [
        HumanMessage(content="go"),
        AIMessage(content="", tool_calls=[_call("a", "first"), _call("b", "second")]),
        ToolMessage(content="second result", tool_call_id="b"),
        ToolMessage(content="first result", tool_call_id="a"),
    ]

    assert _paired(messages) == [("first", "first result"), ("second", "second result")]


def test_no_tool_calls_or_only_orphan_results_give_no_steps() -> None:
    assert messages_to_intermediate_steps([]) == []
    assert messages_to_intermediate_steps([HumanMessage(content="hi"), ToolMessage(content="ghost", tool_call_id="x"), AIMessage(content="done")]) == []
