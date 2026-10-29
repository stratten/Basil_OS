from pathlib import Path

from api.core.models.reasoning.model_runtime_profile import (
    TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS,
    TOOL_CALL_FORMAT_JSON_TOOL_CALL,
    RuntimeModelProfile,
    resolve_runtime_model_profile,
    resolve_tool_call_format_for,
)
from api.services.agent_processing.lifecycle.execution_graph.local_tool_call_parser import (
    extract_text_tool_calls,
)


def test_extract_json_tool_call_format_parses_existing_qwen3_shape() -> None:
    content = """
<tool_call>
{"name": "record_result", "arguments": {"value": "basil-local-eval"}}
</tool_call>
"""

    tool_calls, cleaned = extract_text_tool_calls(
        content, TOOL_CALL_FORMAT_JSON_TOOL_CALL
    )

    assert cleaned == ""
    assert tool_calls == [
        {
            "id": "call_0_record_result",
            "name": "record_result",
            "args": {"value": "basil-local-eval"},
        }
    ]


def test_extract_function_parameter_tags_format_parses_coder_xml_shape() -> None:
    content = (
        "<tool_call><function=record_result>"
        "<parameter=value>basil-local-eval</parameter>"
        "</function></tool_call>"
    )

    tool_calls, cleaned = extract_text_tool_calls(
        content, TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS
    )

    assert cleaned == ""
    assert tool_calls == [
        {
            "id": "call_0_record_result",
            "name": "record_result",
            "args": {"value": "basil-local-eval"},
        }
    ]


def test_extract_function_parameter_tags_format_parses_qwen35_shape() -> None:
    content = """
<tool_call>
<function=record_result>
<parameter=value>
basil-local-eval
</parameter>
</function>
</tool_call>
"""

    tool_calls, cleaned = extract_text_tool_calls(
        content, TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS
    )

    assert cleaned == ""
    assert tool_calls == [
        {
            "id": "call_0_record_result",
            "name": "record_result",
            "args": {"value": "basil-local-eval"},
        }
    ]


def test_extract_function_parameter_tags_supports_multiple_parameters() -> None:
    content = """
Before.
<tool_call>
<function=record_result>
<parameter=value>
basil-local-eval
</parameter>
<parameter=source>
qwen35
</parameter>
</function>
</tool_call>
After.
"""

    tool_calls, cleaned = extract_text_tool_calls(
        content, TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS
    )

    assert cleaned == "Before.\n\nAfter."
    assert tool_calls == [
        {
            "id": "call_0_record_result",
            "name": "record_result",
            "args": {"value": "basil-local-eval", "source": "qwen35"},
        }
    ]


def test_extract_function_parameter_tags_recovers_bare_block_missing_tool_call_wrapper() -> None:
    """Regression for the incident where qwen3.5 dropped the opening
    <tool_call> wrapper but still emitted a well-formed <function=...> block
    and a stray, unmatched closing </tool_call> tag. Before this fix the
    agent silently produced zero tool calls and fabricated a "the shell
    command couldn't be executed" narrative instead of ever running it."""
    content = (
        "I'll investigate the script and repository to understand how to use "
        "the current relocatable Python when network is not available. Let "
        "me first examine the provided script.\n\n"
        "<function=shell_service_execute_command>\n"
        "<parameter=command>\n"
        "cat\n"
        "</parameter>\n"
        "<parameter=args>\n"
        '["/tmp/basil-fixture/Desktop/Projects/Personal_Projects/Redshift/'
        'RedShift_Desktop/build/scripts/build_and_sign.sh"]\n'
        "</parameter>\n"
        "</function>\n"
        "</tool_call>"
    )

    tool_calls, cleaned = extract_text_tool_calls(
        content, TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS
    )

    assert tool_calls == [
        {
            "id": "call_0_shell_service_execute_command",
            "name": "shell_service_execute_command",
            "args": {
                "command": "cat",
                "args": (
                    '["/tmp/basil-fixture/Desktop/Projects/Personal_Projects/'
                    'Redshift/RedShift_Desktop/build/scripts/build_and_sign.sh"]'
                ),
            },
        }
    ]
    assert "<function=" not in cleaned
    assert "<tool_call>" not in cleaned
    assert "</tool_call>" not in cleaned
    assert cleaned.startswith("I'll investigate the script")


def test_extract_function_parameter_tags_with_no_function_tag_falls_back_empty() -> None:
    """Negative: plain prose with neither wrapper nor bare tag yields no
    tool calls (never invents a call from free text)."""
    content = "I looked into this but could not find the file."

    tool_calls, cleaned = extract_text_tool_calls(
        content, TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS
    )

    assert tool_calls == []
    assert cleaned == content


def test_extract_function_parameter_tags_strips_leaked_reasoning_from_argument_value() -> None:
    """Regression for the 73DC32E9 retry incident: qwen3.6 called
    finalize_agent_task_result directly with a standardized_messages argument
    whose value was its own raw chain-of-thought followed by the real answer,
    with only the closing </think> tag present (the model's chat template
    injects the opener as an implicit generation prefix that never round-trips
    back as generated text). The persisted result must contain only the text
    after the orphaned closer, not the leaked reasoning."""
    content = (
        "<tool_call><function=finalize_agent_task_result>"
        "<parameter=standardized_messages>"
        "The user wants X. Let me think about the best approach.\n"
        "I will formulate the response now.\n"
        "</think>\n\n"
        "Here is the actual answer the user needs."
        "</parameter>"
        "</function></tool_call>"
    )

    tool_calls, _ = extract_text_tool_calls(
        content, TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS
    )

    assert len(tool_calls) == 1
    value = tool_calls[0]["args"]["standardized_messages"]
    assert value == "Here is the actual answer the user needs."
    assert "</think>" not in value
    assert "Let me think" not in value


def test_extract_function_parameter_tags_strips_complete_think_block_from_argument_value() -> None:
    """A well-formed <think>...</think> pair (both tags present) inside an
    argument value is stripped the same way as the orphaned-closer case."""
    content = (
        "<tool_call><function=finalize_agent_task_result>"
        "<parameter=self_assessment>"
        "<think>Internal reasoning that should never reach the user.</think>"
        "The task completed successfully."
        "</parameter>"
        "</function></tool_call>"
    )

    tool_calls, _ = extract_text_tool_calls(
        content, TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS
    )

    assert tool_calls[0]["args"]["self_assessment"] == "The task completed successfully."


def test_extract_json_tool_call_format_strips_leaked_reasoning_from_nested_list_argument() -> None:
    """The JSON tool-call path (used by models that speak native JSON
    arguments) must strip leaked reasoning from every string in a list-typed
    argument too, since standardized_messages is typically a list of strings."""
    content = (
        '<tool_call>{"name": "finalize_agent_task_result", '
        '"arguments": {"standardized_messages": '
        '["Reasoning preamble.\\n</think>\\n\\nClean final message."]}}'
        "</tool_call>"
    )

    tool_calls, _ = extract_text_tool_calls(
        content, TOOL_CALL_FORMAT_JSON_TOOL_CALL
    )

    assert tool_calls[0]["args"]["standardized_messages"] == ["Clean final message."]


def test_resolve_runtime_profile_reads_qwen35_tool_call_format() -> None:
    class LocalModel:
        model_path = Path("/tmp/basil-fixture/.basil/models/qwen35-4b-q4km.gguf")

    profile = resolve_runtime_model_profile(LocalModel())

    assert profile.model_id == "Qwen-qwen35-4b-q4km"
    assert profile.tool_call_format == TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS
    assert resolve_tool_call_format_for(profile) == TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS


def test_missing_tool_call_format_defaults_to_json_tool_call() -> None:
    profile = RuntimeModelProfile(
        model_id="custom-local",
        registry_entry=None,
        provider="custom",
        handler="llama_cpp",
    )

    assert profile.tool_call_format == TOOL_CALL_FORMAT_JSON_TOOL_CALL
    assert resolve_tool_call_format_for(profile) == TOOL_CALL_FORMAT_JSON_TOOL_CALL
