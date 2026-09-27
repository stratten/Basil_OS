"""Regression coverage for LlamaCppLangChainAdapter message conversion.

Every locally-loaded GGUF's own embedded chat template renders a prior
assistant tool call by walking its ``arguments`` as an already-parsed mapping,
either unconditionally (qwen3-coder crashes on a string with
``TypeError: Can only get item pairs from a mapping.``) or conditionally with
a silent-drop-on-string fallback (qwen3.5/3.6 lose every argument instead of
crashing). None of Basil's local models need ``arguments`` serialized as a
JSON string, so the adapter must hand back a real dict.
"""

from langchain_core.messages import AIMessage

from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import (
    LlamaCppLangChainAdapter,
)


def _make_adapter() -> LlamaCppLangChainAdapter:
    return LlamaCppLangChainAdapter(model_name="test-model")


def test_prior_tool_call_arguments_are_converted_as_a_dict_not_a_json_string():
    adapter = _make_adapter()
    message = AIMessage(
        content="",
        tool_calls=[
            {"id": "call_0", "name": "shell_service_execute_command", "args": {"command": "cat"}},
        ],
    )

    converted = adapter._convert_messages([message])

    assert len(converted) == 1
    tool_calls = converted[0]["tool_calls"]
    assert len(tool_calls) == 1
    arguments = tool_calls[0]["function"]["arguments"]
    assert isinstance(arguments, dict)
    assert arguments == {"command": "cat"}


def test_multiple_tool_calls_each_keep_dict_arguments():
    adapter = _make_adapter()
    message = AIMessage(
        content="",
        tool_calls=[
            {"id": "call_0", "name": "shell_service_execute_command", "args": {"command": "cat"}},
            {"id": "call_1", "name": "file_service_read_text_file", "args": {"path": "/tmp/x.txt"}},
        ],
    )

    converted = adapter._convert_messages([message])

    tool_calls = converted[0]["tool_calls"]
    assert [tc["function"]["arguments"] for tc in tool_calls] == [
        {"command": "cat"},
        {"path": "/tmp/x.txt"},
    ]


def test_tool_call_with_empty_args_converts_to_empty_dict():
    adapter = _make_adapter()
    message = AIMessage(
        content="",
        tool_calls=[{"id": "call_0", "name": "no_arg_tool", "args": {}}],
    )

    converted = adapter._convert_messages([message])

    assert converted[0]["tool_calls"][0]["function"]["arguments"] == {}
