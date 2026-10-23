from __future__ import annotations

import asyncio
import json
import logging
import os
from hashlib import sha256
from pathlib import Path

from api.services.agent_processing.lifecycle.execution_graph.service_tools import create_service_tools
from api.services.agent_processing.service_capabilities.service_capability_analyzer import ServiceCapabilityAnalyzer
from api.services.agent_processing.service_capabilities.service_execution_engine import ServiceExecutionEngine
from api.services.agent_processing.tools.direct_application_interactions.file_system.file_system_service import FileSystemService
from api.services.agent_processing.tools.direct_application_interactions.file_system import text_file_write
from api.services.agent_processing.tools.direct_application_interactions.file_system.text_file_write import (
    LocalTextFileWriter,
    select_direct_text_write_artifact,
)
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_execution import (
    redact_tool_parameters_for_log,
)


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _artifact_id(path: Path) -> str:
    normalized_path = os.path.normpath(str(path))
    return f"file-{sha256(normalized_path.encode('utf-8')).hexdigest()[:24]}"


def _create_write_tool(tmp_path: Path):
    service = FileSystemService(write_roots=[tmp_path])
    analyzer = ServiceCapabilityAnalyzer(file_service=service)
    services = analyzer.discover_available_services()
    engine = ServiceExecutionEngine(analyzer)
    engine.register_service("file_service", service)
    result = asyncio.run(
        create_service_tools(
            service_execution_engine=engine,
            capability_analyzer=analyzer,
            services=services,
        )
    )
    tool = next(item for item in result.tools if item.name == "file_service_write_text_file")
    return tool


def test_text_write_tool_creates_utf8_file_and_verified_receipt(tmp_path: Path, caplog):
    tool = _create_write_tool(tmp_path)
    caplog.set_level(logging.INFO)
    target = tmp_path / "notes.txt"

    raw = asyncio.run(
        tool.ainvoke(
            {
                "path": str(target),
                "content": "café\n東京\n",
                "mode": "create",
            }
        )
    )
    payload = json.loads(raw)
    result = payload["result"]

    assert payload["success"] is True
    assert target.read_text(encoding="utf-8") == "café\n東京\n"
    assert "café" not in raw
    assert "東京" not in raw
    assert payload["parameters_used"]["content"] == "<redacted text:13 bytes>"
    assert result["operation"] == "create"
    assert result["mode"] == "create"
    assert result["sha256"] == _sha256(target)
    assert result["file_artifacts"] == [{
        "name": "notes.txt",
        "full_path": str(target),
        "operation": "create",
        "kind": "file",
        "sha256": _sha256(target),
    }]
    receipt = result["material_operation"]["receipts"][0]
    assert receipt["execution_state"] == "succeeded"
    assert receipt["verification_status"] == "verified"
    assert receipt["evidence"]["sha256"] == _sha256(target)
    assert payload["agent_task_artifact"] == {
        "artifact_id": _artifact_id(target),
        "display_name": "notes.txt",
        "local_path": str(target),
        "artifact_kind": "file",
        "operation": "create",
        "lifecycle": "verified",
        "preview": {"capability": "unknown"},
        "verification": {
            "status": "verified",
            "summary": f"Verified 13 bytes; SHA-256 {_sha256(target)}.",
        },
    }
    assert "café" not in json.dumps(payload["agent_task_artifact"], ensure_ascii=False)
    assert "東京" not in json.dumps(payload["agent_task_artifact"], ensure_ascii=False)
    assert "café\n東京\n" not in caplog.text
    assert "<redacted text:13 bytes>" in caplog.text


def test_text_write_tool_rejects_stale_overwrite_without_mutating_target(tmp_path: Path):
    tool = _create_write_tool(tmp_path)
    target = tmp_path / "existing.txt"
    target.write_text("original", encoding="utf-8")

    raw = asyncio.run(
        tool.ainvoke(
            {
                "path": str(target),
                "content": "replacement",
                "mode": "overwrite",
                "expected_sha256": "0" * 64,
            }
        )
    )
    payload = json.loads(raw)
    result = payload["result"]

    assert payload["success"] is False
    assert target.read_text(encoding="utf-8") == "original"
    assert result["error_type"] == "stale_target"
    receipt = result["material_operation"]["receipts"][0]
    assert receipt["execution_state"] == "not_started"
    assert receipt["verification_status"] == "not_applicable"


def test_text_write_tool_overwrites_then_appends_with_current_digest(tmp_path: Path):
    tool = _create_write_tool(tmp_path)
    target = tmp_path / "journal.txt"
    target.write_text("one\n", encoding="utf-8")

    overwrite_raw = asyncio.run(
        tool.ainvoke(
            {
                "path": str(target),
                "content": "two\n",
                "mode": "overwrite",
                "expected_sha256": _sha256(target),
            }
        )
    )
    overwrite_result = json.loads(overwrite_raw)["result"]
    assert overwrite_result["success"] is True
    assert target.read_text(encoding="utf-8") == "two\n"

    append_raw = asyncio.run(
        tool.ainvoke(
            {
                "path": str(target),
                "content": "three\n",
                "mode": "append",
                "expected_sha256": _sha256(target),
            }
        )
    )
    append_result = json.loads(append_raw)["result"]
    assert append_result["success"] is True
    assert append_result["operation"] == "modify"
    assert append_result["mode"] == "append"
    assert target.read_text(encoding="utf-8") == "two\nthree\n"
    receipt = append_result["material_operation"]["receipts"][0]
    assert receipt["requested_effect"]["mode"] == "append"


def test_text_write_tool_rejects_duplicate_create_and_symlink_target(tmp_path: Path):
    tool = _create_write_tool(tmp_path)
    existing = tmp_path / "existing.txt"
    existing.write_text("keep", encoding="utf-8")

    duplicate_raw = asyncio.run(
        tool.ainvoke(
            {"path": str(existing), "content": "replace", "mode": "create"}
        )
    )
    duplicate_result = json.loads(duplicate_raw)["result"]
    assert duplicate_result["success"] is False
    assert existing.read_text(encoding="utf-8") == "keep"

    linked = tmp_path / "linked.txt"
    linked.symlink_to(existing)
    link_raw = asyncio.run(
        tool.ainvoke(
            {"path": str(linked), "content": "replace", "mode": "overwrite"}
        )
    )
    link_result = json.loads(link_raw)["result"]
    assert link_result["success"] is False
    assert link_result["error_type"] == "invalid_path_or_mode"
    assert existing.read_text(encoding="utf-8") == "keep"


def test_text_write_tool_rejects_missing_parent_without_creating_target(tmp_path: Path):
    tool = _create_write_tool(tmp_path)
    target = tmp_path / "missing-parent" / "notes.txt"

    raw = asyncio.run(
        tool.ainvoke(
            {"path": str(target), "content": "do not write", "mode": "create"}
        )
    )
    result = json.loads(raw)["result"]

    assert result["success"] is False
    assert result["error_type"] == "parent_directory_missing"
    assert not target.exists()


def test_text_writer_rejects_unknown_mode_without_mutating_target(tmp_path: Path):
    target = tmp_path / "existing.txt"
    target.write_text("keep", encoding="utf-8")
    writer = LocalTextFileWriter([tmp_path])

    result = asyncio.run(
        writer.write_text_file(
            path=str(target),
            content="replace",
            mode="replace",
        )
    )

    assert result["success"] is False
    assert result["error_type"] == "invalid_mode"
    assert target.read_text(encoding="utf-8") == "keep"


def test_tool_parameter_log_redaction_removes_text_payload():
    parameters = redact_tool_parameters_for_log(
        {"path": "/tmp/notes.txt", "content": "private café text"}
    )

    assert parameters == {
        "path": "/tmp/notes.txt",
        "content": "<redacted text:18 bytes>",
    }


def test_text_write_tool_schema_requires_direct_content_and_write_mode(tmp_path: Path):
    tool = _create_write_tool(tmp_path)
    schema = tool.args_schema.model_json_schema()

    assert schema["properties"]["content"]["type"] == "string"
    assert schema["properties"]["mode"]["enum"] == ["create", "overwrite", "append"]
    assert "shell quoting" in schema["properties"]["content"]["description"]
    assert "expected_sha256" in schema["properties"]


def test_text_write_tool_projects_failed_verification_without_reason_text(
    tmp_path: Path,
    monkeypatch,
):
    tool = _create_write_tool(tmp_path)
    target = tmp_path / "verification-failed.txt"
    monkeypatch.setattr(
        text_file_write,
        "verify_file_operations",
        lambda _declarations: ([], ["private diagnostic " * 1_000]),
    )

    raw = asyncio.run(
        tool.ainvoke(
            {
                "path": str(target),
                "content": "private direct-write content",
                "mode": "create",
            }
        )
    )
    payload = json.loads(raw)

    assert payload["truncated"] is True
    assert payload["agent_task_artifact"] == {
        "artifact_id": _artifact_id(target),
        "display_name": "verification-failed.txt",
        "local_path": str(target),
        "artifact_kind": "file",
        "operation": "create",
        "lifecycle": "failed",
        "preview": {"capability": "unknown"},
        "verification": {
            "status": "failed",
            "summary": "Verification failed: postcondition_verification_failed.",
        },
    }
    serialized_artifact = json.dumps(payload["agent_task_artifact"], ensure_ascii=False)
    assert "private direct-write content" not in serialized_artifact
    assert "private diagnostic" not in serialized_artifact
    assert len(payload["agent_task_artifact"]["verification"]["summary"]) < 2_000


def test_direct_text_artifact_selector_rejects_missing_receipt_and_invalid_mode(
    tmp_path: Path,
):
    target = tmp_path / "invalid-mode.txt"
    writer = LocalTextFileWriter([tmp_path])
    result = asyncio.run(
        writer.write_text_file(
            path=str(target),
            content="do not retain",
            mode="replace",
        )
    )

    assert result["error_type"] == "invalid_mode"
    assert select_direct_text_write_artifact(result) is None
    assert select_direct_text_write_artifact({"success": True, "file_path": str(target)}) is None


def test_service_execution_engine_never_projects_a_shell_receipt(tmp_path: Path):
    class ShellLikeService:
        async def execute_command(self) -> dict:
            return {
                "success": True,
                "material_operation": {
                    "contract_version": 1,
                    "material_write": True,
                    "receipts": [
                        {
                            "entity": {
                                "entity_type": "file",
                                "source_system": "filesystem",
                                "source_scope": {"host_scope": "local"},
                                "external_id": str(tmp_path / "shell-created.txt"),
                            },
                            "requested_effect": {"operation": "create"},
                            "execution_state": "succeeded",
                            "observed_postcondition": {
                                "file_artifact": {
                                    "full_path": str(tmp_path / "shell-created.txt"),
                                    "operation": "create",
                                    "kind": "file",
                                },
                            },
                            "verification_status": "verified",
                            "evidence": {
                                "file_artifact": {
                                    "full_path": str(tmp_path / "shell-created.txt"),
                                    "operation": "create",
                                    "kind": "file",
                                },
                                "bytes_written": 1,
                                "sha256": "0" * 64,
                            },
                            "discrepancy": {},
                        },
                    ],
                },
            }

    engine = ServiceExecutionEngine()
    engine.register_service("shell_service", ShellLikeService())
    result = asyncio.run(engine.execute_service_method("shell_service", "execute_command", {}))

    assert result.success is True
    assert result.agent_task_artifact is None
