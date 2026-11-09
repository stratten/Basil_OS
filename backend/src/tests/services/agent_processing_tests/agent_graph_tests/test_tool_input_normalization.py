"""Tests for schema-aware agent tool input normalization."""

from __future__ import annotations

from typing import Any, Dict, List, Literal

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, ValidationError

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


class _AgendaItem(BaseModel):
    id: str
    title: str
    completion_basis: str | None = None


class ObjectListInput(BaseModel):
    items: List[_AgendaItem]


async def _echo_object_items(items: List[_AgendaItem]) -> int:
    return len(items)


@pytest.mark.asyncio
async def test_json_string_list_of_objects_is_normalized():
    tool = normalize_structured_tool_args_schema(_tool("agenda", _echo_object_items, ObjectListInput))

    result = await tool.ainvoke({"items": '[{"id": "a", "title": "A", "completion_basis": null}, {"id": "b", "title": "B"}]'})

    assert result == 2


@pytest.mark.asyncio
async def test_malformed_json_list_of_objects_is_not_repaired():
    tool = normalize_structured_tool_args_schema(_tool("agenda", _echo_object_items, ObjectListInput))

    for broken in ('[{"id": "a" "b"}]', "[{'id': 'a', 'title': 'A'}]", "not a list", '{"id": "a", "title": "A"}'):
        result = await tool.ainvoke({"items": broken})
        assert "validation failed" in result


@pytest.mark.asyncio
async def test_list_of_objects_items_are_still_validated_after_normalization():
    tool = normalize_structured_tool_args_schema(_tool("agenda", _echo_object_items, ObjectListInput))

    result = await tool.ainvoke({"items": '[{"id": "a"}]'})

    assert "validation failed" in result
    assert "title" in result


def test_real_session_agenda_schema_accepts_a_quoted_catalog_array():
    import json

    import api.routes.setup_assistant.models  # noqa: F401  (import order avoids a package cycle)
    from api.services.setup_assistant.agent_graph.agenda_catalog import SETUP_AGENDA_CATALOG
    from api.services.setup_assistant.agent_graph.setup_agent_tooling.schemas import SetupProposeSessionAgendaInput

    schema = create_normalized_args_schema(SetupProposeSessionAgendaInput)
    seed = [item.to_seed_dict() for item in SETUP_AGENDA_CATALOG]

    parsed = schema(items=json.dumps(seed))

    assert len(parsed.items) == len(seed)


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


def test_stringified_nested_object_is_repaired_for_shell_whitelist_advice():
    normalized_schema = create_normalized_args_schema(ShellExecuteCommandArgs)
    validated = normalized_schema.model_validate(
        {
            "command": "find",
            "purpose": "Count files",
            "whitelist_advice": '{"recommend": true, "reason": "Read-only listing"}',
        }
    )

    assert validated.whitelist_advice is not None
    assert validated.whitelist_advice.recommend is True
    assert validated.whitelist_advice.reason == "Read-only listing"


def test_native_nested_object_still_validates_and_bad_fields_still_fail():
    normalized_schema = create_normalized_args_schema(ShellExecuteCommandArgs)
    ok = normalized_schema.model_validate(
        {"command": "ls", "whitelist_advice": {"recommend": False, "reason": "Broad"}}
    )
    assert ok.whitelist_advice.recommend is False

    with pytest.raises(ValidationError):
        normalized_schema.model_validate({"command": "ls", "whitelist_advice": '{"recommend": "maybe"}'})
    with pytest.raises(ValidationError):
        normalized_schema.model_validate({"command": "ls", "whitelist_advice": "not json at all"})
    with pytest.raises(ValidationError):
        normalized_schema.model_validate({"command": "ls", "whitelist_advice": '["recommend"]'})


def test_handle_validation_error_is_set_and_idempotent():
    tool = _tool("items", _echo_items, StringListInput)

    normalize_structured_tool_args_schema(tool)
    handler = tool.handle_validation_error
    normalize_structured_tool_args_schema(tool)

    assert handler.func is format_tool_validation_error
    assert handler.keywords["args_schema"] is tool.args_schema
    assert tool.handle_validation_error is handler


class _NestedCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender: str | None = None
    folder: str | None = None


class _NestedSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: _NestedCriteria
    limit: int = 50


async def _echo_nested_search(criteria: Dict[str, Any], limit: int = 50) -> dict[str, Any]:
    return {"criteria": criteria, "limit": limit}


def _validation_error_for(payload: dict[str, Any]) -> ValidationError:
    with pytest.raises(ValidationError) as captured:
        _NestedSearchInput.model_validate(payload)
    return captured.value


def test_validation_error_keeps_the_field_prefix_the_repetition_guard_reads():
    message = format_tool_validation_error(_validation_error_for({"criteria": {}, "folder": "inbox"}), _NestedSearchInput)

    assert message.startswith("Tool input validation failed for field(s): folder. ")
    assert message.endswith("then call the tool again.")


def test_validation_error_includes_pydantic_reason_without_a_schema():
    message = format_tool_validation_error(_validation_error_for({"criteria": {}, "folder": "inbox"}))

    assert "Reasons: folder: Extra inputs are not permitted." in message
    assert "Accepted fields" not in message


def test_validation_error_names_accepted_fields_and_where_a_misplaced_field_belongs():
    message = format_tool_validation_error(_validation_error_for({"criteria": {}, "folder": "inbox"}), _NestedSearchInput)

    assert "folder is not accepted at the top level but is accepted inside criteria." in message
    assert "Accepted fields at the top level: criteria (required), limit." in message


def test_validation_error_points_a_nested_field_back_to_the_top_level():
    message = format_tool_validation_error(_validation_error_for({"criteria": {"limit": 5}}), _NestedSearchInput)

    assert "criteria.limit: Extra inputs are not permitted" in message
    assert "limit is not accepted inside criteria but is accepted at the top level." in message
    assert "Accepted fields inside criteria: sender, folder." in message


def test_validation_error_reports_missing_required_field():
    message = format_tool_validation_error(_validation_error_for({"limit": 5}), _NestedSearchInput)

    assert "criteria: Field required" in message


def test_validation_error_never_repeats_rejected_values():
    secret = "sk-live-secret-value-123"
    message = format_tool_validation_error(
        _validation_error_for({"criteria": {"sender": 5, "folder": secret}, "limit": "many", "notes": secret}),
        _NestedSearchInput,
    )

    assert secret not in message


def test_validation_error_with_a_dict_schema_still_names_accepted_fields():
    message = format_tool_validation_error(
        _validation_error_for({"criteria": {}, "folder": "inbox"}),
        _NestedSearchInput.model_json_schema(),
    )

    assert "Accepted fields at the top level: criteria (required), limit." in message


@pytest.mark.asyncio
async def test_tool_observation_carries_reason_and_accepted_fields():
    tool = normalize_structured_tool_args_schema(_tool("search", _echo_nested_search, _NestedSearchInput))

    result = await tool.ainvoke({"criteria": {}, "folder": "inbox"})

    assert result.startswith("Tool input validation failed for field(s): folder. ")
    assert "folder is not accepted at the top level but is accepted inside criteria." in result
