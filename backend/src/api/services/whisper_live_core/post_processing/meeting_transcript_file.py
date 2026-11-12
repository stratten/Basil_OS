"""Keeps a readable interleaved-transcript file next to each meeting's analyses.

A call is stored as one folder per recording track (microphone, system audio, and one more pair per resumed part), so reading it means finding the siblings, placing every line on one timeline, and grouping lines into turns. ``ensure_meeting_transcript_markdown`` does that and writes ``transcript_interleaved.md`` into the call's representative folder, formatted exactly like the analysis window's Export (see ``meeting_transcript_markdown``).

The timeline rule is the one the analysis window uses: each recording's own segment times, shifted only by how much later it started than the earliest recording of the same part. A resumed part's segment times already carry its resume offset, so no offset is added on top.

Every function here is best-effort for its callers: a failure to write the file is logged by the callers and never fails an analysis, a recording, or post-processing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .meeting_transcript_markdown import (
    TRANSCRIPT_MARKDOWN_FILENAME,
    build_transcript_markdown,
    write_transcript_markdown,
)
from .meeting_transcript_utils import parse_iso_to_epoch
from .transcript_merger import merge_session_transcripts

logger = logging.getLogger(__name__)

MemberEntry = Tuple[Path, Dict[str, Any]]


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _is_microphone(metadata: Dict[str, Any]) -> bool:
    return str(metadata.get("audio_source") or "").strip().lower() == "microphone"


def _part_index(metadata: Dict[str, Any]) -> int:
    try:
        return int(metadata.get("recording_part_index") or 0)
    except (TypeError, ValueError):
        return 0


def _clean_name(metadata: Dict[str, Any]) -> str:
    """Drop the trailing " - <audio source>" the client appends per recording, like the meeting list does."""
    name = str(metadata.get("name") or "")
    audio_source = metadata.get("audio_source")
    if audio_source and name.endswith(f" - {audio_source}"):
        return name[: -len(f" - {audio_source}")]
    return name


def _session_members(meeting_dir: Path) -> List[MemberEntry]:
    """Every recording of the call that ``meeting_dir`` belongs to, ordered by part then start time."""
    metadata = _read_json(meeting_dir / "metadata.json")
    if metadata is None:
        return []
    session_id = metadata.get("session_id")
    if not session_id:
        return [(meeting_dir, metadata)]
    members: List[MemberEntry] = []
    try:
        siblings = list(meeting_dir.parent.iterdir())
    except OSError:
        return [(meeting_dir, metadata)]
    for directory in siblings:
        if not directory.is_dir():
            continue
        candidate = metadata if directory == meeting_dir else _read_json(directory / "metadata.json")
        if candidate is not None and candidate.get("session_id") == session_id:
            members.append((directory, candidate))
    if not any(directory == meeting_dir for directory, _ in members):
        members.append((meeting_dir, metadata))
    members.sort(key=lambda entry: (_part_index(entry[1]), str(entry[1].get("start_time") or "")))
    return members


def _representative(members: List[MemberEntry]) -> MemberEntry:
    """The microphone recording when there is one, else the earliest: the folder the meeting list also shows."""
    return next((entry for entry in members if _is_microphone(entry[1])), members[0])


def _merge_inputs(members: List[MemberEntry]) -> List[Dict[str, Any]]:
    """Members shaped for ``merge_session_transcripts``, microphone recordings first so a tie keeps the microphone line first."""
    single = len(members) == 1
    part_origin: Dict[int, float] = {}
    for _, metadata in members:
        started = parse_iso_to_epoch(metadata.get("start_time"))
        if started is None:
            continue
        part = _part_index(metadata)
        if part not in part_origin or started < part_origin[part]:
            part_origin[part] = started

    inputs: List[Dict[str, Any]] = []
    for directory, metadata in sorted(members, key=lambda entry: 0 if _is_microphone(entry[1]) else 1):
        transcript = _read_json(directory / "transcript.json")
        segments = (transcript or {}).get("segments")
        if not isinstance(segments, list) or not segments:
            continue
        started = parse_iso_to_epoch(metadata.get("start_time"))
        origin = part_origin.get(_part_index(metadata))
        skew = max(0.0, started - origin) if started is not None and origin is not None else 0.0
        source = metadata.get("audio_source") or ("Microphone" if single else "System Audio")
        inputs.append({"source": source, "segments": segments, "start_offset_seconds": skew})
    return inputs


def ensure_meeting_transcript_markdown(meeting_dir: Path) -> Optional[Path]:
    """Render the call's full interleaved transcript and make sure its file is current.

    Returns the file's path, or None when the folder has no readable metadata or the call has no transcribed speech. The file is rewritten only when its content changed, so calling this often is cheap and safe, and it always reflects the transcripts on disk now rather than when an analysis last ran.
    """
    meeting_dir = Path(meeting_dir)
    members = _session_members(meeting_dir)
    if not members:
        return None
    representative_dir, representative_metadata = _representative(members)
    merged = merge_session_transcripts(_merge_inputs(members))
    markdown = build_transcript_markdown(
        merged.get("segments", []),
        meeting_name=_clean_name(representative_metadata),
        started_at=representative_metadata.get("start_time"),
    )
    write_transcript_markdown(representative_dir, markdown)
    path = representative_dir / TRANSCRIPT_MARKDOWN_FILENAME
    return path if path.exists() else None


async def ensure_meeting_transcript_markdown_async(meeting_dir: Path) -> Optional[Path]:
    """The same, off the event loop: it reads several JSON files and scans the meetings folder."""
    return await asyncio.to_thread(ensure_meeting_transcript_markdown, Path(meeting_dir))


def meeting_transcript_markdown_path(meeting_id: str) -> Optional[str]:
    """Path of the call's transcript file, created or refreshed now; None when it cannot be produced."""
    try:
        from api.services.meetings.meeting_recorder import MeetingRecorder

        path = ensure_meeting_transcript_markdown(MeetingRecorder.get_meeting_directory(meeting_id))
    except Exception as exc:
        logger.warning("Could not prepare the transcript file for meeting %s: %s", meeting_id, exc)
        return None
    return str(path) if path else None


async def refresh_after_recording_stopped(meeting_id: str) -> None:
    """Write the transcript file for a recording that just stopped, then ask the memory scheduler to collect the meeting now.

    Both steps are independent and best-effort. The scheduler normally picks a finished meeting up on a timer that can be a quarter of an hour away; the kick makes it searchable within seconds. A call with two recordings stops twice, and the second stop is the one that closes the meeting, so each stop kicks.
    """
    try:
        from api.services.meetings.meeting_recorder import MeetingRecorder

        await ensure_meeting_transcript_markdown_async(MeetingRecorder.get_meeting_directory(meeting_id))
    except Exception as exc:
        logger.warning("Could not write the transcript file for meeting %s: %s", meeting_id, exc)
    try:
        from api.services.zettel.scheduler import get_zettel_scheduler

        get_zettel_scheduler().kick()
    except Exception as exc:
        logger.warning("Could not ask the memory scheduler to collect meeting %s: %s", meeting_id, exc)
