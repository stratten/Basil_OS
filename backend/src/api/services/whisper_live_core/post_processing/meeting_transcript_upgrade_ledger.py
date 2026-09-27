"""Durable range upgrades produced by windowed meeting re-transcription.

Live re-transcription improves the client view before the recorder has stopped.
The recorder subsequently writes its in-memory, streaming transcript, so the
improved ranges must be retained separately until they can be replayed over that
raw transcript. This module owns that local, per-meeting sidecar ledger.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from .windowed_retranscription import splice_segments

LEDGER_FILENAME = "windowed_retranscription_upgrades.json"
_LEDGER_VERSION = 1


def get_upgrade_ledger_path(meeting_dir: Path) -> Path:
    """Return the local sidecar path for a meeting's window upgrades."""
    return meeting_dir / LEDGER_FILENAME


def record_window_upgrade(
    meeting_dir: Path,
    start_seconds: float,
    end_seconds: float,
    segments: List[Dict[str, Any]],
) -> None:
    """Append one successful closed-range replacement to the meeting ledger."""
    if end_seconds <= start_seconds:
        raise ValueError("Window upgrade end_seconds must be greater than start_seconds")

    ledger = _load_ledger(get_upgrade_ledger_path(meeting_dir))
    ledger["upgrades"].append(
        {
            "start_seconds": float(start_seconds),
            "end_seconds": float(end_seconds),
            "segments": [_normalize_segment(segment) for segment in segments],
        }
    )
    _atomic_write_json(get_upgrade_ledger_path(meeting_dir), ledger)


def apply_recorded_window_upgrades(
    meeting_dir: Path,
    transcript: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a transcript with all recorded window upgrades replayed in order."""
    ledger = _load_ledger(get_upgrade_ledger_path(meeting_dir))
    upgraded = dict(transcript)
    segments = list(transcript.get("segments", []))
    for upgrade in ledger["upgrades"]:
        segments = splice_segments(
            segments,
            upgrade["segments"],
            upgrade["start_seconds"],
            upgrade["end_seconds"],
        )
    upgraded["segments"] = segments
    return upgraded


def finalize_recorded_window_upgrades(meeting_id: str) -> Dict[str, Any]:
    """Replay a meeting's ledger over its canonical transcript.json atomically."""
    from api.services.meetings.meeting_recorder import MeetingRecorder

    meeting_dir = MeetingRecorder.get_meeting_directory(meeting_id)
    transcript_path = meeting_dir / "transcript.json"
    if not transcript_path.exists():
        raise FileNotFoundError(f"Transcript not found for meeting {meeting_id}")

    with open(transcript_path, "r") as transcript_file:
        transcript = json.load(transcript_file)
    if not isinstance(transcript, dict):
        raise ValueError(f"Transcript for meeting {meeting_id} must be a JSON object")

    upgraded = apply_recorded_window_upgrades(meeting_dir, transcript)
    _atomic_write_json(transcript_path, upgraded)
    return upgraded


def _load_ledger(ledger_path: Path) -> Dict[str, Any]:
    """Load and validate a ledger, treating its absence as no prior upgrades."""
    if not ledger_path.exists():
        return {"version": _LEDGER_VERSION, "upgrades": []}

    try:
        with open(ledger_path, "r") as ledger_file:
            ledger = json.load(ledger_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read transcript-upgrade ledger {ledger_path}: {exc}") from exc

    if not isinstance(ledger, dict) or ledger.get("version") != _LEDGER_VERSION:
        raise ValueError(f"Invalid transcript-upgrade ledger version at {ledger_path}")
    upgrades = ledger.get("upgrades")
    if not isinstance(upgrades, list):
        raise ValueError(f"Invalid transcript-upgrade ledger upgrades at {ledger_path}")

    for upgrade in upgrades:
        if not isinstance(upgrade, dict):
            raise ValueError(f"Invalid transcript-upgrade entry at {ledger_path}")
        start = upgrade.get("start_seconds")
        end = upgrade.get("end_seconds")
        segments = upgrade.get("segments")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            raise ValueError(f"Invalid transcript-upgrade range at {ledger_path}")
        if end <= start or not isinstance(segments, list):
            raise ValueError(f"Invalid transcript-upgrade entry at {ledger_path}")
        upgrade["segments"] = [_normalize_segment(segment) for segment in segments]
    return ledger


def _normalize_segment(segment: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize persisted window output to the canonical transcript shape."""
    if not isinstance(segment, dict):
        raise ValueError("Transcript-upgrade segments must be objects")
    start = segment.get("start")
    end = segment.get("end")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        raise ValueError("Transcript-upgrade segments require numeric start and end")
    return {
        "start": float(start),
        "end": float(end),
        "text": str(segment.get("text", "")).strip(),
        "speaker": segment.get("speaker"),
    }


def _atomic_write_json(path: Path, value: Dict[str, Any]) -> None:
    """Atomically write JSON within the target directory."""
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
