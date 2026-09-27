"""Bounded, pure capture policy for durable Agent Task artifact revisions.

Owns the complete decision of whether a verified, direct local text-file
write becomes a durable revision snapshot: allowed extension-to-kind
mapping, UTF-8 decoding, size bounds, and a structured result. It performs
no database I/O and no filesystem write; it only reads the already-written
file at the verified local path and returns a decision for the caller to
persist.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, Optional

CapturedContentKind = Literal["markdown", "html", "text", "code", "json", "yaml", "xml"]

MAX_SNAPSHOT_BYTES = 512 * 1024
MAX_TASK_SNAPSHOT_BYTES = 8 * 1024 * 1024

_EXTENSION_KIND: dict[str, CapturedContentKind] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".html": "html",
    ".htm": "html",
    ".txt": "text",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".xml": "xml",
    ".py": "code",
    ".js": "code",
    ".jsx": "code",
    ".ts": "code",
    ".tsx": "code",
    ".css": "code",
    ".sh": "code",
    ".sql": "code",
    ".swift": "code",
    ".go": "code",
    ".rs": "code",
    ".java": "code",
    ".c": "code",
    ".cpp": "code",
    ".h": "code",
    ".rb": "code",
    ".toml": "code",
    ".ini": "code",
    ".csv": "code",
}


@dataclass(frozen=True)
class ArtifactRevisionCaptureResult:
    """Structured outcome of one capture attempt for one verified artifact."""

    status: Literal["captured", "unchanged", "unavailable"]
    content_kind: Optional[CapturedContentKind] = None
    content: Optional[str] = None
    content_sha256: Optional[str] = None
    byte_count: Optional[int] = None
    unavailable_reason: Optional[str] = None


def content_kind_for_path(local_path: str) -> Optional[CapturedContentKind]:
    """Return the capture-eligible content kind for a local path, if any."""
    _, extension = os.path.splitext(local_path)
    return _EXTENSION_KIND.get(extension.lower())


def capture_artifact_revision(
    *,
    local_path: str,
    expected_sha256: str,
    latest_known_sha256: Optional[str],
    task_snapshot_bytes_used: int,
) -> ArtifactRevisionCaptureResult:
    """Decide whether to capture a durable revision snapshot for one artifact.

    ``expected_sha256`` is the receipt-verified digest for the file as it was
    written; the file is re-read and re-hashed so a capture can never persist
    content that does not match the verified receipt. ``latest_known_sha256``
    is the most recently captured revision's digest for this artifact, if
    any; a matching digest short-circuits to ``unchanged`` without a
    filesystem read. ``task_snapshot_bytes_used`` is the caller-computed sum
    of already-persisted snapshot bytes for the owning task, read inside the
    same transaction that will perform the insert.
    """
    if latest_known_sha256 is not None and latest_known_sha256 == expected_sha256:
        return ArtifactRevisionCaptureResult(status="unchanged")

    content_kind = content_kind_for_path(local_path)
    if content_kind is None:
        return ArtifactRevisionCaptureResult(
            status="unavailable",
            unavailable_reason="Snapshot unavailable: unsupported file type.",
        )

    try:
        file_stat = os.stat(local_path, follow_symlinks=False)
    except OSError:
        return ArtifactRevisionCaptureResult(
            status="unavailable",
            unavailable_reason="Snapshot unavailable: file could not be read.",
        )
    if not os.path.isfile(local_path) or os.path.islink(local_path):
        return ArtifactRevisionCaptureResult(
            status="unavailable",
            unavailable_reason="Snapshot unavailable: not a regular file.",
        )
    if file_stat.st_size > MAX_SNAPSHOT_BYTES:
        return ArtifactRevisionCaptureResult(
            status="unavailable",
            unavailable_reason="Snapshot unavailable: review size limit.",
        )
    if task_snapshot_bytes_used + file_stat.st_size > MAX_TASK_SNAPSHOT_BYTES:
        return ArtifactRevisionCaptureResult(
            status="unavailable",
            unavailable_reason="Snapshot unavailable: task review size limit.",
        )

    try:
        with open(local_path, "rb") as source:
            raw_bytes = source.read(MAX_SNAPSHOT_BYTES + 1)
    except OSError:
        return ArtifactRevisionCaptureResult(
            status="unavailable",
            unavailable_reason="Snapshot unavailable: file could not be read.",
        )
    if len(raw_bytes) > MAX_SNAPSHOT_BYTES:
        return ArtifactRevisionCaptureResult(
            status="unavailable",
            unavailable_reason="Snapshot unavailable: review size limit.",
        )

    import hashlib

    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if actual_sha256 != expected_sha256:
        return ArtifactRevisionCaptureResult(
            status="unavailable",
            unavailable_reason="Snapshot unavailable: file changed before capture.",
        )

    try:
        text_content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return ArtifactRevisionCaptureResult(
            status="unavailable",
            unavailable_reason="Snapshot unavailable: file is not valid UTF-8.",
        )

    if actual_sha256 == latest_known_sha256:
        return ArtifactRevisionCaptureResult(status="unchanged")

    return ArtifactRevisionCaptureResult(
        status="captured",
        content_kind=content_kind,
        content=text_content,
        content_sha256=actual_sha256,
        byte_count=len(raw_bytes),
    )
