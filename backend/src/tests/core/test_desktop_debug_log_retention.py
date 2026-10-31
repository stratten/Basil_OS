"""Retention and empty-file behavior of the desktop debug-log folder."""

import logging
import os
import time
from pathlib import Path

from api.core.logging.api_logger import DESKTOP_DEBUG_LOG_RETENTION_DAYS, prune_old_desktop_debug_logs

DAY = 86400.0


def make_file(directory: Path, name: str, age_days: float, now: float) -> Path:
    path = directory / name
    path.write_text("x", encoding="utf-8")
    stamp = now - age_days * DAY
    os.utime(path, (stamp, stamp))
    return path


def test_retention_is_two_weeks():
    assert DESKTOP_DEBUG_LOG_RETENTION_DAYS == 14


def test_prune_removes_only_old_basil_logs_and_samples(tmp_path):
    now = time.time()
    old_client = make_file(tmp_path, "Basil_20260409_101010_AAAAAAAA.log", 200, now)
    old_backend = make_file(tmp_path, "Basil_Backend_20260409_101010_BBBBBBBB.log", 15, now)
    old_sample = make_file(tmp_path, "Basil_MainStall_20260409_101010.sample.txt", 30, now)
    recent = make_file(tmp_path, "Basil_20261029_101010_CCCCCCCC.log", 13, now)
    today = make_file(tmp_path, "Basil_Backend_20261030_101010_DDDDDDDD.log", 0, now)
    unrelated_old = make_file(tmp_path, "notes.txt", 400, now)
    other_extension = make_file(tmp_path, "Basil_export.csv", 400, now)

    removed = prune_old_desktop_debug_logs(tmp_path, now=now)

    assert removed == 3
    assert not old_client.exists() and not old_backend.exists() and not old_sample.exists()
    assert recent.exists() and today.exists() and unrelated_old.exists() and other_extension.exists()


def test_prune_leaves_directories_and_symlinks_alone(tmp_path):
    now = time.time()
    folder = tmp_path / "Basil_old_folder.log"
    folder.mkdir()
    os.utime(folder, (now - 100 * DAY, now - 100 * DAY))
    target = make_file(tmp_path, "target.dat", 100, now)
    link = tmp_path / "Basil_link.log"
    link.symlink_to(target)

    assert prune_old_desktop_debug_logs(tmp_path, now=now) == 0
    assert folder.exists() and link.is_symlink() and target.exists()


def test_prune_with_a_missing_directory_removes_nothing(tmp_path):
    assert prune_old_desktop_debug_logs(tmp_path / "does-not-exist") == 0


def test_delayed_file_handler_creates_no_file_until_a_record_is_written(tmp_path):
    path = tmp_path / "Basil_Backend_test.log"
    handler = logging.FileHandler(str(path), mode="w", delay=True)
    try:
        assert not path.exists()
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)
        handler.emit(record)
        assert path.exists() and "hello" in path.read_text(encoding="utf-8")
    finally:
        handler.close()
