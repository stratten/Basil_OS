"""Crash-safe text file replacement shared by the memory and skill stores."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, content: str) -> None:
    """Replace ``path`` with ``content`` so a reader sees the old or new file, never a partial one.

    The content is written to a temporary file in the same directory, flushed and fsynced, then moved into place with ``os.replace``. The temporary file is removed if anything fails before the replace.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary = Path(temporary_path)
        if temporary.exists():
            temporary.unlink()
