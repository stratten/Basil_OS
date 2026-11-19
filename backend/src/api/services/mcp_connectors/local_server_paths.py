"""Where one local server keeps the files Basil prepares for it and the files its program writes.

Each connection gets two folders under the supervisor's state folder: ``install`` for downloaded and built files, and ``data`` for the program's own sessions and databases. Both are private to the person, and both are deleted with the connection.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


@dataclass(frozen=True)
class ConnectionFolders:
    install: Path
    data: Path


def is_safe_connection_id(connection_id: str) -> bool:
    return bool(_SAFE_ID.fullmatch(connection_id))


def connection_folders(state_dir: Path, connection_id: str) -> ConnectionFolders:
    """The folders for a connection. Nothing is created. Raises ValueError for an id that could point outside the state folder."""
    if not is_safe_connection_id(connection_id):
        raise ValueError("That is not a valid local server id.")
    root = Path(state_dir) / "connections" / connection_id
    return ConnectionFolders(install=root / "install", data=root / "data")


def ensure_connection_folders(state_dir: Path, connection_id: str) -> ConnectionFolders:
    """The folders for a connection, created with owner-only permissions when missing."""
    folders = connection_folders(state_dir, connection_id)
    for folder in (folders.install.parent, folders.install, folders.data):
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o700)
    return folders


def remove_connection_folders(state_dir: Path, connection_id: str) -> None:
    """Delete everything kept for a connection. Does nothing for an invalid id or a connection with no folders."""
    if not is_safe_connection_id(connection_id):
        return
    shutil.rmtree(Path(state_dir) / "connections" / connection_id, ignore_errors=True)
