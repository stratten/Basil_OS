"""Pure helpers for formatting and measuring a loaded meeting transcript.

Extracted from MeetingAnalyzer so the analyzer stays focused on orchestration
and within the project file-size limit. All functions operate on a transcript
dict of the shape ``{"segments": [{"start", "end", "text", "speaker"}, ...]}``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional


def parse_iso_to_epoch(value: Optional[str]) -> Optional[float]:
    """Parse an ISO-8601 timestamp (optionally Z-suffixed) to epoch seconds.

    Returns ``None`` for missing/unparseable values so callers can fall back to
    a zero offset. Used to align multi-track recordings onto a shared origin.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # datetime.fromisoformat accepts "+00:00" but not a trailing "Z" before
    # Python 3.11; normalize it for broad compatibility.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def format_timestamp(seconds: float) -> str:
    """Format seconds as MM:SS."""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins:02d}:{secs:02d}"


def format_transcript_for_prompt(transcript: Optional[Dict[str, Any]]) -> str:
    """Format transcript segments into readable, speaker-labeled lines."""
    if not transcript or "segments" not in transcript:
        return ""

    lines = []
    for segment in transcript["segments"]:
        start = segment.get("start", 0.0)
        speaker = segment.get("speaker", "Unknown")
        text = segment.get("text", "").strip()

        # Format: [00:12] Speaker 1: Text content
        timestamp_str = format_timestamp(start)
        lines.append(f"[{timestamp_str}] {speaker}: {text}")

    return "\n".join(lines)


def get_transcript_duration(transcript: Optional[Dict[str, Any]]) -> float:
    """Return the end time of the last segment (total duration in seconds)."""
    if not transcript or "segments" not in transcript:
        return 0.0

    segments = transcript["segments"]
    if not segments:
        return 0.0

    return segments[-1].get("end", 0.0)


def count_unique_speakers(transcript: Optional[Dict[str, Any]]) -> int:
    """Count the number of unique, non-empty speaker labels in the transcript."""
    if not transcript or "segments" not in transcript:
        return 0

    speakers = set()
    for segment in transcript["segments"]:
        speaker = segment.get("speaker")
        if speaker:
            speakers.add(speaker)

    return len(speakers)
