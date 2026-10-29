"""Shared, crash-safe transcript persistence helpers.

Every writer of a meeting's ``transcript.json`` (the live recorder's raw save,
the full post-processing pipeline, and the windowed-retranscription ledger
replay) should go through :func:`write_transcript_atomically` so a killed
process or a concurrent read can never observe a torn/partial file, and so a
never-intended segment shape (an interim line, a segment past the real audio
duration, or an exact-duplicate trailing run) can never reach disk regardless
of which upstream code produced it.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import tempfile
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def atomic_write_json(path: Path, value: Dict[str, Any]) -> None:
    """Atomically write JSON within the target directory.

    Writes to a temporary file in the same directory as ``path`` and then
    ``os.replace``s it into place, so a reader always sees either the old
    complete file or the new complete file, never a partial write, and a
    process killed mid-write leaves the previous good file intact.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as temporary_file:
            json.dump(value, temporary_file, indent=2)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    except Exception:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def _audio_duration_seconds(audio_path: Optional[Path]) -> Optional[float]:
    """Return the real duration of a WAV file, or None if it cannot be read."""
    if audio_path is None or not audio_path.exists():
        return None
    try:
        with wave.open(str(audio_path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            if frames <= 0 or rate <= 0:
                return None
            return frames / float(rate)
    except Exception:
        return None


def sanitize_transcript_segments(
    segments: List[Dict[str, Any]],
    audio_path: Optional[Path] = None,
    timeline_offset_seconds: float = 0.0,
    timeline_ranges: Optional[List[Dict[str, float]]] = None,
) -> List[Dict[str, Any]]:
    """Return a defensive, persistence-safe copy of ``segments``.

    Applied immediately before every transcript.json write, independent of
    which upstream mechanism produced the segments, as a backstop against a
    corrupted/duplicated tail ever reaching disk:

    - Drops any segment whose ``is_interim`` key is present and truthy. No
      current writer should ever produce one, but a segment that slips
      through must never be treated as durable, persisted content.
    - Clamps every segment to its captured-audio timeline range. Native live
      streams can reconnect and therefore contain time gaps that are absent
      from the appended WAV; their persisted ranges are authoritative. Legacy
      recordings without ranges retain the duration-based contiguous window.
    - Collapses a run of three or more consecutive segments with identical
      text into just the first occurrence, logging when this happens so a
      real duplication bug stays visible instead of silently disappearing.
    """
    duration = _audio_duration_seconds(audio_path)
    valid_end = None if duration is None else timeline_offset_seconds + duration
    valid_ranges = [
        (float(item["start"]), float(item["end"]))
        for item in (timeline_ranges or [])
        if isinstance(item, dict)
        and isinstance(item.get("start"), (int, float))
        and isinstance(item.get("end"), (int, float))
        and item["end"] > item["start"]
    ]

    cleaned: List[Dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        if segment.get("is_interim"):
            logger.warning(
                "Dropping interim-flagged segment before persistence: %r", segment
            )
            continue
        start = segment.get("start")
        end = segment.get("end")
        if valid_ranges and isinstance(start, (int, float)) and isinstance(end, (int, float)):
            overlaps = [
                (max(start, range_start), min(end, range_end))
                for range_start, range_end in valid_ranges
                if start < range_end and end > range_start
            ]
            if not overlaps:
                logger.warning("Dropping segment outside captured-audio timeline ranges: %r", segment)
                continue
            clipped_start, clipped_end = max(overlaps, key=lambda bounds: bounds[1] - bounds[0])
            if clipped_end <= clipped_start:
                continue
            if clipped_start != start or clipped_end != end:
                segment = dict(segment)
                segment["start"] = clipped_start
                segment["end"] = clipped_end
            cleaned.append(segment)
            continue
        if valid_end is not None and isinstance(start, (int, float)) and start >= valid_end:
            logger.warning(
                "Dropping segment starting at/after real audio duration "
                "(%.2fs >= %.2fs, timeline_offset=%.2fs): %r",
                start, valid_end, timeline_offset_seconds, segment,
            )
            continue
        if valid_end is not None and isinstance(end, (int, float)) and end > valid_end:
            segment = dict(segment)
            segment["end"] = valid_end
        cleaned.append(segment)

    deduplicated: List[Dict[str, Any]] = []
    for _text, group_iter in itertools.groupby(cleaned, key=lambda s: s.get("text")):
        group = list(group_iter)
        if len(group) >= 3:
            logger.warning(
                "Collapsing a run of %d consecutive segments with identical "
                "text down to the first occurrence: %r",
                len(group), group[0],
            )
            deduplicated.append(group[0])
        else:
            deduplicated.extend(group)

    return deduplicated


def write_transcript_atomically(
    transcript: Dict[str, Any],
    transcript_path: Path,
    audio_path: Optional[Path] = None,
    timeline_offset_seconds: float = 0.0,
    timeline_ranges: Optional[List[Dict[str, float]]] = None,
) -> None:
    """Sanitize ``transcript["segments"]`` and write it atomically."""
    segments = transcript.get("segments", [])
    sanitized = dict(transcript)
    sanitized["segments"] = sanitize_transcript_segments(
        segments,
        audio_path=audio_path,
        timeline_offset_seconds=timeline_offset_seconds,
        timeline_ranges=timeline_ranges,
    )
    atomic_write_json(transcript_path, sanitized)
