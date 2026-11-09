"""Writing a reviewed profile into essentials.md and user.md, with a backup so the person can undo it."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

PROFILE_FILES = ("essentials.md", "user.md")
_BACKUP_ID = re.compile(r"^profile-[0-9a-f]{12}$")


class ProfileTooLargeError(ValueError):
    """An edited file is over its size limit."""


class UnknownProfileBackupError(LookupError):
    """No profile backup has that id."""


def _byte_length(value: str) -> int:
    return len(value.encode("utf-8"))


def write_profile(
    memory_service: Any,
    backup_dir: Path,
    *,
    label: str,
    new_contents: Dict[str, str],
    caps: Dict[str, int],
) -> Dict[str, Any]:
    """Write every non-blank entry of ``new_contents`` that differs from the current file. Blank means leave that file alone."""
    changes: Dict[str, str] = {}
    for name in PROFILE_FILES:
        proposed = (new_contents.get(name) or "").strip()
        if not proposed:
            continue
        if _byte_length(proposed) > caps[name]:
            raise ProfileTooLargeError(f"{name} is {_byte_length(proposed)} bytes, and its limit is {caps[name]}. Shorten it and save again.")
        if proposed != memory_service.read_memory_file(name).content.strip():
            changes[name] = proposed
    if not changes:
        return {"backup_id": None, "files_updated": [], "label": label}

    previous = {name: memory_service.read_memory_file(name).content for name in changes}
    backup_id = f"profile-{uuid.uuid4().hex[:12]}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{backup_id}.json"
    temp_path = backup_dir / f"{backup_id}.json.tmp"
    temp_path.write_text(
        json.dumps({"created_at": datetime.now(timezone.utc).isoformat(), "label": label, "files": previous}, ensure_ascii=False),
        encoding="utf-8",
    )
    temp_path.replace(backup_path)

    written: List[str] = []
    try:
        for name, content in changes.items():
            memory_service.replace_memory_file(name, content)
            written.append(name)
    except Exception:
        for name in written:
            memory_service.replace_memory_file(name, previous[name])
        raise
    return {"backup_id": backup_id, "files_updated": written, "label": label}


def restore_profile(memory_service: Any, backup_dir: Path, backup_id: str) -> Dict[str, Any]:
    """Put the files an earlier profile import replaced back the way they were."""
    if not _BACKUP_ID.match(backup_id):
        raise UnknownProfileBackupError("That profile backup was not found.")
    path = backup_dir / f"{backup_id}.json"
    if not path.is_file():
        raise UnknownProfileBackupError("That profile backup was not found. It may already have been restored.")
    files = json.loads(path.read_text(encoding="utf-8")).get("files", {})
    restored: List[str] = []
    for name in PROFILE_FILES:
        if name in files:
            memory_service.replace_memory_file(name, files[name])
            restored.append(name)
    path.unlink()
    return {"backup_id": backup_id, "files_restored": restored}
