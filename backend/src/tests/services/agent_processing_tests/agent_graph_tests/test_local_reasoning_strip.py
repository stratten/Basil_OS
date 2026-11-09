"""Reasoning is removed from local-model messages, including the bare closing tag a Qwen3.6 template leaves behind."""

from __future__ import annotations

import pytest

from api.services.agent_processing.lifecycle.execution_graph.local_tool_call_parser import (
    extract_text_tool_calls,
    strip_think_sections,
)

_ANSWER = "I retrieved your three newest inbox messages.\n\n- **Sender:** Ann | **Subject:** Lunch"
_MONOLOGUE = "Let's draft:\nCheck against constraints:\n- Concise? Yes.\nReady. Output matches response.\u2705\n"


def test_a_complete_think_block_is_removed():
    assert strip_think_sections(f"<think>{_MONOLOGUE}</think>\n\n{_ANSWER}") == _ANSWER


def test_a_bare_closing_tag_drops_the_reasoning_before_it():
    assert strip_think_sections(f"{_MONOLOGUE}</think>\n\n{_ANSWER}") == _ANSWER


def test_text_without_any_think_tag_is_unchanged_apart_from_trimming():
    assert strip_think_sections(f"  {_ANSWER}\n") == _ANSWER


def test_an_empty_message_stays_empty():
    assert strip_think_sections("") == ""
    assert strip_think_sections("</think>") == ""


def test_a_closing_tag_after_a_complete_block_drops_only_what_precedes_it():
    assert strip_think_sections("<think>a</think>stray reasoning</think>final") == "final"


def test_the_answer_may_mention_think_as_ordinary_text():
    text = "Use the word think in a sentence: I think so."
    assert strip_think_sections(text) == text


@pytest.mark.parametrize("tool_call_format", ["function_parameter_tags", "json_tool_call"])
def test_extract_text_tool_calls_strips_a_bare_closer_from_a_plain_answer(tool_call_format):
    tool_calls, content = extract_text_tool_calls(f"{_MONOLOGUE}</think>\n\n{_ANSWER}", tool_call_format)

    assert tool_calls == []
    assert content == _ANSWER
    assert "Check against constraints" not in content


def test_extract_text_tool_calls_strips_a_bare_closer_ahead_of_a_tool_call():
    content = (
        f"{_MONOLOGUE}</think>\n\n"
        "<tool_call>\n<function=external_catalog>\n<parameter=action>\nlist_servers\n</parameter>\n</function>\n</tool_call>"
    )

    tool_calls, cleaned = extract_text_tool_calls(content, "function_parameter_tags")

    assert [call["name"] for call in tool_calls] == ["external_catalog"]
    assert "Check against constraints" not in cleaned
    assert "</think>" not in cleaned
