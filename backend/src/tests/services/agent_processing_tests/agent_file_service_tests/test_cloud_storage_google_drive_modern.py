"""Tests for modern Google Drive detection and the hidden-dir-aware find command."""

from __future__ import annotations

import asyncio
import os

import pytest

from api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval import (
    cloud_storage_service as cloud_module,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval.cloud_storage_service import (
    CloudStorageService,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval.search_subprocess import (
    SearchProcessOutcome,
)


@pytest.mark.asyncio
async def test_detects_modern_cloudstorage_google_drive(tmp_path, monkeypatch):
    # Simulate a real Google Drive for Desktop mount under a fake HOME.
    drive_root = tmp_path / "Library" / "CloudStorage" / "GoogleDrive-user@example.com"
    drive_root.mkdir(parents=True)
    (drive_root / "My Drive").mkdir()  # non-empty so it counts as a sync folder

    real_expanduser = os.path.expanduser

    def fake_expanduser(path):
        if isinstance(path, str) and path.startswith("~"):
            return path.replace("~", str(tmp_path), 1)
        return real_expanduser(path)

    monkeypatch.setattr(os.path, "expanduser", fake_expanduser)

    service = CloudStorageService()
    sync_folders = await service._detect_sync_folders()

    assert "google_drive" in sync_folders
    assert str(drive_root) in sync_folders["google_drive"]


def _outcome(lines=(), *, timed_out=False, returncode=0, stderr_tail=""):
    return SearchProcessOutcome(
        lines=list(lines),
        timed_out=timed_out,
        returncode=returncode,
        stderr_tail=stderr_tail,
        truncated=False,
    )


@pytest.mark.asyncio
async def test_find_command_includes_shortcut_targets_and_is_case_insensitive(monkeypatch):
    captured = {}

    async def fake_runner(argv, *, timeout_seconds, max_lines=None):
        captured["argv"] = list(argv)
        captured["timeout_seconds"] = timeout_seconds
        return _outcome()

    monkeypatch.setattr(cloud_module, "run_bounded_search_process", fake_runner)

    service = CloudStorageService()
    await service._search_in_path("/fake/drive/root", "PayLink")
    assert captured["timeout_seconds"] == 30.0

    argv = captured["argv"]
    assert argv[0] == "find"
    # The shortcut subtree must be preserved (excluded from the hidden-dir prune).
    assert ".shortcut-targets-by-id" in argv
    # Matching must be case-insensitive.
    assert "-iname" in argv
    assert "*PayLink*" in argv
    # A blanket hidden-dir exclusion must NOT be present anymore.
    assert "*/.*" not in argv


@pytest.mark.asyncio
async def test_find_nonzero_exit_with_permission_errors_keeps_matches_and_is_complete(tmp_path, monkeypatch):
    match = tmp_path / "PayLink Guide.pdf"
    match.write_bytes(b"%PDF")

    async def fake_runner(argv, *, timeout_seconds, max_lines=None):
        return _outcome(
            [str(match)],
            returncode=1,
            stderr_tail="find: /drive/locked: Permission denied\nfind: /drive/x: Operation not permitted\n",
        )

    monkeypatch.setattr(cloud_module, "run_bounded_search_process", fake_runner)

    files, reason = await CloudStorageService()._search_in_path_with_coverage(str(tmp_path), "PayLink")

    assert [entry["path"] for entry in files] == [str(match)]
    assert reason is None


@pytest.mark.asyncio
async def test_find_nonzero_exit_with_other_errors_keeps_matches_and_reports_reason(tmp_path, monkeypatch):
    match = tmp_path / "PayLink Guide.pdf"
    match.write_bytes(b"%PDF")

    async def fake_runner(argv, *, timeout_seconds, max_lines=None):
        return _outcome([str(match)], returncode=1, stderr_tail="find: fts_read: Input/output error\n")

    monkeypatch.setattr(cloud_module, "run_bounded_search_process", fake_runner)

    files, reason = await CloudStorageService()._search_in_path_with_coverage(str(tmp_path), "PayLink")

    assert [entry["path"] for entry in files] == [str(match)]
    assert reason == "find exited with status 1"


@pytest.mark.asyncio
async def test_find_timeout_keeps_partial_matches_and_reports_reason(tmp_path, monkeypatch):
    match = tmp_path / "PayLink Early.pdf"
    match.write_bytes(b"%PDF")

    async def fake_runner(argv, *, timeout_seconds, max_lines=None):
        return _outcome([str(match)], timed_out=True, returncode=-15)

    monkeypatch.setattr(cloud_module, "run_bounded_search_process", fake_runner)

    service = CloudStorageService()
    files, reason = await service._search_in_path_with_coverage(str(tmp_path), "PayLink")
    assert [entry["path"] for entry in files] == [str(match)]
    assert reason == "timed out after 30s"

    legacy_files = await service._search_in_path(str(tmp_path), "PayLink")
    assert [entry["path"] for entry in legacy_files] == [str(match)]


@pytest.mark.asyncio
async def test_search_cloud_files_with_coverage_collects_incomplete_paths(monkeypatch):
    service = CloudStorageService()

    async def fake_detect():
        return {
            "searchable_paths": ["/drive/a", "/drive/b", "/drive/c"],
            "volumes_detected": {},
            "sync_folders_detected": {},
        }

    async def fake_search(search_path, filename):
        if search_path == "/drive/a":
            return [{"name": "hit.pdf", "path": "/drive/a/hit.pdf"}], None
        if search_path == "/drive/b":
            return [], "timed out after 30s"
        raise RuntimeError("mount vanished")

    monkeypatch.setattr(service, "detect_cloud_storage", fake_detect)
    monkeypatch.setattr(service, "_search_in_path_with_coverage", fake_search)

    coverage = await service.search_cloud_files_with_coverage("hit")

    assert [entry["path"] for entry in coverage["files"]] == ["/drive/a/hit.pdf"]
    assert coverage["files"][0]["is_cloud_file"] is True
    assert coverage["incomplete_paths"] == [
        {"path": "/drive/b", "reason": "timed out after 30s"},
        {"path": "/drive/c", "reason": "search error: mount vanished"},
    ]
    assert [entry["path"] for entry in await service.search_cloud_files("hit")] == ["/drive/a/hit.pdf"]
