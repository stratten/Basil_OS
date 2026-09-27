"""Tests for schema-aware agent tool input normalization."""

from __future__ import annotations

from typing import Any, Dict, List, Literal

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ValidationError

from api.services.agent_processing.lifecycle.execution_graph.service_tooling.schema_generation import ShellExecuteCommandArgs
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_input_normalization import (
    create_normalized_args_schema,
    format_tool_validation_error,
    normalize_structured_tool_args_schema,
)


class StringListInput(BaseModel):
    items: List[str]


class DictInput(BaseModel):
    target: Dict[str, Any]


class StringInput(BaseModel):
    query: str


class LiteralInput(BaseModel):
    action: Literal["navigate", "click"]


class IntegerListInput(BaseModel):
    items: List[int]


async def _echo_items(items: List[str]) -> list[str]:
    return items


async def _echo_target(target: Dict[str, Any]) -> dict[str, Any]:
    return target


async def _echo_query(query: str) -> str:
    return query


async def _echo_action(action: Literal["navigate", "click"]) -> str:
    return action


async def _echo_integer_items(items: List[int]) -> list[int]:
    return items


def _tool(name: str, func, args_schema: type[BaseModel]) -> StructuredTool:
    return StructuredTool.from_function(
        func=func,
        coroutine=func,
        name=name,
        description=f"{name} test tool",
        args_schema=args_schema,
    )


@pytest.mark.asyncio
async def test_json_string_array_is_accepted_for_string_list_field():
    tool = normalize_structured_tool_args_schema(_tool("items", _echo_items, StringListInput))

    result = await tool.ainvoke({"items": '["browser"]'})

    assert result == ["browser"]


@pytest.mark.asyncio
async def test_comma_separated_string_is_accepted_for_string_list_field():
    tool = normalize_structured_tool_args_schema(_tool("items", _echo_items, StringListInput))

    result = await tool.ainvoke({"items": "browser,email"})

    assert result == ["browser", "email"]


@pytest.mark.asyncio
async def test_json_string_object_is_accepted_for_dict_field():
    tool = normalize_structured_tool_args_schema(_tool("target", _echo_target, DictInput))

    result = await tool.ainvoke({"target": '{"browser":"Chrome","tab_index":1}'})

    assert result == {"browser": "Chrome", "tab_index": 1}


@pytest.mark.asyncio
async def test_string_field_is_not_json_parsed():
    tool = normalize_structured_tool_args_schema(_tool("query", _echo_query, StringInput))

    result = await tool.ainvoke({"query": '["browser"]'})

    assert result == '["browser"]'


@pytest.mark.asyncio
async def test_literal_field_invalid_value_returns_guidance_observation():
    tool = normalize_structured_tool_args_schema(_tool("action", _echo_action, LiteralInput))

    result = await tool.ainvoke({"action": '["navigate"]'})

    assert "validation failed" in result
    assert "action" in result


@pytest.mark.asyncio
async def test_json_string_object_is_not_coerced_to_list():
    tool = normalize_structured_tool_args_schema(_tool("items", _echo_items, StringListInput))

    result = await tool.ainvoke({"items": '{"family":"browser"}'})

    assert "validation failed" in result
    assert "items" in result


@pytest.mark.asyncio
async def test_malformed_json_looking_list_still_fails_validation():
    tool = normalize_structured_tool_args_schema(_tool("items", _echo_items, StringListInput))

    result = await tool.ainvoke({"items": '["browser"'})

    assert "validation failed" in result
    assert "items" in result


@pytest.mark.asyncio
async def test_non_string_list_field_is_not_normalized():
    tool = normalize_structured_tool_args_schema(_tool("items", _echo_integer_items, IntegerListInput))

    result = await tool.ainvoke({"items": "[1, 2]"})

    assert "validation failed" in result
    assert "items" in result


def test_normalization_is_idempotent_and_preserves_schema_title():
    tool = _tool("items", _echo_items, StringListInput)
    original_schema = tool.args_schema.model_json_schema()

    normalize_structured_tool_args_schema(tool)
    first_schema = tool.args_schema
    normalize_structured_tool_args_schema(tool)

    assert tool.args_schema is first_schema
    assert tool.args_schema.model_json_schema()["title"] == original_schema["title"]
    assert tool.args_schema.model_json_schema()["properties"] == original_schema["properties"]


@pytest.mark.asyncio
async def test_dict_field_with_control_characters_is_coerced():
    tool = normalize_structured_tool_args_schema(_tool("target", _echo_target, DictInput))

    result = await tool.ainvoke({"target": '{"description": "line1\nline2\twith tab"}'})

    assert result == {"description": "line1\nline2\twith tab"}


@pytest.mark.asyncio
async def test_malformed_json_dict_returns_guidance_observation():
    tool = normalize_structured_tool_args_schema(_tool("target", _echo_target, DictInput))

    result = await tool.ainvoke({"target": '{"a": "he said "hi""}'})

    assert "validation failed" in result
    assert "target" in result


@pytest.mark.asyncio
async def test_external_catalog_tool_recovers_from_stringified_arguments():
    from api.services.agent_processing.tools.external_services import external_catalog_tool

    tool = normalize_structured_tool_args_schema(
        external_catalog_tool.create_external_catalog_tool()
    )

    result = await tool.ainvoke(
        {
            "action": "call_tool",
            "connection_id": "conn-1",
            "tool_name": "speakeasy_create_request",
            "arguments": '{"subject": "a" "b"}',
        }
    )

    assert "validation failed" in result
    assert "arguments" in result


def test_malformed_shell_args_returns_specific_recovery_guidance():
    with pytest.raises(ValidationError) as captured:
        ShellExecuteCommandArgs.model_validate(
            {
                "command": "bash",
                "args": '["-lc", "printf \\\"café\\\" > /tmp/example.txt"]',
            }
        )

    guidance = format_tool_validation_error(captured.value)

    assert "malformed JSON text" in guidance
    assert "native JSON array of strings" in guidance
    assert "file_service_write_text_file" in guidance
    assert "non-ASCII" in guidance


def test_valid_unicode_shell_args_are_accepted():
    normalized_schema = create_normalized_args_schema(ShellExecuteCommandArgs)
    validated = normalized_schema.model_validate(
        {"command": "bash", "args": '["-lc", "printf \'café\\n\'"]'}
    )

    assert validated.args == ["-lc", "printf 'café\n'"]


def test_handle_validation_error_is_set_and_idempotent():
    tool = _tool("items", _echo_items, StringListInput)

    normalize_structured_tool_args_schema(tool)
    handler = tool.handle_validation_error
    normalize_structured_tool_args_schema(tool)

    assert handler is format_tool_validation_error
    assert tool.handle_validation_error is handler
