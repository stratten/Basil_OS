"""Tests for canonical standardized file-result extraction.

File-operation detection is structural only: it reads the ``file_artifacts``
field from a tool's JSON result. It never inspects tool stdout/log text for
keywords like "created" or "modified" (see standardized_file_operation_parser.py
and file_result_extraction.py).
"""

import json

from langchain_classic.schema import AgentAction

from api.services.agent_processing.lifecycle.execution_graph.standardized_file_operation_parser import (
    StandardizedFileOperationParser,
)
from api.services.agent_processing.lifecycle.finalization.file_result_extraction import (
    extract_files_from_steps,
)


def test_standardized_parser_rejects_prose_with_no_structured_artifacts():
    """Free-form tool output mentioning "created" must never become a fake file operation."""
    parser = StandardizedFileOperationParser()
    action = AgentAction(
        tool="external_catalog",
        tool_input={"action": "call_tool", "url": "https://github.com/org/repo/blob/main/railway.toml"},
        log="Using external_catalog tool",
    )

    message = parser._extract_file_operation_from_tool_result(
        action,
        "Created a GitHub issue and reviewed https://github.com/org/repo plus railway.toml references.",
    )

    assert message is None


def test_standardized_parser_ignores_file_capable_tool_without_file_artifacts():
    """A file-capable tool whose structured result has no file_artifacts must not
    produce a create/modify/delete claim, even if its raw text says "created"."""
    parser = StandardizedFileOperationParser()
    action = AgentAction(
        tool="shell_service_execute_command",
        tool_input={"command": "echo", "args": ["hello"]},
        log="Using shell_service tool",
    )
    observation = json.dumps({
        "result": {
            "stdout": "Successfully created file report.txt (this claim is not backed by a receipt)",
            "file_artifacts": [],
        }
    })

    message = parser._extract_file_operation_from_tool_result(action, observation)

    assert message is None


def test_standardized_parser_renders_message_from_structured_file_artifacts():
    """Real file-capable tools emit the standardized format from file_artifacts only."""
    parser = StandardizedFileOperationParser()
    action = AgentAction(
        tool="file_service_create_file",
        tool_input={"path": "/tmp/basil-fixture/Desktop/report.txt"},
        log="Using file_service tool",
    )
    observation = json.dumps({
        "result": {
            "file_artifacts": [
                {
                    "name": "report.txt",
                    "full_path": "/tmp/basil-fixture/Desktop/report.txt",
                    "operation": "create",
                }
            ]
        }
    })

    message = parser._extract_file_operation_from_tool_result(action, observation)

    assert message == "STEP_COMPLETE: Successfully created file 'report.txt' at '/tmp/basil-fixture/Desktop/report.txt'"


def test_standardized_parser_renders_multiple_artifacts_as_separate_lines():
    parser = StandardizedFileOperationParser()
    action = AgentAction(
        tool="shell_service_execute_command",
        tool_input={"command": "cp"},
        log="Using shell_service tool",
    )
    observation = json.dumps({
        "result": {
            "file_artifacts": [
                {"name": "sample.txt", "full_path": "/tmp/sample.txt", "operation": "modify"},
                {"name": "old-backup.txt", "operation": "delete"},
            ]
        }
    })

    message = parser._extract_file_operation_from_tool_result(action, observation)

    assert message == (
        "STEP_COMPLETE: Successfully modified file 'sample.txt' at '/tmp/sample.txt'\n"
        "STEP_COMPLETE: Successfully deleted file 'old-backup.txt'"
    )


def test_extract_files_from_steps_reads_structured_file_artifacts():
    steps = [
        {
            "result": {
                "result": {
                    "file_artifacts": [
                        {
                            "name": "test-document.txt",
                            "full_path": "/tmp/basil-fixture/Desktop/test-document.txt",
                            "operation": "create",
                        }
                    ]
                }
            }
        },
        {
            "result": {
                "result": {
                    "file_artifacts": [
                        {
                            "name": "sample.txt",
                            "full_path": "/tmp/basil-fixture/Desktop/sample.txt",
                            "operation": "modify",
                        }
                    ]
                }
            }
        },
    ]

    assert extract_files_from_steps(steps) == [
        {
            "name": "test-document.txt",
            "full_path": "/tmp/basil-fixture/Desktop/test-document.txt",
            "operation": "create",
        },
        {
            "name": "sample.txt",
            "full_path": "/tmp/basil-fixture/Desktop/sample.txt",
            "operation": "modify",
        },
    ]


def test_extract_files_from_steps_ignores_unrelated_script_error_text():
    """A step's free-form error text must never be mined for a file claim; only
    the structured file_artifacts field (absent here) is authoritative."""
    steps = [
        {"result": {"success": True, "error": "script error: Expected end of line"}},
        {
            "result": {
                "result": {
                    "file_artifacts": [
                        {
                            "name": "sample.txt",
                            "full_path": "/tmp/basil-fixture/Desktop/sample.txt",
                            "operation": "modify",
                        }
                    ]
                }
            }
        },
    ]

    assert extract_files_from_steps(steps) == [
        {
            "name": "sample.txt",
            "full_path": "/tmp/basil-fixture/Desktop/sample.txt",
            "operation": "modify",
        }
    ]


def test_extract_files_from_steps_returns_no_files_without_artifacts():
    steps = [{"result": {"success": True, "message": "Successfully analyzed 100 records"}}]

    assert extract_files_from_steps(steps) == []
