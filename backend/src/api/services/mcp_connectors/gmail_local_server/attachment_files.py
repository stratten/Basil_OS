"""Where and how a downloaded Gmail attachment is saved on the user's computer.

Every function here is about the disk, not Gmail: choosing a safe destination folder, turning an attachment's name into a safe file name, and writing the bytes without ever replacing a file that already exists. The handler in :mod:`handlers_attachments` decides which attachment to fetch.
"""

from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path
from typing import Optional, Tuple

from .gmail_api import ToolArgumentError

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
"""Largest attachment the tool will download. Gmail itself caps messages at about 25 MB; this leaves room for encoding overhead and refuses anything stranger."""

MAX_DRAFT_ATTACHMENT_BYTES = 25 * 1024 * 1024
"""Largest combined size of the files attached to one draft, the limit Gmail applies to a message."""

_MAX_FILE_NAME_LENGTH = 180
_MAX_NAME_COLLISIONS = 1000
_UNSAFE_NAME_CHARACTERS = re.compile(r"[\x00-\x1f\x7f/\\:]")

_PROTECTED_HOME_FOLDERS = (
    ".ssh",
    ".gnupg",
    ".aws",
    ".kube",
    ".basil/secrets",
    "Library/LaunchAgents",
    "Library/LaunchDaemons",
    "Library/Keychains",
)
_PROTECTED_SYSTEM_FOLDERS = (
    "/System",
    "/usr",
    "/bin",
    "/sbin",
    "/etc",
    "/private/etc",
    "/Library/LaunchAgents",
    "/Library/LaunchDaemons",
)


def safe_file_name(name: Optional[str], mime_type: Optional[str] = None) -> str:
    """A plain file name with no folder parts, control characters, or leading dots, never empty and never very long."""
    base = os.path.basename((name or "").replace("\\", "/"))
    cleaned = _UNSAFE_NAME_CHARACTERS.sub("_", base).strip().lstrip(".").strip()
    if not cleaned:
        extension = mimetypes.guess_extension((mime_type or "").split(";")[0].strip()) or ""
        return f"attachment{extension}"
    if len(cleaned) > _MAX_FILE_NAME_LENGTH:
        stem, extension = os.path.splitext(cleaned)
        extension = extension[:20]
        cleaned = stem[: _MAX_FILE_NAME_LENGTH - len(extension)] + extension
    return cleaned


def _is_inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _refuse_protected(folder: Path, action: str = "save downloaded attachments into") -> None:
    home = Path.home().resolve()
    for relative in _PROTECTED_HOME_FOLDERS:
        if _is_inside(folder, home / relative):
            raise ToolArgumentError(f"Basil does not {action} {folder}, because it holds credentials or startup items. Choose another folder.")
    for absolute in _PROTECTED_SYSTEM_FOLDERS:
        if _is_inside(folder, Path(absolute).resolve()):
            raise ToolArgumentError(f"Basil does not {action} {folder}, because it is a system folder. Choose another folder.")


def resolve_destination_folder(requested: Optional[str], default_folder: Path) -> Path:
    """The folder to save into: the default when none was asked for, otherwise the absolute path the user chose, created if needed."""
    if requested is None or not requested.strip():
        folder = default_folder
    else:
        expanded = Path(os.path.expanduser(requested.strip()))
        if not expanded.is_absolute():
            raise ToolArgumentError(
                f"destinationFolder must be an absolute path such as /Users/name/Documents, or one starting with ~/. Got {requested!r}."
            )
        folder = expanded.resolve()
    _refuse_protected(folder.resolve())
    if folder.exists() and not folder.is_dir():
        raise ToolArgumentError(f"{folder} is a file, not a folder.")
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ToolArgumentError(f"Could not create or open the folder {folder}: {exc.strerror or type(exc).__name__}.") from exc
    return folder


def read_attachment_file(requested: str) -> Tuple[bytes, str, str]:
    """Read a file the agent wants to attach to a draft; returns its bytes, a safe file name, and its media type.

    The path must be absolute or start with ``~/``. Files inside credential or system folders are refused, so an attachment path cannot be used to read secrets, and a file over the draft size limit is refused before it is read in full.
    """
    text = (requested or "").strip()
    if not text:
        raise ToolArgumentError("An attachment needs either content or a path, and this path is empty.")
    expanded = Path(os.path.expanduser(text))
    if not expanded.is_absolute():
        raise ToolArgumentError(f"An attachment path must be absolute, such as /Users/name/Documents/report.pdf, or start with ~/. Got {requested!r}.")
    path = expanded.resolve()
    _refuse_protected(path, "attach files from")
    if not path.exists():
        raise ToolArgumentError(f"There is no file at {path}. Check the path, or save the file first and use its saved location.")
    if not path.is_file():
        raise ToolArgumentError(f"{path} is a folder, not a file. Attach one file per attachment.")
    try:
        size = path.stat().st_size
        if size > MAX_DRAFT_ATTACHMENT_BYTES:
            raise ToolArgumentError(f"{path.name} is {size // (1024 * 1024)} MB, which is over the 25 MB limit for the files attached to one email.")
        data = path.read_bytes()
    except OSError as exc:
        raise ToolArgumentError(f"Could not read {path}: {exc.strerror or type(exc).__name__}.") from exc
    name = safe_file_name(path.name)
    mime_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return data, name, mime_type


def write_without_overwriting(folder: Path, file_name: str, data: bytes) -> Path:
    """Save ``data`` as ``file_name`` in ``folder``, adding " (1)", " (2)" and so on when the name is taken. An existing file is never replaced."""
    stem, extension = os.path.splitext(file_name)
    for attempt in range(_MAX_NAME_COLLISIONS):
        candidate = folder / (file_name if attempt == 0 else f"{stem} ({attempt}){extension}")
        created = False
        try:
            with open(candidate, "xb") as handle:
                created = True
                handle.write(data)
            return candidate
        except FileExistsError:
            continue
        except OSError as exc:
            if created:
                # Only a file this call created is removed, so a half-written attachment is never left behind and nothing else is touched.
                try:
                    candidate.unlink()
                except OSError:
                    pass
            raise ToolArgumentError(f"Could not save the attachment to {candidate}: {exc.strerror or type(exc).__name__}.") from exc
    raise ToolArgumentError(f"{folder} already holds {_MAX_NAME_COLLISIONS} files named like {file_name!r}. Choose another folder or file name.")
