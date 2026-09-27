"""Response parsing helpers for OpenAI transcription responses."""

from __future__ import annotations

from typing import Any, Dict, List


def extract_timestamped_segments(response: Any) -> List[Dict[str, Any]]:
    """Normalize OpenAI verbose transcription responses into transcript segments."""
    raw_segments = None
    if isinstance(response, dict):
        raw_segments = response.get("segments")
    else:
        raw_segments = getattr(response, "segments", None)

    if not raw_segments:
        return []

    segments: List[Dict[str, Any]] = []
    for segment in raw_segments:
        if isinstance(segment, dict):
            start = segment.get("start")
            end = segment.get("end")
            text = segment.get("text")
        else:
            start = getattr(segment, "start", None)
            end = getattr(segment, "end", None)
            text = getattr(segment, "text", None)

        if start is None or end is None or not text:
            continue

        segments.append({
            "start": float(start),
            "end": float(end),
            "text": str(text).strip(),
        })

    return segments
