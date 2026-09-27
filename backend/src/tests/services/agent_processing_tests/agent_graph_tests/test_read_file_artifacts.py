"""Tests for retrieved/read file surfacing in finalizer payloads."""

from __future__ import annotations

import pytest

from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_execution import (
    _maybe_record_prepared_file_read,
)
from api.services.agent_processing.lifecycle.finalization.result_finalizer_tool import (
    finalize_agent_task_result,
)
from api.services.agent_processing.lifecycle.finalization.summary_payload import (
    merge_read_file_artifacts,
)


def test_merge_read_file_artifacts_appends_reads_with_operation_read():
    files = merge_read_file_artifacts(
        [],
        [{"name": "report.pdf", "full_path": "/Users/me/report.pdf"}],
    )
    assert files == [{
        "name": "report.pdf",
        "full_path": "/Users/me/report.pdf",
        "operation": "read",
    }]


def test_merge_read_file_artifacts_dedups_against_existing_create_entry():
    existing = [{
        "name": "report.pdf",
        "full_path": "/Users/me/report.pdf",
        "operation": "create",
    }]
    files = merge_read_file_artifacts(
        existing,
        [{"name": "report.pdf", "full_path": "/Users/me/report.pdf"}],
    )
    assert files == existing


def test_merge_read_file_artifacts_drops_entries_missing_name_or_path():
    files = merge_read_file_artifacts(
        [],
        [
            {"name": "", "full_path": "/Users/me/report.pdf"},
            {"name": "report.pdf", "full_path": ""},
            {"path": "/Users/me/other.pdf", "name": "other.pdf"},
        ],
    )
    assert files == [{
        "name": "other.pdf",
        "full_path": "/Users/me/other.pdf",
        "operation": "read",
    }]


def test_maybe_record_prepared_file_read_captures_before_truncation_shape():
    file_read_log: list[dict[str, str]] = []
    _maybe_record_prepared_file_read(
        {
            "result_kind": "prepared",
            "file_path": "/Users/me/large.docx",
            "file_name": "large.docx",
            "extracted_text": "x" * 500_000,
        },
        file_read_log,
    )
    assert file_read_log == [{
        "name": "large.docx",
        "full_path": "/Users/me/large.docx",
        "operation": "read",
    }]


def test_maybe_record_prepared_file_read_dedups_within_log():
    file_read_log: list[dict[str, str]] = []
    payload = {
        "result_kind": "prepared",
        "file_path": "/Users/me/large.docx",
        "file_name": "large.docx",
    }
    _maybe_record_prepared_file_read(payload, file_read_log)
    _maybe_record_prepared_file_read(payload, file_read_log)
    assert len(file_read_log) == 1


def test_maybe_record_prepared_file_read_ignores_non_prepared_results():
    file_read_log: list[dict[str, str]] = []
    _maybe_record_prepared_file_read(
        {"result_kind": "candidates", "file_path": "/Users/me/x.txt"},
        file_read_log,
    )
    assert file_read_log == []


@pytest.mark.asyncio
async def test_finalize_agent_task_result_includes_read_file_artifacts():
    result = await finalize_agent_task_result(
        original_prompt="Summarize the attached contract.",
        agent_task_id="agent-read-1",
        active_app="Finder",
        steps=[],
        standardized_messages=["Here is a summary of the contract terms."],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=True,
        read_file_artifacts=[{
            "name": "contract.pdf",
            "full_path": "/Users/me/Documents/contract.pdf",
        }],
    )

    assert result["success"] is True
    assert "warnings" not in result
    assert "retry_hint" not in result
    files = result["result_payload"]["files"]
    assert len(files) == 1
    assert files[0]["name"] == "contract.pdf"
    assert files[0]["full_path"] == "/Users/me/Documents/contract.pdf"
    assert files[0]["operation"] == "read"
