from __future__ import annotations

import asyncio
import json
import logging
import os
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from api.services.agent_processing.lifecycle.execution_graph.service_tools import create_service_tools
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_execution import (
    redact_tool_parameters_for_log,
)
from api.services.agent_processing.lifecycle.execution_graph.system_prompts import AGENT_SYSTEM_PROMPT_TEMPLATE
from api.services.agent_processing.service_capabilities.service_capability_analyzer import ServiceCapabilityAnalyzer
from api.services.agent_processing.service_capabilities.service_execution_engine import (
    ServiceExecutionEngine,
    redact_text_parameters_for_log,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system import (
    file_system_service as file_system_service_module,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system import text_file_edit
from api.services.agent_processing.tools.direct_application_interactions.file_system.file_system_service import (
    FileSystemService,
)


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _artifact_id(path: Path) -> str:
    normalized_path = os.path.normpath(str(path))
    return f"file-{sha256(normalized_path.encode('utf-8')).hexdigest()[:24]}"


def _create_edit_tool(tmp_path: Path):
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
    return next(item for item in result.tools if item.name == "file_service_edit_text_file")


def _edit(service: FileSystemService, path: Path, edits: list[dict], expected_sha256: str | None = None) -> dict:
    return asyncio.run(service.edit_text_file(path=str(path), edits=edits, expected_sha256=expected_sha256))


def test_edit_tool_replaces_unique_text_with_verified_receipt_and_redacted_logs(tmp_path: Path, caplog):
    tool = _create_edit_tool(tmp_path)
    caplog.set_level(logging.INFO)
    target = tmp_path / "config.py"
    target.write_text("alpha = 1\nsecret_marker = 'old café'\nomega = 3\n", encoding="utf-8")
    before_sha256 = _sha256(target)

    raw = asyncio.run(
        tool.ainvoke(
            {
                "path": str(target),
                "edits": [{"old_text": "secret_marker = 'old café'", "new_text": "secret_marker = 'new 東京'"}],
            }
        )
    )
    payload = json.loads(raw)
    result = payload["result"]

    assert payload["success"] is True
    assert target.read_text(encoding="utf-8") == "alpha = 1\nsecret_marker = 'new 東京'\nomega = 3\n"
    assert result["edits_applied"] == [{"index": 0, "replacements": 1}]
    assert result["operation"] == "modify"
    assert result["previous_sha256"] == before_sha256
    assert result["sha256"] == _sha256(target)
    receipt = result["material_operation"]["receipts"][0]
    assert receipt["execution_state"] == "succeeded"
    assert receipt["verification_status"] == "verified"
    assert payload["agent_task_artifact"]["artifact_id"] == _artifact_id(target)
    assert payload["agent_task_artifact"]["lifecycle"] == "verified"
    assert payload["parameters_used"]["edits"] == "<redacted edits:1>"
    assert "old café" not in raw and "new 東京" not in raw
    assert "old café" not in caplog.text and "new 東京" not in caplog.text


def test_edit_applies_ordered_edits_against_the_running_result(tmp_path: Path):
    service = FileSystemService(write_roots=[tmp_path])
    target = tmp_path / "ordered.txt"
    target.write_text("one two\n", encoding="utf-8")

    result = _edit(
        service,
        target,
        [
            {"old_text": "one", "new_text": "three"},
            {"old_text": "three two", "new_text": "done"},
        ],
    )

    assert result["success"] is True
    assert target.read_text(encoding="utf-8") == "done\n"
    assert result["edits_applied"] == [{"index": 0, "replacements": 1}, {"index": 1, "replacements": 1}]


def test_edit_replace_all_reports_every_replacement(tmp_path: Path):
    service = FileSystemService(write_roots=[tmp_path])
    target = tmp_path / "repeat.txt"
    target.write_text("x y x y x\n", encoding="utf-8")

    result = _edit(service, target, [{"old_text": "x", "new_text": "z", "replace_all": True}])

    assert result["success"] is True
    assert target.read_text(encoding="utf-8") == "z y z y z\n"
    assert result["edits_applied"] == [{"index": 0, "replacements": 3}]


def test_edit_deletes_text_when_new_text_is_empty(tmp_path: Path):
    service = FileSystemService(write_roots=[tmp_path])
    target = tmp_path / "delete.txt"
    target.write_text("keep\nremove me\nkeep too\n", encoding="utf-8")

    result = _edit(service, target, [{"old_text": "remove me\n", "new_text": ""}])

    assert result["success"] is True
    assert target.read_text(encoding="utf-8") == "keep\nkeep too\n"


def test_edit_ambiguous_match_fails_without_changing_the_file(tmp_path: Path):
    service = FileSystemService(write_roots=[tmp_path])
    target = tmp_path / "ambiguous.txt"
    target.write_text("dup\ndup\n", encoding="utf-8")

    result = _edit(service, target, [{"old_text": "dup", "new_text": "single"}])

    assert result["success"] is False
    assert result["error_type"] == "old_text_ambiguous"
    assert "2 places" in result["error"]
    assert result["previous_sha256"] == _sha256(target)
    assert target.read_text(encoding="utf-8") == "dup\ndup\n"


def test_edit_missing_text_fails_and_hints_at_crlf_and_whitespace(tmp_path: Path):
    service = FileSystemService(write_roots=[tmp_path])
    crlf = tmp_path / "crlf.txt"
    crlf.write_bytes(b"first\r\nsecond\r\n")
    spaced = tmp_path / "spaced.txt"
    spaced.write_text("def f():\n        return 1\n", encoding="utf-8")

    crlf_result = _edit(service, crlf, [{"old_text": "first\nsecond", "new_text": "x"}])
    spaced_result = _edit(service, spaced, [{"old_text": "def f():\n    return 1", "new_text": "x"}])
    plain_result = _edit(service, spaced, [{"old_text": "absent", "new_text": "x"}])

    assert crlf_result["error_type"] == "old_text_not_found"
    assert "CRLF" in crlf_result["error"]
    assert spaced_result["error_type"] == "old_text_not_found"
    assert "different whitespace" in spaced_result["error"]
    assert plain_result["error_type"] == "old_text_not_found"
    assert "CRLF" not in plain_result["error"] and "whitespace" not in plain_result["error"]
    assert crlf.read_bytes() == b"first\r\nsecond\r\n"
    assert spaced.read_text(encoding="utf-8") == "def f():\n        return 1\n"


def test_edit_failure_in_a_later_edit_leaves_the_file_untouched(tmp_path: Path):
    service = FileSystemService(write_roots=[tmp_path])
    target = tmp_path / "atomic.txt"
    target.write_text("a\nb\n", encoding="utf-8")
    before = target.read_bytes()

    result = _edit(
        service,
        target,
        [{"old_text": "a", "new_text": "A"}, {"old_text": "missing", "new_text": "M"}],
    )

    assert result["success"] is False
    assert result["error_type"] == "old_text_not_found"
    assert result["error"].startswith("Edit 1:")
    assert target.read_bytes() == before


def test_edit_rejects_noop_and_self_canceling_edits(tmp_path: Path):
    service = FileSystemService(write_roots=[tmp_path])
    target = tmp_path / "noop.txt"
    target.write_text("a\n", encoding="utf-8")

    identical = _edit(service, target, [{"old_text": "a", "new_text": "a"}])
    canceling = _edit(
        service,
        target,
        [{"old_text": "a", "new_text": "b"}, {"old_text": "b", "new_text": "a"}],
    )
    empty_old = _edit(service, target, [{"old_text": "", "new_text": "a"}])

    assert identical["error_type"] == "noop_edit"
    assert canceling["error_type"] == "noop_edit"
    assert empty_old["error_type"] == "empty_old_text"
    assert target.read_text(encoding="utf-8") == "a\n"


def test_edit_validates_the_edit_list_shape(tmp_path: Path):
    service = FileSystemService(write_roots=[tmp_path])
    target = tmp_path / "shape.txt"
    target.write_text("a\n", encoding="utf-8")

    no_edits = _edit(service, target, [])
    too_many = _edit(service, target, [{"old_text": "a", "new_text": "b"}] * 51)
    not_object = _edit(service, target, ["a"])
    bad_types = _edit(service, target, [{"old_text": "a", "new_text": 5}])

    assert no_edits["error_type"] == "no_edits"
    assert too_many["error_type"] == "too_many_edits"
    assert not_object["error_type"] == "invalid_edit"
    assert bad_types["error_type"] == "invalid_edit"
    assert target.read_text(encoding="utf-8") == "a\n"


def test_edit_refuses_a_stale_expected_digest_without_changing_the_file(tmp_path: Path):
    service = FileSystemService(write_roots=[tmp_path])
    target = tmp_path / "stale.txt"
    target.write_text("original\n", encoding="utf-8")

    result = _edit(service, target, [{"old_text": "original", "new_text": "changed"}], expected_sha256="0" * 64)
    matching = _edit(
        service,
        target,
        [{"old_text": "original", "new_text": "changed"}],
        expected_sha256=_sha256(target),
    )

    assert result["success"] is False
    assert result["error_type"] == "stale_target"
    assert result["previous_sha256"] == sha256(b"original\n").hexdigest()
    assert matching["success"] is True
    assert target.read_text(encoding="utf-8") == "changed\n"


def test_edit_preserves_crlf_line_endings_and_unicode(tmp_path: Path):
    service = FileSystemService(write_roots=[tmp_path])
    target = tmp_path / "windows.txt"
    target.write_bytes("héllo\r\nwörld\r\n".encode("utf-8"))

    result = _edit(service, target, [{"old_text": "wörld", "new_text": "wörld 東京"}])

    assert result["success"] is True
    assert target.read_bytes() == "héllo\r\nwörld 東京\r\n".encode("utf-8")


def test_edit_refuses_binary_non_utf8_oversized_and_missing_files(tmp_path: Path, monkeypatch):
    service = FileSystemService(write_roots=[tmp_path])
    binary = tmp_path / "binary.bin"
    binary.write_bytes(b"ab\x00cd")
    latin = tmp_path / "latin.txt"
    latin.write_bytes("caf\xe9".encode("latin-1"))
    big = tmp_path / "big.txt"
    big.write_text("a" * 20, encoding="utf-8")
    missing = tmp_path / "missing.txt"
    edits = [{"old_text": "a", "new_text": "b"}]

    binary_result = _edit(service, binary, edits)
    latin_result = _edit(service, latin, edits)
    missing_result = _edit(service, missing, edits)
    monkeypatch.setattr(text_file_edit, "MAX_EDIT_FILE_BYTES", 10)
    big_result = _edit(service, big, edits)

    assert binary_result["error_type"] == "not_text_file"
    assert latin_result["error_type"] == "not_utf8"
    assert missing_result["error_type"] == "invalid_path_or_mode"
    assert big_result["error_type"] == "file_too_large"
    assert binary.read_bytes() == b"ab\x00cd"
    assert big.read_text(encoding="utf-8") == "a" * 20
    assert not missing.exists()


def test_edit_refuses_symlinks_directories_and_paths_outside_the_roots(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    service = FileSystemService(write_roots=[root])
    real = root / "real.txt"
    real.write_text("a\n", encoding="utf-8")
    link = root / "link.txt"
    link.symlink_to(real)
    outside = tmp_path / "outside.txt"
    outside.write_text("a\n", encoding="utf-8")
    directory = root / "folder"
    directory.mkdir()
    edits = [{"old_text": "a", "new_text": "b"}]

    link_result = _edit(service, link, edits)
    outside_result = _edit(service, outside, edits)
    directory_result = _edit(service, directory, edits)

    assert link_result["success"] is False
    assert link_result["error_type"] == "invalid_path_or_mode"
    assert outside_result["success"] is False
    assert outside_result["error_type"] == "invalid_path_or_mode"
    assert directory_result["success"] is False
    assert directory_result["error_type"] == "target_not_regular_file"
    assert real.read_text(encoding="utf-8") == "a\n"
    assert outside.read_text(encoding="utf-8") == "a\n"


def test_edit_refuses_protected_runtime_paths_before_reading(tmp_path: Path, monkeypatch):
    service = FileSystemService(write_roots=[tmp_path])
    target = tmp_path / "protected.json"
    target.write_text('{"token": "secret-host"}', encoding="utf-8")
    monkeypatch.setattr(file_system_service_module, "is_protected_runtime_path", lambda _path: True)

    async def fail_read(**_kwargs):
        raise AssertionError("a protected path must be refused before it is read")

    monkeypatch.setattr(service._text_file_writer, "read_text_snapshot", fail_read)

    result = _edit(service, target, [{"old_text": "secret-host", "new_text": "x"}])

    assert result["success"] is False
    assert result["error_type"] == "policy_blocked"
    assert result["error"] == file_system_service_module.PROTECTED_RUNTIME_REFUSAL
    assert "secret-host" not in json.dumps(result)
    assert target.read_text(encoding="utf-8") == '{"token": "secret-host"}'


def test_edit_writes_once_through_write_text_file_with_the_digest_that_was_read(tmp_path: Path, monkeypatch):
    service = FileSystemService(write_roots=[tmp_path])
    target = tmp_path / "delegate.txt"
    target.write_text("before\n", encoding="utf-8")
    calls: list[dict] = []

    async def fake_write_text_file(**kwargs):
        calls.append(kwargs)
        return {"success": True, "file_path": kwargs["path"]}

    monkeypatch.setattr(service, "write_text_file", fake_write_text_file)

    result = _edit(service, target, [{"old_text": "before", "new_text": "after"}])

    assert calls == [
        {
            "path": str(target),
            "content": "after\n",
            "mode": "overwrite",
            "expected_sha256": sha256(b"before\n").hexdigest(),
        }
    ]
    assert result == {
        "success": True,
        "file_path": str(target),
        "edits_applied": [{"index": 0, "replacements": 1}],
    }


def test_edit_returns_the_write_failure_unchanged_when_the_file_changed_after_reading(tmp_path: Path, monkeypatch):
    service = FileSystemService(write_roots=[tmp_path])
    target = tmp_path / "race.txt"
    target.write_text("before\n", encoding="utf-8")
    real_write = service.write_text_file

    async def write_after_concurrent_change(**kwargs):
        target.write_text("someone else wrote this\n", encoding="utf-8")
        return await real_write(**kwargs)

    monkeypatch.setattr(service, "write_text_file", write_after_concurrent_change)

    result = _edit(service, target, [{"old_text": "before", "new_text": "after"}])

    assert result["success"] is False
    assert result["error_type"] == "stale_target"
    assert "edits_applied" not in result
    assert target.read_text(encoding="utf-8") == "someone else wrote this\n"


def test_edit_parameter_redaction_covers_both_log_paths():
    parameters = {
        "path": "/tmp/a.py",
        "edits": [{"old_text": "private old", "new_text": "private new"}],
        "expected_sha256": None,
    }

    expected = {"path": "/tmp/a.py", "edits": "<redacted edits:1>", "expected_sha256": None}

    assert redact_tool_parameters_for_log(parameters) == expected
    assert redact_text_parameters_for_log(parameters) == expected
    assert redact_tool_parameters_for_log({"edits": "not a list"}) == {"edits": "not a list"}


def test_edit_tool_schema_enforces_edit_shape_and_digest_pattern(tmp_path: Path):
    tool = _create_edit_tool(tmp_path)
    schema = tool.args_schema
    valid_edit = {"old_text": "a", "new_text": "b"}

    assert schema.model_validate({"path": "/x", "edits": [valid_edit]}).edits[0].replace_all is False
    for invalid in (
        {"path": "/x", "edits": []},
        {"path": "/x", "edits": [{"old_text": "", "new_text": "b"}]},
        {"path": "/x", "edits": [valid_edit] * 51},
        {"path": "/x", "edits": [valid_edit], "expected_sha256": "ABC"},
        {"path": "/x", "edits": [{"old_text": "a"}]},
    ):
        with pytest.raises(ValidationError):
            schema.model_validate(invalid)


def test_edit_tool_is_advertised_in_the_prompt_and_capability_docs(tmp_path: Path):
    service = FileSystemService(write_roots=[tmp_path])
    methods = {method["name"]: method for method in service.get_service_capabilities()["methods"]}

    assert "edit_text_file" in methods
    assert "no approval prompt" in methods["edit_text_file"]["slim_doc"]
    assert "edit_text_file" in methods["write_text_file"]["slim_doc"]
    assert "file_service_edit_text_file" in AGENT_SYSTEM_PROMPT_TEMPLATE
