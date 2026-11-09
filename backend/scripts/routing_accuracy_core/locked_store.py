"""Write a result file once, make it read-only, and record a SHA-256 beside it, so a later step can prove the file is the one that was captured.

Cleanup of a run's database rows refuses to start unless the results and the evidence snapshot both verify here.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


class LockedStoreError(RuntimeError):
    """A locked file is missing, writable, altered, or has no matching digest."""


def digest_path(path: Path) -> Path:
    return path.with_name(path.name + ".sha256")


def write_locked(path: Path, document: dict[str, Any]) -> str:
    """Create ``path`` from ``document`` and lock it. An existing file is never overwritten. Returns the SHA-256 of the bytes written."""
    if path.exists() or digest_path(path).exists():
        raise FileExistsError(f"{path} already exists; locked results are never overwritten, so choose a new name")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o444)
    os.replace(temporary, path)
    sidecar = digest_path(path)
    sidecar.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    os.chmod(sidecar, 0o444)
    return digest


def lock_existing(path: Path) -> str:
    """Lock a file that was written before locking existed: record its digest and make it read-only. A file that already has a digest is left alone."""
    if not path.is_file():
        raise LockedStoreError(f"{path} does not exist")
    sidecar = digest_path(path)
    if sidecar.exists():
        raise LockedStoreError(f"{path} already has a digest")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    os.chmod(path, 0o444)
    sidecar.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    os.chmod(sidecar, 0o444)
    return digest


def verify_locked(path: Path) -> dict[str, Any]:
    """Return the document in ``path`` after checking it is read-only and its bytes still match the recorded digest."""
    if not path.is_file():
        raise LockedStoreError(f"{path} does not exist")
    sidecar = digest_path(path)
    if not sidecar.is_file():
        raise LockedStoreError(f"{sidecar} does not exist")
    if path.stat().st_mode & _WRITE_BITS:
        raise LockedStoreError(f"{path} is writable, so it is not locked")
    payload = path.read_bytes()
    recorded = sidecar.read_text(encoding="utf-8").split()[0]
    if hashlib.sha256(payload).hexdigest() != recorded:
        raise LockedStoreError(f"{path} no longer matches its recorded SHA-256")
    return json.loads(payload.decode("utf-8"))
