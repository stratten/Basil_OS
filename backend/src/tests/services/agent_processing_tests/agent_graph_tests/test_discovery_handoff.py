from __future__ import annotations

import json

from langchain_classic.schema import AgentAction

from api.services.agent_processing.lifecycle.execution_graph.discovery_handoff import (
    MAX_EXTRACTED_TEXT_CHARS_PER_FILE,
    build_discovery_handoff,
)


def _step(tool: str, result: dict):
    return (
        AgentAction(tool=tool, tool_input={}, log="test"),
        json.dumps({"success": True, "result": result}),
    )


def test_build_discovery_handoff_preserves_prepared_text_and_catalog():
    steps = [
        _step(
            "file_service_prepare_file_by_path",
            {
                "result_kind": "prepared",
                "file_path": "/tmp/tracking.csv",
                "file_name": "tracking.csv",
                "file_type": "csv",
                "extracted_text": "Call Name on Calendar,Actual meeting",
                "base64_content": "not-forwarded",
            },
        )
    ]
    sources = [{"source_kind": "meeting", "authority": "primary"}]

    handoff = build_discovery_handoff(steps, sources)

    assert handoff is not None
    assert handoff.prepared_files[0]["file_path"] == "/tmp/tracking.csv"
    assert handoff.prepared_files[0]["extracted_text"] == "Call Name on Calendar,Actual meeting"
    assert handoff.source_catalog == tuple(sources)
    rendered = handoff.render()
    assert "base64_content" not in rendered
    assert '"source_kind": "meeting"' in rendered


def test_build_discovery_handoff_ignores_nonprepared_and_nonfile_steps():
    steps = [
        _step("shell_service_execute_command", {"result_kind": "prepared", "file_path": "/tmp/a"}),
        _step("file_service_prepare_file_by_path", {"result_kind": "not_found"}),
    ]

    assert build_discovery_handoff(steps, []) is None


def test_build_discovery_handoff_bounds_extracted_text_and_deduplicates_paths():
    text = "x" * (MAX_EXTRACTED_TEXT_CHARS_PER_FILE + 1)
    prepared = {
        "result_kind": "prepared",
        "file_path": "/tmp/tracking.csv",
        "file_name": "tracking.csv",
        "file_type": "csv",
        "extracted_text": text,
    }
    handoff = build_discovery_handoff(
        [
            _step("file_service_prepare_file_by_path", prepared),
            _step("file_service_find_file_for_llm", prepared),
        ],
        [],
    )

    assert handoff is not None
    assert len(handoff.prepared_files) == 1
    assert len(handoff.prepared_files[0]["extracted_text"]) == MAX_EXTRACTED_TEXT_CHARS_PER_FILE
    assert handoff.prepared_files[0]["truncated"] is True
