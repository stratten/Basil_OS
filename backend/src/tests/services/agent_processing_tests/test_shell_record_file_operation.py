"""The shell ``record`` file operation registers a file an earlier command in this run already wrote."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from api.services.agent_processing.lifecycle.finalization.file_result_extraction import (
    extract_files_from_steps,
)
from api.services.agent_processing.shared.agent_runtime_context import (
    AGENT_RUN_STARTED_AT_KEY,
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_file_artifacts import (
    prepare_file_operations,
    verify_file_operations,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_service import (
    ShellService,
)


def test_record_of_file_written_during_run_produces_create_card(tmp_path: Path):
    run_started_at = time.time() - 1
    target = tmp_path / "rebase_2026_connection_report.csv"
    target.write_text("name,score\nAda,14\n")

    declarations = prepare_file_operations(
        [{"operation": "record", "path": str(target)}],
        [tmp_path],
        recorded_after=run_started_at,
    )
    artifacts, errors = verify_file_operations(declarations)

    assert errors == []
    assert [(a["full_path"], a["operation"], a["kind"]) for a in artifacts] == [
        (str(target), "create", "file")
    ]
    files = extract_files_from_steps([{"result": {"success": True, "file_artifacts": artifacts}}])
    assert files == [
        {"name": target.name, "full_path": str(target), "operation": "create", "kind": "file"}
    ]


@pytest.mark.skipif(not hasattr(os.stat_result, "st_birthtime"), reason="needs file birth time")
def test_record_of_preexisting_file_changed_during_run_reports_modify(tmp_path: Path):
    target = tmp_path / "notes.md"
    target.write_text("before\n")
    run_started_at = target.stat().st_birthtime + 0.05
    time.sleep(0.1)
    target.write_text("after\n")

    declarations = prepare_file_operations(
        [{"operation": "record", "path": str(target)}],
        [tmp_path],
        recorded_after=run_started_at,
    )
    artifacts, errors = verify_file_operations(declarations)

    assert errors == []
    assert artifacts[0]["operation"] == "modify"


def test_record_rejects_file_unchanged_since_run_started(tmp_path: Path):
    target = tmp_path / "old.csv"
    target.write_text("stale\n")
    old_time = time.time() - 3600
    os.utime(target, (old_time, old_time))

    with pytest.raises(ValueError, match="not created or modified during this task"):
        prepare_file_operations(
            [{"operation": "record", "path": str(target)}],
            [tmp_path],
            recorded_after=time.time() - 60,
        )


def test_record_rejects_missing_file_and_directories(tmp_path: Path):
    with pytest.raises(ValueError, match="not an existing regular file"):
        prepare_file_operations(
            [{"operation": "record", "path": str(tmp_path / "missing.csv")}],
            [tmp_path],
            recorded_after=time.time() - 60,
        )
    with pytest.raises(ValueError, match="not an existing regular file"):
        prepare_file_operations(
            [{"operation": "record", "path": str(tmp_path)}],
            [tmp_path],
            recorded_after=time.time() - 60,
        )


def test_record_requires_active_run_start_time(tmp_path: Path):
    target = tmp_path / "report.csv"
    target.write_text("x\n")

    with pytest.raises(ValueError, match="requires an active agent task run"):
        prepare_file_operations([{"operation": "record", "path": str(target)}], [tmp_path])


def test_record_outside_allowed_roots_is_rejected(tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("x\n")

    with pytest.raises(ValueError, match="outside allowed roots"):
        prepare_file_operations(
            [{"operation": "record", "path": str(outside)}],
            [allowed],
            recorded_after=time.time() - 60,
        )


def test_shell_service_records_existing_file_with_read_only_command(tmp_path: Path):
    service = ShellService()
    service._home_root = tmp_path.resolve()
    target = tmp_path / "rebase_2026_connection_report.csv"
    target.write_text("name,score\nAda,14\n")
    token = set_current_agent_context({AGENT_RUN_STARTED_AT_KEY: time.time() - 5})
    try:
        result = asyncio.run(
            service.execute_command(
                "ls",
                ["-la", str(target)],
                cwd=str(tmp_path),
                file_operations=[{"operation": "record", "path": str(target)}],
                skip_approval_check=True,
            )
        )
    finally:
        reset_current_agent_context(token)

    assert result["success"] is True
    assert [a["full_path"] for a in result["file_artifacts"]] == [str(target.resolve())]
    assert result["file_artifacts"][0]["operation"] == "create"
