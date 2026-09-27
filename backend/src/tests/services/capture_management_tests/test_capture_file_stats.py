"""Tests for CaptureManagementService.get_capture_stats() flat-temp file counting.

Regression coverage for the bug where automatic-capture screenshots written by
the current Swift capture bridge (``capture_<timestamp>.png`` directly in the
flat temp directory, with no per-date subfolder) were silently excluded from
the Capture Management stats because the scanner only recognized the older
``temp_capture_`` naming convention.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from api.core.services.capture_management_service import CaptureManagementService


def _set_mtime(path: Path, when: datetime) -> None:
    timestamp = when.timestamp()
    os.utime(path, (timestamp, timestamp))


@pytest.fixture
def stats_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CaptureManagementService:
    """A CaptureManagementService pointed at isolated tmp_path capture directories."""
    structured_dir = tmp_path / "data" / "captures"
    temp_dir = tmp_path / "data" / "temp"
    structured_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    class _FakeStorageService:
        def __init__(self) -> None:
            self.base_path = tmp_path

    service = CaptureManagementService(storage_service=_FakeStorageService())
    assert service.captures_path_structured == structured_dir
    assert service.captures_path_temp_flat == temp_dir
    return service


@pytest.mark.asyncio
async def test_current_swift_bridge_naming_is_counted_in_flat_temp(stats_service: CaptureManagementService) -> None:
    """capture_<timestamp>.png files (the current live naming) must be counted."""
    temp_dir = stats_service.captures_path_temp_flat
    recent_file = temp_dir / "capture_20260913_153805.png"
    recent_file.write_bytes(b"x" * 1000)
    _set_mtime(recent_file, datetime.now() - timedelta(days=1))

    stats = await stats_service.get_capture_stats()

    assert stats["total_files"] == 1
    assert stats["files_last_7_days"] == 1
    assert stats["files_last_30_days"] == 1
    assert stats["total_size_bytes"] == 1000


@pytest.mark.asyncio
async def test_legacy_and_fallback_naming_conventions_are_still_counted(stats_service: CaptureManagementService) -> None:
    """Older prefixes (temp_capture_, fallback_capture_, fallback_temp_) remain recognized."""
    temp_dir = stats_service.captures_path_temp_flat
    names = [
        "temp_capture_20260913_120000_SomeApp.png",
        "fallback_capture_1789328959909.png",
        "fallback_temp_1789328959909.png",
    ]
    for name in names:
        file_path = temp_dir / name
        file_path.write_bytes(b"y" * 500)
        _set_mtime(file_path, datetime.now())

    stats = await stats_service.get_capture_stats()

    assert stats["total_files"] == len(names)
    assert stats["files_last_7_days"] == len(names)


@pytest.mark.asyncio
async def test_flat_temp_files_bucket_by_modification_time_not_filename(stats_service: CaptureManagementService) -> None:
    """Date bucketing uses file mtime, since fallback filenames embed a raw
    millisecond epoch rather than a parseable YYYYMMDD_HHMMSS date string."""
    temp_dir = stats_service.captures_path_temp_flat

    old_file = temp_dir / "capture_20260101_000000.png"
    old_file.write_bytes(b"z" * 200)
    _set_mtime(old_file, datetime.now() - timedelta(days=40))

    recent_file = temp_dir / "capture_20260101_000001.png"
    recent_file.write_bytes(b"z" * 200)
    _set_mtime(recent_file, datetime.now() - timedelta(days=2))

    stats = await stats_service.get_capture_stats()

    assert stats["total_files"] == 2
    assert stats["files_last_30_days"] == 1
    assert stats["files_last_7_days"] == 1


@pytest.mark.asyncio
async def test_non_capture_files_in_temp_dir_are_ignored(stats_service: CaptureManagementService) -> None:
    """Unrelated temp files (scripts, non-png, non-capture-prefixed) are not counted."""
    temp_dir = stats_service.captures_path_temp_flat
    (temp_dir / "capture_script.scpt").write_text("#!/usr/bin/osascript")
    (temp_dir / "insert_script.scpt").write_text("#!/usr/bin/osascript")
    (temp_dir / "some_other_temp_file.png").write_bytes(b"unrelated")

    stats = await stats_service.get_capture_stats()

    assert stats["total_files"] == 0


@pytest.mark.asyncio
async def test_structured_directory_counting_is_unchanged(stats_service: CaptureManagementService) -> None:
    """Structured per-date directories (data/captures/YYYY-MM-DD/) keep working as before."""
    structured_dir = stats_service.captures_path_structured
    recent_date_dir = structured_dir / datetime.now().strftime("%Y-%m-%d")
    recent_date_dir.mkdir(parents=True, exist_ok=True)
    (recent_date_dir / "capture_20260913_090000_TestApp.png").write_bytes(b"a" * 300)

    old_date_dir = structured_dir / (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
    old_date_dir.mkdir(parents=True, exist_ok=True)
    (old_date_dir / "capture_20260101_090000_TestApp.png").write_bytes(b"b" * 300)

    stats = await stats_service.get_capture_stats()

    assert stats["total_files"] == 2
    assert stats["files_last_30_days"] == 1
