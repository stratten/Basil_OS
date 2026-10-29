"""Rebuilds Companion turns from a finished meeting's saved transcript files."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import store as store_module
from .models import CompanionTurn
from .replay import segments_to_turns
from .store import read_json_object
from .utterances import SessionClock

MAX_STORED_TURNS = 40


def _epoch(start_time: Any) -> Optional[float]:
    text = str(start_time or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.rstrip("Zz")).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _members(base: Path, meeting_id: str) -> List[Tuple[Path, Dict[str, Any]]]:
    """The meeting's own directory, plus every other directory of the same recording session, oldest first."""
    own_dir = base / meeting_id
    own = read_json_object(own_dir / "metadata.json") or {}
    session_id = own.get("session_id")
    found: List[Tuple[Path, Dict[str, Any]]] = []
    if session_id:
        try:
            children = sorted(child for child in base.iterdir() if child.is_dir())
        except OSError:
            children = []
        for child in children:
            metadata = read_json_object(child / "metadata.json")
            if metadata and metadata.get("session_id") == session_id:
                found.append((child, metadata))
    if not found:
        found.append((own_dir, own))
    found.sort(key=lambda pair: str(pair[1].get("start_time") or ""))
    return found


def _usable_segments(document: Optional[Dict[str, Any]], offset: float, source: str) -> List[Dict[str, Any]]:
    segments = (document or {}).get("segments")
    if not isinstance(segments, list):
        return []
    usable: List[Dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        try:
            start, end = float(segment["start"]) + offset, float(segment["end"]) + offset
        except (KeyError, TypeError, ValueError):
            continue
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        usable.append({"start": start, "end": end, "text": text, "speaker": segment.get("speaker") or source})
    return usable


def load_stored_turns(meeting_id: str, *, root: Optional[Path] = None, limit: int = MAX_STORED_TURNS) -> List[CompanionTurn]:
    """The most recent ``limit`` turns of a finished meeting, with every session member on one shared timeline."""
    base = root if root is not None else store_module.meetings_root()
    members = _members(base, meeting_id)
    clock = SessionClock()
    for directory, metadata in members:
        clock.register_member(directory.name, _epoch(metadata.get("start_time")))
    turns: List[CompanionTurn] = []
    for directory, metadata in members:
        source = str(metadata.get("audio_source") or "Speaker")
        segments = _usable_segments(read_json_object(directory / "transcript.json"), clock.offset_for(directory.name), source)
        turns.extend(segments_to_turns(segments, source_meeting_id=directory.name, id_prefix=f"{directory.name[:6]}-"))
    turns.sort(key=lambda turn: (turn.start, turn.id))
    return turns[-limit:]
