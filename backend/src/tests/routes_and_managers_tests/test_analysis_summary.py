"""Tests for per-meeting analysis summary used by meeting list responses."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from api.routes.meetings import analysis_summary
from api.routes.meetings.analysis_summary import build_analysis_summary
from api.services.meetings.meeting_recorder import MeetingRecorder

VALID_FILENAME = "analysis_20240101_000000.json"


def _write_analysis_file(
    directory: Path,
    filename: str = VALID_FILENAME,
    suggested_actions=None,
) -> None:
    payload = {"suggested_actions": suggested_actions if suggested_actions is not None else []}
    with open(directory / filename, "w") as f:
        json.dump(payload, f)


@pytest.fixture
def meeting_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(
        MeetingRecorder,
        "get_meeting_directory",
        staticmethod(lambda meeting_id: tmp_path),
    )
    return tmp_path


def test_no_analyses_returns_none_without_disk_read(monkeypatch):
    def _fail_if_called(_meeting_id):
        raise AssertionError("get_meeting_directory must not be called")

    monkeypatch.setattr(
        MeetingRecorder,
        "get_meeting_directory",
        staticmethod(_fail_if_called),
    )

    assert build_analysis_summary("m1", {}) is None
    assert build_analysis_summary("m1", {"analyses": []}) is None


def test_pending_count_excludes_handled_statuses(meeting_dir):
    _write_analysis_file(
        meeting_dir,
        suggested_actions=[
            {"execution_status": "proposed"},
            {"execution_status": "submitting"},
            {"execution_status": "submitted"},
            {"execution_status": "completed"},
            {"execution_status": "dismissed"},
            {"execution_status": "failed"},
            {},  # omitted key -> defaults to proposed
        ],
    )
    metadata = {
        "analyses": [
            {
                "timestamp": "2026-01-01T10:00:00Z",
                "filename": VALID_FILENAME,
            }
        ]
    }

    summary = build_analysis_summary("m1", metadata)

    assert summary is not None
    assert summary.pending_action_count == 4


def test_latest_entry_picked_by_timestamp_not_list_order(meeting_dir):
    older = "analysis_20240101_000000.json"
    newer = "analysis_20240102_000000.json"
    _write_analysis_file(meeting_dir, filename=older, suggested_actions=[])
    _write_analysis_file(meeting_dir, filename=newer, suggested_actions=[])

    metadata = {
        "analyses": [
            {
                "timestamp": "2026-01-02T10:00:00Z",
                "filename": newer,
            },
            {
                "timestamp": "2026-01-01T10:00:00Z",
                "filename": older,
            },
        ]
    }

    summary = build_analysis_summary("m1", metadata)

    assert summary is not None
    assert summary.latest_filename == newer
    assert summary.count == 2


def test_missing_analysis_file_returns_none_pending_but_keeps_count(meeting_dir):
    metadata = {
        "analyses": [
            {
                "timestamp": "2026-01-01T10:00:00Z",
                "filename": VALID_FILENAME,
            }
        ]
    }

    summary = build_analysis_summary("m1", metadata)

    assert summary is not None
    assert summary.count == 1
    assert summary.latest_filename == VALID_FILENAME
    assert summary.latest_timestamp == "2026-01-01T10:00:00Z"
    assert summary.pending_action_count is None


def test_malformed_filename_rejected(meeting_dir, monkeypatch):
    opened_paths = []

    original_open = open

    def _tracking_open(path, *args, **kwargs):
        opened_paths.append(str(path))
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _tracking_open)

    metadata = {
        "analyses": [
            {
                "timestamp": "2026-01-01T10:00:00Z",
                "filename": "../../etc/passwd",
            }
        ]
    }

    summary = build_analysis_summary("m1", metadata)

    assert summary is not None
    assert summary.pending_action_count is None
    assert not any("/etc/passwd" in p for p in opened_paths)


def test_suggested_actions_absent_treated_as_zero_not_none(meeting_dir):
    _write_analysis_file(meeting_dir, suggested_actions=None)
    with open(meeting_dir / VALID_FILENAME, "w") as f:
        json.dump({}, f)

    metadata = {
        "analyses": [
            {
                "timestamp": "2026-01-01T10:00:00Z",
                "filename": VALID_FILENAME,
            }
        ]
    }

    summary = build_analysis_summary("m1", metadata)

    assert summary is not None
    assert summary.pending_action_count == 0


def test_analysis_filename_re_exported_for_proposal_store():
    assert analysis_summary.ANALYSIS_FILENAME_RE.match(VALID_FILENAME)
    assert not analysis_summary.ANALYSIS_FILENAME_RE.match("../evil.json")
