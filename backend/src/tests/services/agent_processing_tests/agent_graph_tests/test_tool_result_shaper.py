"""The tool-result envelope the model sees drops echoed input and duplicated payloads."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from api.services.agent_processing.lifecycle.execution_graph.service_tooling.models import BaseModel
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_execution import create_tool_function
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_result_shaper import shape_tool_envelope
from api.services.agent_processing.lifecycle.execution_graph.service_tools import ServiceToolFactory
from api.services.agent_processing.service_capabilities.service_execution_engine import ExecutionResult


def _envelope(**overrides):
    envelope = {
        "success": True,
        "result": {"output": "ok", "script_content": "tell application \"Mail\" to quit", "nested": [{"script_content": "x", "keep": 1}]},
        "data": None,
        "error": None,
        "service": "applescript_service",
        "method": "execute_applescript",
        "parameters_used": {"script_content": "tell application \"Mail\" to quit", "path": "/tmp/a.txt", "app_name": "Mail"},
        "execution_time": 1.5,
    }
    envelope.update(overrides)
    return envelope


def test_script_content_is_removed_at_every_depth_and_execution_time_is_dropped():
    shaped = shape_tool_envelope(_envelope())

    assert "script_content" not in json.dumps(shaped)
    assert shaped["result"]["nested"] == [{"keep": 1}]
    assert shaped["result"]["output"] == "ok"
    assert "execution_time" not in shaped
    assert shaped["success"] is True
    assert shaped["service"] == "applescript_service"


def test_parameters_used_keeps_only_path_and_action_hints():
    shaped = shape_tool_envelope(_envelope(parameters_used={"path": "/tmp/a.txt", "body": "long", "context_data": {"file_path": "/x", "noise": 1}}))

    assert shaped["parameters_used"] == {"path": "/tmp/a.txt", "context_data": {"file_path": "/x"}}


def test_parameters_used_is_omitted_when_nothing_useful_remains_or_it_is_not_a_dict():
    assert "parameters_used" not in shape_tool_envelope(_envelope(parameters_used={"body": "long"}))
    assert "parameters_used" not in shape_tool_envelope(_envelope(parameters_used="<EmailSearchCriteriaArgs>"))


def test_data_is_dropped_when_it_duplicates_result_or_is_only_the_stub():
    duplicate = {"messages": [1, 2, 3]}
    assert "data" not in shape_tool_envelope(_envelope(result=duplicate, data=copy.deepcopy(duplicate)))
    stub = {"summary": "Retrieved 3 items", "result_type": "list[3]", "result_count": 3, "execution_time_ms": 12}
    assert "data" not in shape_tool_envelope(_envelope(result="text", data=stub))
    assert shape_tool_envelope(_envelope(result="text", data={"rows": [1]}))["data"] == {"rows": [1]}


def test_input_envelope_is_not_mutated():
    envelope = _envelope()
    snapshot = copy.deepcopy(envelope)

    shape_tool_envelope(envelope)

    assert envelope == snapshot


class _Args(BaseModel):
    pass


class _Engine:
    def __init__(self, result):
        self._result = result

    async def execute_service_method(self, service_name, method_name, parameters):
        return self._result


def _tool(result):
    factory = SimpleNamespace(
        service_execution_engine=_Engine(result),
        max_tool_output_chars=60_000,
        max_context_tokens=1_000_000,
        tool_error_log=[],
    )
    return create_tool_function(factory, "svc_method", "desc", _Args, "svc", "method", {}), factory


@pytest.mark.asyncio
async def test_non_json_parameters_used_no_longer_falls_back_to_a_python_repr():
    class Criteria:
        def __repr__(self) -> str:
            return "<EmailSearchCriteriaArgs>"

    result = ExecutionResult(
        success=True,
        result={"emails": [{"subject": "Hello"}]},
        service="svc",
        method="method",
        parameters_used={"criteria": Criteria()},
        execution_time=0.1,
    )
    tool, _factory = _tool(result)

    output = await tool.ainvoke({})

    payload = json.loads(output)
    assert payload["result"]["emails"][0]["subject"] == "Hello"
    assert "<EmailSearchCriteriaArgs>" not in output


@pytest.mark.asyncio
async def test_unserializable_result_logs_a_warning_and_still_returns_text(caplog):
    class Opaque:
        def __str__(self) -> str:
            return "opaque-value"

    tool, _factory = _tool(Opaque())

    with caplog.at_level("WARNING"):
        output = await tool.ainvoke({})

    assert output == "opaque-value"
    assert "falling back to str(result)" in caplog.text


def test_tool_output_ceiling_is_sixty_thousand_characters_even_for_huge_windows():
    assert ServiceToolFactory.TOOL_OUTPUT_MAX_CHARS == 60_000
    factory = ServiceToolFactory(_Engine(None), SimpleNamespace(), max_context_tokens=1_000_000)
    assert factory.max_tool_output_chars == 60_000
    small = ServiceToolFactory(_Engine(None), SimpleNamespace(), max_context_tokens=100_000)
    assert small.max_tool_output_chars == 40_000


def test_redaction_placeholders_in_parameters_are_kept():
    shaped = shape_tool_envelope(_envelope(parameters_used={"content": "<redacted text:13 bytes>", "mode": "create"}))

    assert shaped["parameters_used"] == {"content": "<redacted text:13 bytes>"}
