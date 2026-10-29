"""Upload-budget chunking helpers for timestamped OpenAI transcription."""

from __future__ import annotations

import io
import math
import wave
from typing import Any, Dict, List, Tuple

from .pcm_analysis import pcm_rms as _pcm_rms

OPENAI_AUDIO_UPLOAD_LIMIT_BYTES = 26_214_400
OPENAI_AUDIO_UPLOAD_BUDGET_BYTES = 24 * 1024 * 1024
WAV_CHUNK_HEADER_MARGIN_BYTES = 4096
TARGET_WAV_CHUNK_SECONDS = 6 * 60
# Meeting audio is captured as 16 kHz mono 16-bit PCM (32,000 bytes/sec). We use
# this fixed rate to translate the target chunk *duration* into a byte size so
# the API path can route on duration using file size as a stand-in, without
# re-parsing the WAV. Revisit if the capture format ever changes.
MEETING_PCM_BYTES_PER_SECOND = 32_000
# Audio larger than one target chunk (~6 min) is split into chunks rather than
# sent as a single oversized request.
SINGLE_REQUEST_MAX_BYTES = TARGET_WAV_CHUNK_SECONDS * MEETING_PCM_BYTES_PER_SECOND
QUIET_SPLIT_SEARCH_RADIUS_SECONDS = 45
QUIET_SPLIT_WINDOW_SECONDS = 0.2
MIN_QUIET_SPLIT_SECONDS = 0.7
MIN_WAV_CHUNK_SECONDS = 30


def is_wav_file_bytes(audio_data: bytes) -> bool:
    """Return whether bytes look like a RIFF/WAVE file."""
    return (
        len(audio_data) >= 12
        and audio_data[:4] == b"RIFF"
        and audio_data[8:12] == b"WAVE"
    )


def split_wav_for_upload_budget(
    wav_bytes: bytes,
    *,
    upload_budget_bytes: int = OPENAI_AUDIO_UPLOAD_BUDGET_BYTES,
    header_margin_bytes: int = WAV_CHUNK_HEADER_MARGIN_BYTES,
) -> List[Tuple[bytes, float, float]]:
    """Split a PCM WAV into chunks that fit the configured upload budget."""
    if upload_budget_bytes <= header_margin_bytes:
        raise ValueError("OpenAI upload budget is too small to build WAV chunks")

    with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
        channels = reader.getnchannels()
        sample_width = reader.getsampwidth()
        frame_rate = reader.getframerate()
        total_frames = reader.getnframes()
        comp_type = reader.getcomptype()
        comp_name = reader.getcompname()

        if frame_rate <= 0 or channels <= 0 or sample_width <= 0:
            raise ValueError("Cannot chunk WAV with invalid audio parameters")
        if comp_type != "NONE":
            raise ValueError("Cannot chunk compressed WAV audio for API re-transcription")

        bytes_per_frame = channels * sample_width
        max_audio_bytes = upload_budget_bytes - header_margin_bytes
        max_frames_per_chunk = max(1, max_audio_bytes // bytes_per_frame)
        target_frames_per_chunk = min(
            max_frames_per_chunk,
            max(1, int(TARGET_WAV_CHUNK_SECONDS * frame_rate)),
        )
        min_frames_per_chunk = min(
            max_frames_per_chunk,
            max(1, int(MIN_WAV_CHUNK_SECONDS * frame_rate)),
        )
        all_frames = reader.readframes(total_frames)

        chunks: List[Tuple[bytes, float, float]] = []
        start_frame = 0
        while start_frame < total_frames:
            remaining_frames = total_frames - start_frame
            if remaining_frames <= target_frames_per_chunk:
                end_frame = total_frames
            else:
                desired_end_frame = min(
                    start_frame + target_frames_per_chunk,
                    start_frame + max_frames_per_chunk,
                    total_frames,
                )
                end_frame = _find_quiet_split_frame(
                    all_frames,
                    bytes_per_frame=bytes_per_frame,
                    sample_width=sample_width,
                    frame_rate=frame_rate,
                    start_frame=start_frame,
                    desired_end_frame=desired_end_frame,
                    min_end_frame=start_frame + min_frames_per_chunk,
                    max_end_frame=min(start_frame + max_frames_per_chunk, total_frames),
                )

            frames_to_read = end_frame - start_frame
            frame_start_byte = start_frame * bytes_per_frame
            frame_end_byte = end_frame * bytes_per_frame
            frame_bytes = all_frames[frame_start_byte:frame_end_byte]
            if not frame_bytes:
                break

            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as writer:
                writer.setnchannels(channels)
                writer.setsampwidth(sample_width)
                writer.setframerate(frame_rate)
                writer.setcomptype(comp_type, comp_name)
                writer.writeframes(frame_bytes)

            chunk_bytes = buffer.getvalue()
            if len(chunk_bytes) > upload_budget_bytes:
                raise ValueError(
                    "Unable to split meeting audio below OpenAI's upload limit "
                    f"({len(chunk_bytes)} bytes > {upload_budget_bytes} byte budget)"
                )

            chunk_start_seconds = start_frame / frame_rate
            chunk_end_seconds = (start_frame + frames_to_read) / frame_rate
            chunks.append((chunk_bytes, chunk_start_seconds, chunk_end_seconds))
            start_frame = end_frame

    return chunks


def _find_quiet_split_frame(
    frame_bytes: bytes,
    *,
    bytes_per_frame: int,
    sample_width: int,
    frame_rate: int,
    start_frame: int,
    desired_end_frame: int,
    min_end_frame: int,
    max_end_frame: int,
) -> int:
    """Find a quiet split point near the target boundary, or return the target."""
    min_end_frame = max(start_frame + 1, min_end_frame)
    max_end_frame = max(min_end_frame, max_end_frame)
    desired_end_frame = min(max(desired_end_frame, min_end_frame), max_end_frame)

    search_radius_frames = max(1, int(QUIET_SPLIT_SEARCH_RADIUS_SECONDS * frame_rate))
    search_start = max(min_end_frame, desired_end_frame - search_radius_frames)
    search_end = min(max_end_frame, desired_end_frame + search_radius_frames)
    window_frames = max(1, int(QUIET_SPLIT_WINDOW_SECONDS * frame_rate))
    min_quiet_windows = max(1, math.ceil(MIN_QUIET_SPLIT_SECONDS / QUIET_SPLIT_WINDOW_SECONDS))

    windows = []
    for frame in range(search_start, search_end, window_frames):
        window_end = min(frame + window_frames, search_end)
        start_byte = frame * bytes_per_frame
        end_byte = window_end * bytes_per_frame
        window_bytes = frame_bytes[start_byte:end_byte]
        if not window_bytes:
            continue
        windows.append((frame, window_end, _pcm_rms(window_bytes, sample_width)))

    if not windows:
        return desired_end_frame

    max_rms = max(rms for _, _, rms in windows)
    full_scale = float(1 << ((8 * sample_width) - 1))
    quiet_threshold = max(full_scale * 0.005, max_rms * 0.08)

    best_candidate = None
    best_distance = None
    run_start = None
    run_end = None
    run_count = 0

    def consider_run() -> None:
        nonlocal best_candidate, best_distance
        if run_start is None or run_end is None or run_count < min_quiet_windows:
            return
        candidate = (run_start + run_end) // 2
        if candidate < min_end_frame or candidate > max_end_frame:
            return
        distance = abs(candidate - desired_end_frame)
        if best_distance is None or distance < best_distance:
            best_candidate = candidate
            best_distance = distance

    for window_start, window_end, rms in windows:
        if rms <= quiet_threshold:
            if run_start is None:
                run_start = window_start
            run_end = window_end
            run_count += 1
        else:
            consider_run()
            run_start = None
            run_end = None
            run_count = 0
    consider_run()

    return best_candidate if best_candidate is not None else desired_end_frame


def offset_timestamped_segments(
    segments: List[Dict[str, Any]],
    *,
    offset_seconds: float,
    chunk_end_seconds: float,
) -> List[Dict[str, Any]]:
    """Convert chunk-local segment timestamps into meeting-global timestamps."""
    adjusted_segments: List[Dict[str, Any]] = []
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue

        start = min(max(0.0, float(segment["start"]) + offset_seconds), chunk_end_seconds)
        end = max(start, float(segment["end"]) + offset_seconds)
        adjusted_segments.append({
            "start": start,
            "end": min(end, chunk_end_seconds),
            "text": text,
        })
    return adjusted_segments
