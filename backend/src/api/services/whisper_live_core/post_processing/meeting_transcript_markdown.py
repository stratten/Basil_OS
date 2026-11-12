"""Readable Markdown rendering of a meeting's full interleaved transcript.

The saved ``transcript.json`` files hold one recording track each, so reading a call means merging the tracks, ordering them on one timeline, and grouping them into turns. The analysis window's Copy All and Export buttons do that in the web bundle (``transcriptFormatting.ts``) with a Swift mirror in ``MeetingAnalysisWebWindowController.swift``. This module is the backend mirror, so a file written next to an analysis reads exactly like an export and neither a person nor the agent has to rebuild the layout.

Input is the merged segment list produced by ``merge_session_transcripts`` (or any list of ``{start, text, source, speaker}`` dicts already on one timeline). Nothing here touches the meeting directory except ``write_transcript_markdown``.
"""

from __future__ import annotations

import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

TRANSCRIPT_MARKDOWN_FILENAME = "transcript_interleaved.md"

LABEL_NOTE = (
    "*Speaker labels name the recording track a line came from, not the person speaking. "
    "Microphone is this Mac's microphone, and System Audio is everything else playing on this Mac, "
    "including every remote participant mixed together. Basil does not identify individual voices.*"
)

_TRAILING_NUMBER = re.compile(r"(\d+)$")


def _is_microphone(source: str) -> bool:
    return source.strip().lower() == "microphone"


def _speaker_number(speaker: Optional[str]) -> Optional[int]:
    """Mirror of the web bundle's parseSpeakerNumber: ``speaker0`` is Speaker 1, a bare positive number is itself."""
    if not speaker:
        return None
    match = _TRAILING_NUMBER.search(speaker)
    if not match:
        return None
    parsed = int(match.group(1))
    if speaker.lower().startswith("speaker"):
        return parsed + 1
    return parsed if parsed > 0 else None


def _label(source: Optional[str], speaker: Optional[str]) -> Optional[str]:
    """A source always wins: Microphone, or System Audio for any other track. Only a line with no source falls back to Speaker N."""
    if source:
        return "Microphone" if _is_microphone(source) else "System Audio"
    number = _speaker_number(speaker)
    return f"Speaker {number}" if number is not None else None


def format_timestamp(start_seconds: Optional[float]) -> str:
    """``[m:ss]`` under an hour and ``[h:mm:ss]`` from the first hour on, rounding half up like the app does."""
    if not isinstance(start_seconds, (int, float)) or isinstance(start_seconds, bool) or math.isnan(start_seconds):
        return "[00:00]"
    total = max(0, int(math.floor(start_seconds + 0.5)))
    hours, minutes, seconds = total // 3600, (total % 3600) // 60, total % 60
    if hours > 0:
        return f"[{hours}:{minutes:02d}:{seconds:02d}]"
    return f"[{minutes}:{seconds:02d}]"


def _start_sort_key(segment: Dict[str, Any]) -> float:
    start = segment.get("start")
    return float(start) if isinstance(start, (int, float)) and not isinstance(start, bool) and not math.isnan(start) else math.inf


def format_transcript_turns(segments: Sequence[Dict[str, Any]]) -> str:
    """One ``[timestamp] Label`` header per turn, its lines indented four spaces, a blank line between turns.

    A turn is a run of consecutive lines with the same source and speaker, so the microphone and the system audio alternate as they did on the call. Lines are ordered by start time with a stable sort, which keeps simultaneous lines in the order given; a line with no start time goes last. Empty lines are dropped.
    """
    ordered = sorted(segments, key=_start_sort_key)
    blocks: List[List[str]] = []
    previous_group: Optional[str] = None
    for segment in ordered:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        source = segment.get("source")
        speaker = segment.get("speaker")
        group = f"{source or ''}|{speaker or ''}"
        if group != previous_group or not blocks:
            timestamp = format_timestamp(segment.get("start"))
            label = _label(source, speaker)
            blocks.append([f"{timestamp} {label}" if label else timestamp])
        blocks[-1].append(f"    {text}")
        previous_group = group
    return "\n\n".join("\n".join(block) for block in blocks)


def build_transcript_markdown(
    segments: Sequence[Dict[str, Any]],
    *,
    meeting_name: Optional[str] = None,
    started_at: Optional[str] = None,
) -> str:
    """The whole file: a title, when it happened, the note about labels, then the turns. Empty when there is nothing to say."""
    body = format_transcript_turns(segments)
    if not body:
        return ""
    title = (meeting_name or "").strip() or "Meeting"
    parts = [f"# {title} - Transcript"]
    if started_at:
        parts.append(f"*Started: {started_at}*")
    parts.append(LABEL_NOTE)
    parts.append(body)
    return "\n\n".join(parts) + "\n"


def write_transcript_markdown(meeting_dir: Path, markdown: str) -> bool:
    """Write the file atomically; return False without touching the disk when the content is already current or empty."""
    if not markdown:
        return False
    path = Path(meeting_dir) / TRANSCRIPT_MARKDOWN_FILENAME
    try:
        if path.exists() and path.read_text(encoding="utf-8") == markdown:
            return False
    except OSError:
        pass
    descriptor, temporary_name = tempfile.mkstemp(dir=str(path.parent), prefix=".transcript_md_", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(markdown)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    return True
