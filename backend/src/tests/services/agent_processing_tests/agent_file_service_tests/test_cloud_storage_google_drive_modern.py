"""Tests for modern Google Drive detection and the hidden-dir-aware find command."""

from __future__ import annotations

import asyncio
import os

import pytest

from api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval.cloud_storage_service import (
    CloudStorageService,
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


@pytest.mark.asyncio
async def test_find_command_includes_shortcut_targets_and_is_case_insensitive(monkeypatch):
    captured = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"", b"")

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["argv"] = list(args)
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    service = CloudStorageService()
    await service._search_in_path("/fake/drive/root", "PayLink")

    argv = captured["argv"]
    assert argv[0] == "find"
    # The shortcut subtree must be preserved (excluded from the hidden-dir prune).
    assert ".shortcut-targets-by-id" in argv
    # Matching must be case-insensitive.
    assert "-iname" in argv
    assert "*PayLink*" in argv
    # A blanket hidden-dir exclusion must NOT be present anymore.
    assert "*/.*" not in argv
