"""Shared little-endian PCM amplitude analysis helpers.

These are intentionally dependency-free (no numpy) so they can be used from
both the upload-budget chunker and the leading-silence trimmer without pulling
extra imports into the hot transcription path.
"""

from __future__ import annotations

import math
from typing import List, Tuple


def pcm_rms(pcm_bytes: bytes, sample_width: int) -> float:
    """Compute RMS amplitude for little-endian PCM samples."""
    if sample_width <= 0:
        return 0.0

    total = 0.0
    count = 0
    usable_length = len(pcm_bytes) - (len(pcm_bytes) % sample_width)
    for offset in range(0, usable_length, sample_width):
        sample_bytes = pcm_bytes[offset:offset + sample_width]
        if sample_width == 1:
            sample = sample_bytes[0] - 128
        else:
            sample = int.from_bytes(sample_bytes, byteorder="little", signed=True)
        total += float(sample * sample)
        count += 1

    if count == 0:
        return 0.0
    return math.sqrt(total / count)


def windowed_rms(
    frame_bytes: bytes,
    *,
    bytes_per_frame: int,
    sample_width: int,
    window_frames: int,
) -> List[Tuple[int, int, float]]:
    """Return ``(start_frame, end_frame, rms)`` for each fixed-size window.

    Windows are measured in frames (a frame is ``bytes_per_frame`` bytes, i.e.
    one sample across all channels). The final window may be shorter than
    ``window_frames`` when the audio length is not an exact multiple.
    """
    if bytes_per_frame <= 0 or window_frames <= 0:
        return []

    total_frames = len(frame_bytes) // bytes_per_frame
    results: List[Tuple[int, int, float]] = []
    for start_frame in range(0, total_frames, window_frames):
        end_frame = min(start_frame + window_frames, total_frames)
        start_byte = start_frame * bytes_per_frame
        end_byte = end_frame * bytes_per_frame
        window_bytes = frame_bytes[start_byte:end_byte]
        if not window_bytes:
            continue
        results.append((start_frame, end_frame, pcm_rms(window_bytes, sample_width)))

    return results
