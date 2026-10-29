from __future__ import annotations

import asyncio
import json
import logging
import os
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.lifecycle.execution_graph.service_tools import create_service_tools
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_execution import (
    redact_tool_parameters_for_log,
)
from api.services.agent_processing.lifecycle.execution_graph.system_prompts import AGENT_SYSTEM_PROMPT_TEMPLATE
from api.services.agent_processing.lifecycle.runtime.artifact_activity_publication import (
    select_serialized_file_artifacts,
)
from api.services.agent_processing.lifecycle.runtime.workflow_status_notifier import WorkflowStatusNotifier
from api.services.agent_processing.service_capabilities.service_capability_analyzer import ServiceCapabilityAnalyzer
from api.services.agent_processing.service_capabilities.service_execution_engine import (
    ServiceExecutionEngine,
    redact_text_parameters_for_log,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system import (
    file_system_service as file_system_service_module,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.file_system_service import (
    FileSystemService,
)


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _artifact_id(path: Path) -> str:
    normalized_path = os.path.normpath(str(path))
    return f"file-{sha256(normalized_path.encode('utf-8')).hexdigest()[:24]}"


async def _create_edit_tool_async(tmp_path: Path, name: str = "file_service_edit_text_files"):
    service = FileSystemService(write_roots=[tmp_path])
    analyzer = ServiceCapabilityAnalyzer(file_service=service)
    services = analyzer.discover_available_services()
    engine = ServiceExecutionEngine(analyzer)
    engine.register_service("file_service", service)
    result = await create_service_tools(
        service_execution_engine=engine,
        capability_analyzer=analyzer,
        services=services,
    )
    return next(item for item in result.tools if item.name == name)


def _create_edit_tool(tmp_path: Path, name: str = "file_service_edit_text_files"):
    return asyncio.run(_create_edit_tool_async(tmp_path, name))


def _edit_files(service: FileSystemService, files: list[dict]) -> dict:
    return asyncio.run(service.edit_text_files(files=files))


def _entry(path: Path, old: str, new: str, **extra: Any) -> dict:
    return {"path": str(path), "edits": [{"old_text": old, "new_text": new}], **extra}


def _three_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    first = tmp_path / "one.md"
    second = tmp_path / "two.md"
    third = tmp_path / "three.md"
    first.write_text("# One\nalpha\n", encoding="utf-8")
    second.write_text("# Two\nbeta\n", encoding="utf-8")
    third.write_text("# Three\ngamma\n", encoding="utf-8")
    return first, second, third


def test_multi_file_tool_edits_every_file_with_receipts_and_redacted_logs(tmp_path: Path, caplog):
    tool = _create_edit_tool(tmp_path)
    caplog.set_level(logging.INFO)
    first, second, third = _three_files(tmp_path)
    before = {path: _sha256(path) for path in (first, second, third)}

    raw = asyncio.run(
        tool.ainvoke(
            {
                "files": [
                    _entry(first, "alpha", "private-one"),
                    _entry(second, "beta", "private-two"),
                    _entry(third, "gamma", "private-three"),
                ]
            }
        )
    )
    payload = json.loads(raw)
    result = payload["result"]

    assert payload["success"] is True
    assert first.read_text(encoding="utf-8") == "# One\nprivate-one\n"
    assert second.read_text(encoding="utf-8") == "# Two\nprivate-two\n"
    assert third.read_text(encoding="utf-8") == "# Three\nprivate-three\n"
    assert result["files_total"] == 3
    assert result["files_applied"] == 3
    assert [item["status"] for item in result["results"]] == ["applied"] * 3
    assert result["results"][1]["edits_applied"] == [{"index": 0, "replacements": 1}]
    assert result["results"][0]["previous_sha256"] == before[first]
    assert result["results"][0]["sha256"] == _sha256(first)
    assert len(result["material_operation"]["receipts"]) == 3
    assert result["outcome_verification_status"] == "verified"
    assert payload["parameters_used"]["files"] == "<redacted files:3>"
    assert "private-one" not in caplog.text and "private-two" not in caplog.text
    assert "agent_task_artifact" not in payload


def test_multi_file_output_publishes_one_artifact_per_file(tmp_path: Path):
    tool = _create_edit_tool(tmp_path)
    first, second, third = _three_files(tmp_path)

    raw = asyncio.run(
        tool.ainvoke(
            {
                "files": [
                    _entry(first, "alpha", "one"),
                    _entry(second, "beta", "two"),
                    _entry(third, "gamma", "three"),
                ]
            }
        )
    )
    artifacts = select_serialized_file_artifacts(raw)

    assert json.loads(raw)["material_operation"] == json.loads(raw)["result"]["material_operation"]
    assert sorted(item["target_path"] for item in artifacts) == sorted(str(path) for path in (first, second, third))
    assert {item["operation"] for item in artifacts} == {"modify"}
    assert {item["expected_sha256"] for item in artifacts} == {_sha256(first), _sha256(second), _sha256(third)}


class _RecordingWebsocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def broadcast(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


@pytest.mark.asyncio
async def test_multi_file_output_persists_a_timeline_entry_event_and_revision_per_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    service = SQLiteKnowledgeService(tmp_path / "multi-file-artifacts.db")
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)
    await service.store_agent_task(
        agent_task_id="task-multi",
        original_prompt="Edit files",
        transcribed_prompt="Edit files",
        status="processing",
    )
    websocket = _RecordingWebsocket()
    notifier = WorkflowStatusNotifier(websocket_manager=websocket, agent_task_id="task-multi")
    workdir = tmp_path / "work"
    workdir.mkdir()
    tool = await _create_edit_tool_async(workdir)
    first, second, third = _three_files(workdir)

    raw = await tool.ainvoke(
        {
            "files": [
                _entry(first, "alpha", "one"),
                _entry(second, "beta", "two"),
                _entry(third, "gamma", "three"),
            ]
        }
    )
    published = await notifier.publish_agent_task_artifact(output=raw, source_step_id="step-1")

    assert published is True
    record = await service.get_agent_task("task-multi")
    persisted = [entry["metadata"]["artifact"] for entry in record.execution_timeline]
    assert sorted(item["local_path"] for item in persisted) == sorted(str(path) for path in (first, second, third))
    assert len(websocket.messages) == 3
    assert {message["agent_task_artifact"]["artifact_id"] for message in websocket.messages} == {
        _artifact_id(first),
        _artifact_id(second),
        _artifact_id(third),
    }
    for path in (first, second, third):
        revisions = await service.agent_task_service.list_artifact_revisions("task-multi", _artifact_id(path))
        assert len(revisions) == 1
    assert all(item["review"]["snapshot_status"] == "available" for item in persisted)


def test_single_file_edit_still_publishes_its_direct_artifact_without_a_lifted_envelope(tmp_path: Path):
    tool = _create_edit_tool(tmp_path, "file_service_edit_text_file")
    target = tmp_path / "single.md"
    target.write_text("# One\nalpha\n", encoding="utf-8")

    raw = asyncio.run(tool.ainvoke({"path": str(target), "edits": [{"old_text": "alpha", "new_text": "beta"}]}))
    payload = json.loads(raw)

    assert "material_operation" not in payload
    assert payload["agent_task_artifact"]["artifact_id"] == _artifact_id(target)
    assert len(select_serialized_file_artifacts(raw)) == 1


def test_one_bad_file_writes_nothing_and_lists_every_failure(tmp_path: Path):
    service = FileSystemService(write_roots=[tmp_path])
    first, second, third = _three_files(tmp_path)

    result = _edit_files(
        service,
        [
            _entry(first, "alpha", "changed"),
            _entry(second, "absent text", "x"),
            _entry(third, "absent too", "y"),
        ],
    )

    assert result["success"] is False
    assert result["error_type"] == "old_text_not_found"
    assert "File 1 (" in result["error"] and "File 2 (" in result["error"]
    assert result["error"].endswith("Nothing was written to any file.")
    assert [item["status"] for item in result["results"]] == ["not_written", "failed", "failed"]
    assert result["files_applied"] == 0
    assert first.read_text(encoding="utf-8") == "# One\nalpha\n"
    assert second.read_text(encoding="utf-8") == "# Two\nbeta\n"
    assert third.read_text(encoding="utf-8") == "# Three\ngamma\n"
    assert "material_operation" not in result


def test_duplicate_paths_are_refused_before_any_write(tmp_path: Path):
    service = FileSystemService(write_roots=[tmp_path])
    first, _second, _third = _three_files(tmp_path)

    result = _edit_files(service, [_entry(first, "alpha", "one"), _entry(first, "# One", "# Uno")])

    assert result["success"] is False
    assert result["error_type"] == "duplicate_path"
    assert [item["status"] for item in result["results"]] == ["not_written", "failed"]
    assert first.read_text(encoding="utf-8") == "# One\nalpha\n"


def test_stale_digest_on_a_later_file_refuses_the_whole_call(tmp_path: Path):
    service = FileSystemService(write_roots=[tmp_path])
    first, second, _third = _three_files(tmp_path)

    result = _edit_files(
        service,
        [_entry(first, "alpha", "one"), _entry(second, "beta", "two", expected_sha256="0" * 64)],
    )

    assert result["success"] is False
    assert result["error_type"] == "stale_target"
    assert result["results"][1]["previous_sha256"] == _sha256(second)
    assert first.read_text(encoding="utf-8") == "# One\nalpha\n"
    assert second.read_text(encoding="utf-8") == "# Two\nbeta\n"


def test_missing_protected_and_outside_root_files_fail_validation(tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    service = FileSystemService(write_roots=[root])
    good = root / "good.md"
    good.write_text("alpha\n", encoding="utf-8")
    missing = root / "missing.md"
    outside = tmp_path / "outside.md"
    outside.write_text("alpha\n", encoding="utf-8")
    protected = root / "protected.json"
    protected.write_text("alpha\n", encoding="utf-8")
    monkeypatch.setattr(
        file_system_service_module,
        "is_protected_runtime_path",
        lambda path: str(path) == str(protected),
    )

    result = _edit_files(
        service,
        [
            _entry(good, "alpha", "beta"),
            _entry(missing, "alpha", "beta"),
            _entry(outside, "alpha", "beta"),
            _entry(protected, "alpha", "beta"),
        ],
    )

    assert result["success"] is False
    assert [item["status"] for item in result["results"]] == ["not_written", "failed", "failed", "failed"]
    assert [item["error_type"] for item in result["results"][1:]] == [
        "invalid_path_or_mode",
        "invalid_path_or_mode",
        "policy_blocked",
    ]
    assert good.read_text(encoding="utf-8") == "alpha\n"
    assert protected.read_text(encoding="utf-8") == "alpha\n"
    assert outside.read_text(encoding="utf-8") == "alpha\n"


def test_a_write_failure_midway_reports_partial_failure_with_every_status(tmp_path: Path, monkeypatch):
    service = FileSystemService(write_roots=[tmp_path])
    first, second, third = _three_files(tmp_path)
    real_write = service.write_text_file

    async def fail_second_write(**kwargs):
        if kwargs["path"] == str(second):
            return {
                "success": False,
                "file_path": kwargs["path"],
                "operation": "modify",
                "mode": "overwrite",
                "error_type": "write_failed",
                "error": "disk full",
                "file_artifacts": [],
            }
        return await real_write(**kwargs)

    monkeypatch.setattr(service, "write_text_file", fail_second_write)

    result = _edit_files(
        service,
        [_entry(first, "alpha", "one"), _entry(second, "beta", "two"), _entry(third, "gamma", "three")],
    )

    assert result["success"] is False
    assert result["error_type"] == "partial_failure"
    assert "Wrote 1 of 3 files" in result["error"] and "disk full" in result["error"]
    assert [item["status"] for item in result["results"]] == ["applied", "write_failed", "not_attempted"]
    assert result["files_applied"] == 1
    assert first.read_text(encoding="utf-8") == "# One\none\n"
    assert second.read_text(encoding="utf-8") == "# Two\nbeta\n"
    assert third.read_text(encoding="utf-8") == "# Three\ngamma\n"
    assert len(result["material_operation"]["receipts"]) == 1


def test_a_failed_first_write_reports_its_own_error_type(tmp_path: Path, monkeypatch):
    service = FileSystemService(write_roots=[tmp_path])
    first, second, _third = _three_files(tmp_path)

    async def fail_every_write(**kwargs):
        return {"success": False, "error_type": "write_failed", "error": "read-only volume", "file_artifacts": []}

    monkeypatch.setattr(service, "write_text_file", fail_every_write)

    result = _edit_files(service, [_entry(first, "alpha", "one"), _entry(second, "beta", "two")])

    assert result["error_type"] == "write_failed"
    assert result["error"].endswith("Nothing was written to any file.")
    assert [item["status"] for item in result["results"]] == ["write_failed", "not_attempted"]


def test_multi_file_list_shape_and_limits_are_validated(tmp_path: Path):
    service = FileSystemService(write_roots=[tmp_path])
    first, _second, _third = _three_files(tmp_path)
    entry = _entry(first, "alpha", "one")

    assert _edit_files(service, [])["error_type"] == "no_files"
    assert _edit_files(service, [entry] * 21)["error_type"] == "too_many_files"
    assert _edit_files(service, ["not an object"])["error_type"] == "invalid_file_entry"
    assert _edit_files(service, [{"path": "", "edits": []}])["error_type"] == "invalid_file_entry"
    assert _edit_files(service, [{"path": str(first), "edits": []}])["error_type"] == "no_edits"
    assert "File 0 (" in _edit_files(service, [{"path": str(first), "edits": []}])["error"]
    assert first.read_text(encoding="utf-8") == "# One\nalpha\n"


def test_multi_file_redaction_and_schema(tmp_path: Path):
    parameters = {"files": [{"path": "/tmp/a", "edits": [{"old_text": "private", "new_text": "x"}]}] * 2}

    assert redact_tool_parameters_for_log(parameters) == {"files": "<redacted files:2>"}
    assert redact_text_parameters_for_log(parameters) == {"files": "<redacted files:2>"}

    schema = _create_edit_tool(tmp_path).args_schema
    valid = {"path": "/x", "edits": [{"old_text": "a", "new_text": "b"}]}
    assert schema.model_validate({"files": [valid]}).files[0].edits[0].replace_all is False
    for invalid in (
        {"files": []},
        {"files": [valid] * 21},
        {"files": [{"path": "/x", "edits": []}]},
        {"files": [{"path": "/x", "edits": [{"old_text": "", "new_text": "b"}]}]},
        {"files": [{**valid, "expected_sha256": "ABC"}]},
    ):
        with pytest.raises(ValidationError):
            schema.model_validate(invalid)


def test_multi_file_tool_is_advertised_and_prompt_forbids_script_patching(tmp_path: Path):
    service = FileSystemService(write_roots=[tmp_path])
    methods = {method["name"]: method for method in service.get_service_capabilities()["methods"]}

    assert "edit_text_files" in methods
    assert "no approval prompt" in methods["edit_text_files"]["description"]
    assert "no approval prompt" in methods["edit_text_file"]["description"]
    assert "file_service_edit_text_files" in AGENT_SYSTEM_PROMPT_TEMPLATE
    assert "Do NOT patch or append to text files with python3 -c, sed -i, perl -pi" in AGENT_SYSTEM_PROMPT_TEMPLATE
