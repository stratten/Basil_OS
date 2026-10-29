"""Tests for the pure artifact-revision capture policy."""

import hashlib
import os

from api.services.agent_processing.lifecycle.runtime.artifact_revision_capture import (
    MAX_SNAPSHOT_BYTES,
    MAX_TASK_SNAPSHOT_BYTES,
    capture_artifact_revision,
    content_kind_for_path,
)


def _write(path, content: str) -> str:
    data = content.encode("utf-8")
    with open(path, "wb") as destination:
        destination.write(data)
    return hashlib.sha256(data).hexdigest()


def test_content_kind_for_path_recognizes_supported_extensions():
    assert content_kind_for_path("/tmp/report.md") == "markdown"
    assert content_kind_for_path("/tmp/page.html") == "html"
    assert content_kind_for_path("/tmp/notes.txt") == "text"
    assert content_kind_for_path("/tmp/script.py") == "code"
    assert content_kind_for_path("/tmp/image.png") is None


def test_captures_a_verified_markdown_file(tmp_path):
    target = tmp_path / "report.md"
    digest = _write(target, "# Report\n")

    result = capture_artifact_revision(
        local_path=str(target),
        expected_sha256=digest,
        latest_known_sha256=None,
        task_snapshot_bytes_used=0,
    )

    assert result.status == "captured"
    assert result.content_kind == "markdown"
    assert result.content == "# Report\n"
    assert result.content_sha256 == digest
    assert result.byte_count == len("# Report\n".encode("utf-8"))


def test_unchanged_short_circuits_without_reading_the_file(tmp_path):
    target = tmp_path / "missing-after-check.md"
    digest = "0" * 64

    result = capture_artifact_revision(
        local_path=str(target),
        expected_sha256=digest,
        latest_known_sha256=digest,
        task_snapshot_bytes_used=0,
    )

    assert result.status == "unchanged"


def test_unsupported_extension_is_unavailable(tmp_path):
    target = tmp_path / "image.png"
    digest = _write(target, "not really an image")

    result = capture_artifact_revision(
        local_path=str(target),
        expected_sha256=digest,
        latest_known_sha256=None,
        task_snapshot_bytes_used=0,
    )

    assert result.status == "unavailable"
    assert result.unavailable_reason == "Snapshot unavailable: unsupported file type."


def test_missing_file_is_unavailable(tmp_path):
    target = tmp_path / "gone.md"

    result = capture_artifact_revision(
        local_path=str(target),
        expected_sha256="a" * 64,
        latest_known_sha256=None,
        task_snapshot_bytes_used=0,
    )

    assert result.status == "unavailable"
    assert result.unavailable_reason == "Snapshot unavailable: file could not be read."


def test_directory_path_is_unavailable(tmp_path):
    target = tmp_path / "adir.md"
    target.mkdir()

    result = capture_artifact_revision(
        local_path=str(target),
        expected_sha256="a" * 64,
        latest_known_sha256=None,
        task_snapshot_bytes_used=0,
    )

    assert result.status == "unavailable"
    assert result.unavailable_reason == "Snapshot unavailable: not a regular file."


def test_symlink_is_unavailable(tmp_path):
    real_target = tmp_path / "real.md"
    digest = _write(real_target, "# Real\n")
    link = tmp_path / "link.md"
    os.symlink(real_target, link)

    result = capture_artifact_revision(
        local_path=str(link),
        expected_sha256=digest,
        latest_known_sha256=None,
        task_snapshot_bytes_used=0,
    )

    assert result.status == "unavailable"
    assert result.unavailable_reason == "Snapshot unavailable: not a regular file."


def test_oversized_file_is_unavailable(tmp_path):
    target = tmp_path / "big.md"
    digest = _write(target, "x" * (MAX_SNAPSHOT_BYTES + 1))

    result = capture_artifact_revision(
        local_path=str(target),
        expected_sha256=digest,
        latest_known_sha256=None,
        task_snapshot_bytes_used=0,
    )

    assert result.status == "unavailable"
    assert result.unavailable_reason == "Snapshot unavailable: review size limit."


def test_task_quota_exceeded_is_unavailable(tmp_path):
    target = tmp_path / "small.md"
    digest = _write(target, "# Small\n")

    result = capture_artifact_revision(
        local_path=str(target),
        expected_sha256=digest,
        latest_known_sha256=None,
        task_snapshot_bytes_used=MAX_TASK_SNAPSHOT_BYTES,
    )

    assert result.status == "unavailable"
    assert result.unavailable_reason == "Snapshot unavailable: task review size limit."


def test_stale_sha_mismatch_is_unavailable(tmp_path):
    target = tmp_path / "changed.md"
    _write(target, "# After\n")

    result = capture_artifact_revision(
        local_path=str(target),
        expected_sha256=hashlib.sha256(b"# Before\n").hexdigest(),
        latest_known_sha256=None,
        task_snapshot_bytes_used=0,
    )

    assert result.status == "unavailable"
    assert result.unavailable_reason == "Snapshot unavailable: file changed before capture."


def test_malformed_utf8_is_unavailable(tmp_path):
    target = tmp_path / "binary.md"
    data = b"\xff\xfe\x00\x01"
    with open(target, "wb") as destination:
        destination.write(data)
    digest = hashlib.sha256(data).hexdigest()

    result = capture_artifact_revision(
        local_path=str(target),
        expected_sha256=digest,
        latest_known_sha256=None,
        task_snapshot_bytes_used=0,
    )

    assert result.status == "unavailable"
    assert result.unavailable_reason == "Snapshot unavailable: file is not valid UTF-8."


def test_identical_content_after_read_is_unchanged(tmp_path):
    target = tmp_path / "same.md"
    digest = _write(target, "# Same\n")

    result = capture_artifact_revision(
        local_path=str(target),
        expected_sha256=digest,
        latest_known_sha256=digest,
        task_snapshot_bytes_used=0,
    )

    assert result.status == "unchanged"
