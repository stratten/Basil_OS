"""Windowed (closed-range) re-transcription for incremental upgrades.

Re-transcribes a closed ``[start, end)`` range of a meeting's full-length
``audio.wav`` and splices the higher-quality segments back into the per-track
transcript. This backs:

- threshold-based incremental re-transcription while recording continues
  (checkpoints derived from the model's ``chunk_seconds`` registry value, 2A), and
- on-stop behavior: re-transcribe only the tail since the last checkpoint when
  thresholds are enabled, otherwise the whole recording.

The actual ASR work reuses ``TranscriptionProcessor`` (and therefore its cached
model loaders) on a temporary WAV of the window, so no model-loading logic is
duplicated. All time math and splicing is pure and unit-tested; the ASR runner
is injectable so tests can exercise the splice deterministically.
"""

from __future__ import annotations

import logging
import os
import tempfile
import wave
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cadence / range planning (pure)
# ---------------------------------------------------------------------------

def windowed_checkpoints(total_seconds: float, chunk_seconds: float) -> List[Tuple[float, float]]:
    """Closed ranges covering ``[0, total_seconds)`` at ``chunk_seconds`` cadence."""
    if total_seconds <= 0 or chunk_seconds <= 0:
        return []
    ranges: List[Tuple[float, float]] = []
    start = 0.0
    while start < total_seconds - 1e-6:
        end = min(start + chunk_seconds, total_seconds)
        ranges.append((round(start, 3), round(end, 3)))
        start = end
    return ranges


def next_checkpoint_end(
    elapsed_seconds: float,
    chunk_seconds: float,
    last_checkpoint_seconds: float,
) -> Optional[float]:
    """Next chunk boundary at/under ``elapsed_seconds`` past the last checkpoint.

    Returns ``None`` when no new full chunk-window has elapsed since the last
    checkpoint, so callers only trigger a window once a full ``chunk_seconds``
    of new audio is available.
    """
    if chunk_seconds <= 0 or elapsed_seconds <= 0:
        return None
    completed_chunks = int(elapsed_seconds // chunk_seconds)
    boundary = completed_chunks * chunk_seconds
    if boundary > last_checkpoint_seconds + 1e-6:
        return round(boundary, 3)
    return None


def plan_on_stop_window(
    thresholds_enabled: bool,
    last_checkpoint_seconds: float,
    total_seconds: float,
) -> Tuple[float, float]:
    """Closed ``[start, end)`` to re-transcribe when recording stops.

    With thresholds enabled, only the tail ``[last_checkpoint, total)`` remains
    un-upgraded; otherwise the whole recording is re-transcribed.
    """
    if total_seconds <= 0:
        return (0.0, 0.0)
    if thresholds_enabled and last_checkpoint_seconds > 0:
        start = min(max(0.0, last_checkpoint_seconds), total_seconds)
        return (round(start, 3), round(total_seconds, 3))
    return (0.0, round(total_seconds, 3))


# ---------------------------------------------------------------------------
# Segment math (pure)
# ---------------------------------------------------------------------------

def offset_segments(segments: List[Dict[str, Any]], start_seconds: float) -> List[Dict[str, Any]]:
    """Shift window-relative segment times onto the absolute meeting timeline."""
    offset: List[Dict[str, Any]] = []
    for seg in segments:
        shifted = dict(seg)
        shifted["start"] = seg["start"] + start_seconds
        shifted["end"] = seg["end"] + start_seconds
        offset.append(shifted)
    return offset


def _overlaps(segment: Dict[str, Any], start_seconds: float, end_seconds: float) -> bool:
    return segment["end"] > start_seconds and segment["start"] < end_seconds


def splice_segments(
    existing: List[Dict[str, Any]],
    new_segments: List[Dict[str, Any]],
    start_seconds: float,
    end_seconds: float,
) -> List[Dict[str, Any]]:
    """Replace existing segments overlapping ``[start, end)`` with ``new_segments``.

    ``new_segments`` are expected on the absolute timeline (already offset). The
    result keeps every non-overlapping existing segment, drops the ones the
    window supersedes, inserts the new ones, and sorts by start time so the
    spliced output carries no overlapping ranges introduced by the boundary.
    """
    kept = [seg for seg in existing if not _overlaps(seg, start_seconds, end_seconds)]
    merged = kept + list(new_segments)
    merged.sort(key=lambda seg: (seg["start"], seg["end"]))
    return merged


# ---------------------------------------------------------------------------
# Audio window IO
# ---------------------------------------------------------------------------

# Canonical PCM WAV header size produced by the stdlib ``wave`` writer
# (RIFF 12 + fmt 24 + data 8). The meeting recorder writes exactly this layout,
# so a live reader can locate the PCM payload at this fixed offset without
# trusting the (un-patched, mid-recording) data-chunk size in the header.
_WAV_HEADER_BYTES = 44


def read_audio_window(
    audio_path: Path,
    start_seconds: float,
    end_seconds: float,
) -> Tuple[bytes, int, int, int]:
    """Read raw PCM frames for ``[start, end)`` from a WAV file.

    Returns ``(frames, sample_rate, sample_width, channels)``; ``frames`` is
    empty when the requested range is empty or out of bounds.
    """
    with wave.open(str(audio_path), "rb") as wav:
        rate = wav.getframerate()
        sample_width = wav.getsampwidth()
        channels = wav.getnchannels()
        total_frames = wav.getnframes()
        if rate <= 0:
            return (b"", rate, sample_width, channels)
        start_frame = max(0, int(start_seconds * rate))
        end_frame = min(total_frames, int(end_seconds * rate))
        if end_frame <= start_frame:
            return (b"", rate, sample_width, channels)
        wav.setpos(start_frame)
        frames = wav.readframes(end_frame - start_frame)
        return (frames, rate, sample_width, channels)


def read_audio_window_live(
    audio_path: Path,
    start_seconds: float,
    end_seconds: float,
) -> Tuple[bytes, int, int, int]:
    """Read ``[start, end)`` PCM from a WAV that is still being written.

    The meeting recorder keeps the WAV open during recording and only patches
    the header's frame count on ``stop_recording()``. The format fields
    (rate/width/channels) are valid from the first write, but the frame count is
    not. So we read the format from the header, derive the number of available
    frames from the on-disk file size (minus the fixed PCM header), and read the
    requested byte range directly from a fresh read handle - never trusting
    ``getnframes()``.

    Returns ``(frames, sample_rate, sample_width, channels)``; ``frames`` is
    empty when the requested range is empty or not yet available on disk.
    """
    with wave.open(str(audio_path), "rb") as wav:
        rate = wav.getframerate()
        sample_width = wav.getsampwidth()
        channels = wav.getnchannels()
    if rate <= 0:
        return (b"", rate, sample_width, channels)
    block_align = sample_width * channels
    if block_align <= 0:
        return (b"", rate, sample_width, channels)

    file_size = os.path.getsize(audio_path)
    data_bytes = max(0, file_size - _WAV_HEADER_BYTES)
    total_frames = data_bytes // block_align

    start_frame = max(0, int(start_seconds * rate))
    end_frame = min(total_frames, int(end_seconds * rate))
    if end_frame <= start_frame:
        return (b"", rate, sample_width, channels)

    with open(audio_path, "rb") as raw:
        raw.seek(_WAV_HEADER_BYTES + start_frame * block_align)
        frames = raw.read((end_frame - start_frame) * block_align)
    return (frames, rate, sample_width, channels)


def write_window_wav(
    frames: bytes,
    rate: int,
    sample_width: int,
    channels: int,
    out_path: Path,
) -> None:
    """Write raw PCM frames to a WAV file with the given format."""
    with wave.open(str(out_path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(rate)
        wav.writeframes(frames)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

# A runner transcribes raw window frames and returns window-relative segments.
WindowRunner = Callable[
    [bytes, int, int, int, float, str, Optional[Callable]],
    Awaitable[List[Dict[str, Any]]],
]


async def _default_run_transcription(
    frames: bytes,
    rate: int,
    sample_width: int,
    channels: int,
    window_duration: float,
    model_id: str,
    progress_callback: Optional[Callable] = None,
) -> List[Dict[str, Any]]:
    """Default runner: reuse ``TranscriptionProcessor`` on a temp WAV of the window."""
    from .transcription_processor import TranscriptionProcessor

    fd, tmp_name = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        write_window_wav(frames, rate, sample_width, channels, tmp_path)
        processor = TranscriptionProcessor(tmp_path, window_duration, model_id)

        async def _cb(stage_progress, current_time, message, eta_seconds, new_segments=None):
            if progress_callback is not None:
                await progress_callback(stage_progress, current_time, message, eta_seconds, new_segments)

        return await processor.transcribe_with_selected_model(_cb)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


async def transcribe_window(
    meeting_id: str,
    start_seconds: float,
    end_seconds: float,
    model_id: str,
    *,
    audio_path: Optional[Path] = None,
    progress_callback: Optional[Callable] = None,
    run_transcription: Optional[WindowRunner] = None,
    live: bool = False,
) -> List[Dict[str, Any]]:
    """Re-transcribe ``[start, end)`` of a meeting's audio, returning absolute-timeline segments.

    When ``live`` is true the audio file is assumed to be mid-recording (still
    open and growing), so a header-independent reader is used.
    """
    if audio_path is None:
        from api.services.meetings.meeting_recorder import MeetingRecorder

        audio_path = MeetingRecorder.get_meeting_directory(meeting_id) / "audio.wav"

    reader = read_audio_window_live if live else read_audio_window
    frames, rate, sample_width, channels = reader(audio_path, start_seconds, end_seconds)
    if not frames:
        logger.info(
            "Windowed re-transcription for %s [%.2f, %.2f) produced no audio frames",
            meeting_id, start_seconds, end_seconds,
        )
        return []

    runner = run_transcription or _default_run_transcription
    window_duration = max(0.0, end_seconds - start_seconds)
    raw_segments = await runner(
        frames, rate, sample_width, channels, window_duration, model_id, progress_callback
    )
    return offset_segments(raw_segments, start_seconds)


async def retranscribe_window_and_splice(
    meeting_id: str,
    start_seconds: float,
    end_seconds: float,
    model_id: str,
    *,
    audio_path: Optional[Path] = None,
    run_transcription: Optional[WindowRunner] = None,
    load_transcript: Optional[Callable[[Path], Dict[str, Any]]] = None,
    save_transcript: Optional[Callable[[Dict[str, Any], Path], Awaitable[None]]] = None,
    transcript_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Re-transcribe a window and splice it into the saved per-track transcript.

    Returns the updated transcript dict. IO collaborators are injectable for
    testing; defaults read/write the meeting's ``transcript.json``.
    """
    from .transcript_merger import (
        load_transcript_from_file,
        save_transcript_to_file,
    )

    load_fn = load_transcript or load_transcript_from_file
    save_fn = save_transcript or save_transcript_to_file

    if transcript_path is None:
        from api.services.meetings.meeting_recorder import MeetingRecorder

        meeting_dir = MeetingRecorder.get_meeting_directory(meeting_id)
        transcript_path = meeting_dir / "transcript.json"
        if audio_path is None:
            audio_path = meeting_dir / "audio.wav"

    transcript = load_fn(transcript_path)
    existing_segments = list(transcript.get("segments", []))

    new_segments = await transcribe_window(
        meeting_id,
        start_seconds,
        end_seconds,
        model_id,
        audio_path=audio_path,
        run_transcription=run_transcription,
    )
    # Preserve the unlabeled-speaker shape of stored transcript segments.
    normalized_new = [
        {
            "start": seg["start"],
            "end": seg["end"],
            "text": str(seg.get("text", "")).strip(),
            "speaker": seg.get("speaker"),
        }
        for seg in new_segments
    ]
    transcript["segments"] = splice_segments(
        existing_segments, normalized_new, start_seconds, end_seconds
    )

    await save_fn(transcript, transcript_path)
    return transcript
