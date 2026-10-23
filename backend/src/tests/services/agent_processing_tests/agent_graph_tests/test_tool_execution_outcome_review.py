import json
from types import SimpleNamespace

import pytest

from api.services.agent_processing.lifecycle.execution_graph.service_tooling.models import BaseModel
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_execution import (
    create_tool_function,
)
from api.services.agent_processing.service_capabilities.service_execution_engine import ExecutionResult
from api.services.agent_processing.tools.direct_application_interactions.applescript_automation.generic_applescript_service import (
    AppleScriptResult,
)


class EmptyInput(BaseModel):
    pass


class FakeExecutionEngine:
    async def execute_service_method(self, service_name, method_name, parameters):
        return ExecutionResult(
            success=True,
            result=AppleScriptResult(
                success=True,
                output="RESULT_JSON: {}",
                execution_success=True,
                outcome_verification_status="unverified",
                needs_outcome_review=True,
                outcome_review={
                    "material_write": True,
                    "verification_status": "unverified",
                    "summary": "The app accepted the write but readback was unavailable.",
                    "evidence": {},
                    "expected": {"title": "Planning"},
                    "actual": {},
                    "discrepancies": [],
                },
            ),
            service=service_name,
            method=method_name,
            parameters_used=parameters,
            execution_time=0.1,
        )


@pytest.mark.asyncio
async def test_tool_wrapper_logs_unverified_outcome_review():
    factory = SimpleNamespace(
        service_execution_engine=FakeExecutionEngine(),
        max_tool_output_chars=20_000,
        max_context_tokens=200_000,
        tool_error_log=[],
    )
    tool = create_tool_function(
        factory,
        "applescript_service_execute_applescript",
        "Execute AppleScript",
        EmptyInput,
        "applescript_service",
        "execute_applescript",
        {},
    )

    output = await tool.ainvoke({})

    assert factory.tool_error_log == [
        {
            "tool": "applescript_service.execute_applescript",
            "error": "The app accepted the write but readback was unavailable.",
            "type": "outcome_unverified",
        }
    ]
    payload = json.loads(output)
    assert payload["success"] is True
    assert payload["result"]["needs_outcome_review"] is True
    assert payload["result"]["outcome_review"]["verification_status"] == "unverified"


def test_file_preparation_tools_do_not_end_the_agent_loop():
    factory = SimpleNamespace(
        service_execution_engine=FakeExecutionEngine(),
        max_tool_output_chars=20_000,
        max_context_tokens=200_000,
        tool_error_log=[],
    )

    preparation_tool = create_tool_function(
        factory,
        "file_service_prepare_file_by_path",
        "Prepare a file",
        EmptyInput,
        "file_service",
        "prepare_file_by_path",
        {},
    )
    ordinary_file_tool = create_tool_function(
        factory,
        "file_service_write_text_file",
        "Write a file",
        EmptyInput,
        "file_service",
        "write_text_file",
        {},
    )

    assert preparation_tool.return_direct is False
    assert ordinary_file_tool.return_direct is False
