"""Durable Companion persistence: per-meeting ``companion.json`` and the global settings file."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

from api.core.atomic_text import atomic_write_text

from .models import COMPANION_SCHEMA_VERSION, CompanionGlobalSettings, CompanionSettings, TimelineEvent

logger = logging.getLogger(__name__)

COMPANION_FILE_NAME = "companion.json"
GLOBAL_SETTINGS_FILE_NAME = "meeting_companion_settings.json"


class CompanionDocument(BaseModel):
    """The on-disk shape of ``companion.json``."""

    schema_version: int = COMPANION_SCHEMA_VERSION
    session_key: str
    settings: CompanionSettings = Field(default_factory=CompanionSettings)
    events: List[TimelineEvent] = Field(default_factory=list)
    saved_at: str = ""


def meetings_root() -> Path:
    """The directory the meetings list and recorder already use; kept as a function so tests can redirect it."""
    # Imported on use: the routes package imports this service at load time, so a module-level import would be circular.
    from api.routes.meetings.meeting_grouping import meetings_directory

    return meetings_directory()


def read_json_object(path: Path) -> Optional[Dict[str, Any]]:
    """Read a JSON object from ``path``; ``None`` when absent, unreadable or not an object."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def resolve_anchor_meeting_dir(meeting_id: str, *, root: Optional[Path] = None) -> Path:
    """Directory that owns ``companion.json`` for the session containing ``meeting_id``.

    Standalone recordings own their own directory. For a session, the anchor is the Microphone member when present, otherwise the earliest member by ``(recording_part_index, start_time)``; this is the same representative rule the meetings list uses.
    """
    base = root if root is not None else meetings_root()
    own_dir = base / meeting_id
    own_metadata = read_json_object(own_dir / "metadata.json")
    session_id = own_metadata.get("session_id") if own_metadata else None
    if not own_metadata or not session_id:
        return own_dir
    members: List[Dict[str, Any]] = []
    try:
        children = [child for child in base.iterdir() if child.is_dir()]
    except OSError:
        return own_dir
    for child in children:
        metadata = read_json_object(child / "metadata.json")
        if metadata and metadata.get("session_id") == session_id:
            members.append(metadata)
    if not members:
        return own_dir
    ordered = sorted(
        members,
        key=lambda member: (int(member.get("recording_part_index") or 0), str(member.get("start_time") or "")),
    )
    representative = next(
        (member for member in ordered if str(member.get("audio_source") or "").lower() == "microphone"),
        ordered[0],
    )
    return base / str(representative.get("id") or meeting_id)


def meeting_id_for_session_key(session_key: str, *, root: Optional[Path] = None) -> Optional[str]:
    """The meeting id that the Meetings list uses to open the recording behind a Companion ``session_key``.

    A Companion session key is the recorder's ``session_id`` when the recording has one (microphone and system-audio members share it) and the meeting id otherwise. Returns the representative member's id, or ``None`` when no recording on disk matches.
    """
    if not isinstance(session_key, str) or not session_key.strip() or "/" in session_key or "\\" in session_key or session_key in {".", ".."}:
        return None
    base = root if root is not None else meetings_root()
    if read_json_object(base / session_key / "metadata.json") is not None:
        return resolve_anchor_meeting_dir(session_key, root=base).name
    try:
        children = sorted(child for child in base.iterdir() if child.is_dir())
    except OSError:
        return None
    for child in children:
        metadata = read_json_object(child / "metadata.json")
        if metadata and metadata.get("session_id") == session_key:
            return resolve_anchor_meeting_dir(child.name, root=base).name
    return None


class CompanionStore:
    """Reads and atomically writes one ``companion.json``."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / COMPANION_FILE_NAME

    def load(self) -> Optional[CompanionDocument]:
        """Return the stored document, or ``None`` when absent or corrupt (a corrupt file is renamed aside)."""
        if not self.path.is_file():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return CompanionDocument.model_validate(raw)
        except (OSError, ValueError, ValidationError) as error:
            self._quarantine(error)
            return None

    def save(self, document: CompanionDocument) -> None:
        text = json.dumps(document.model_dump(mode="json"), ensure_ascii=False)
        atomic_write_text(self.path, text)

    def remove(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            return
        except OSError as error:
            logger.warning("Could not remove %s: %s", self.path, error)

    def _quarantine(self, error: Exception) -> None:
        target = self.directory / f"companion.corrupt-{int(time.time())}.json"
        try:
            self.path.replace(target)
        except OSError as rename_error:
            logger.error("Companion file %s is unreadable (%s) and could not be set aside: %s", self.path, error, rename_error)
            return
        logger.error("Companion file %s was unreadable (%s); moved to %s", self.path, error, target)


class CompanionGlobalSettingsStore:
    """App-wide Companion defaults at ``~/.basil/config/meeting_companion_settings.json``."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._explicit_path = path

    @property
    def path(self) -> Path:
        if self._explicit_path is not None:
            return self._explicit_path
        return Path.home() / ".basil" / "config" / GLOBAL_SETTINGS_FILE_NAME

    def load(self) -> CompanionGlobalSettings:
        raw = read_json_object(self.path)
        if raw is None:
            return CompanionGlobalSettings()
        try:
            return CompanionGlobalSettings.model_validate(raw)
        except ValidationError:
            logger.warning("Ignoring invalid Companion global settings at %s", self.path)
            return CompanionGlobalSettings()

    def save(self, settings: CompanionGlobalSettings) -> None:
        atomic_write_text(self.path, json.dumps(settings.model_dump(mode="json"), ensure_ascii=False))
