"""Trim substantial leading silence from a WAV before OpenAI transcription.

The hosted ``whisper-1`` endpoint exposes none of the decode controls
(``condition_on_previous_text=False``, ``no_speech_threshold``, temperature
fallback, etc.) that keep a local Whisper from degenerating. When a chunk
*opens* on minutes of dead air - the normal shape of a recording where the bot
joins before anyone speaks - the hosted decoder locks into a non-speech ``"."``
repetition loop for the rest of the file. We cannot fix that at the request
level, so we strip the leading dead air from the audio we upload.

Every cut is measured in whole PCM frames, so the trimmed duration is exact and
can be added back to the chunk's timeline offset with zero rounding error.
"""

from __future__ import annotations

import io
import logging
import math
import wave
from typing import Optional

from .pcm_analysis import windowed_rms

logger = logging.getLogger(__name__)

# Window granularity for energy analysis.
ONSET_WINDOW_SECONDS = 0.1
# A window counts as "speech" when its RMS exceeds this fraction of the chunk's
# peak window RMS. Relative (not absolute) so it self-calibrates to quiet mics.
ONSET_PEAK_FRACTION = 0.15
# ...but it must also clear this fraction of full scale, so an all-noise chunk
# (whose "peak" is just its own noise floor) never registers a false onset.
ONSET_ABS_FLOOR_FRACTION = 0.003
# Energy must stay above threshold this long to count as real speech (rejects
# isolated clicks/pops at the very start).
ONSET_MIN_SUSTAIN_SECONDS = 0.3
# Retain this much audio just before the detected onset so the first phoneme is
# never clipped.
ONSET_LEAD_IN_SECONDS = 0.3
# Only trim when we would remove at least this much. Keeps us from ever
# disturbing the ~0.7s quiet boundaries the chunker splits on.
MIN_LEADING_TRIM_SECONDS = 2.0


def find_speech_onset_frame(
    frame_bytes: bytes,
    *,
    bytes_per_frame: int,
    sample_width: int,
    frame_rate: int,
) -> Optional[int]:
    """Return the frame index where sustained speech first begins, or ``None``.

    ``None`` means no confident onset was found (the audio is effectively all
    silence/noise), in which case the caller should not trim.
    """
    if bytes_per_frame <= 0 or sample_width <= 0 or frame_rate <= 0:
        return None

    window_frames = max(1, int(ONSET_WINDOW_SECONDS * frame_rate))
    windows = windowed_rms(
        frame_bytes,
        bytes_per_frame=bytes_per_frame,
        sample_width=sample_width,
        window_frames=window_frames,
    )
    if not windows:
        return None

    peak = max(rms for _, _, rms in windows)
    if peak <= 0.0:
        return None

    full_scale = float(1 << ((8 * sample_width) - 1))
    threshold = max(peak * ONSET_PEAK_FRACTION, full_scale * ONSET_ABS_FLOOR_FRACTION)
    sustain_windows = max(1, math.ceil(ONSET_MIN_SUSTAIN_SECONDS / ONSET_WINDOW_SECONDS))

    run_start_frame: Optional[int] = None
    run_count = 0
    for start_frame, _end_frame, rms in windows:
        if rms >= threshold:
            if run_start_frame is None:
                run_start_frame = start_frame
            run_count += 1
            if run_count >= sustain_windows:
                return run_start_frame
        else:
            run_start_frame = None
            run_count = 0

    return None


def leading_trim_frames(
    frame_bytes: bytes,
    *,
    bytes_per_frame: int,
    sample_width: int,
    frame_rate: int,
) -> int:
    """Return how many leading frames to drop (0 = leave audio untouched)."""
    onset_frame = find_speech_onset_frame(
        frame_bytes,
        bytes_per_frame=bytes_per_frame,
        sample_width=sample_width,
        frame_rate=frame_rate,
    )
    if onset_frame is None:
        return 0

    lead_in_frames = int(ONSET_LEAD_IN_SECONDS * frame_rate)
    candidate = max(0, onset_frame - lead_in_frames)
    if candidate / frame_rate < MIN_LEADING_TRIM_SECONDS:
        return 0
    return candidate


def trim_leading_silence_wav(wav_bytes: bytes) -> tuple[bytes, float]:
    """Strip substantial leading silence from a PCM WAV.

    Returns ``(possibly_trimmed_wav_bytes, trimmed_seconds)``. ``trimmed_seconds``
    is frame-exact (``dropped_frames / frame_rate``) so callers can add it to the
    chunk's timeline offset without drift. On any unsupported/invalid audio the
    original bytes are returned unchanged with ``0.0`` trimmed.
    """
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
            channels = reader.getnchannels()
            sample_width = reader.getsampwidth()
            frame_rate = reader.getframerate()
            total_frames = reader.getnframes()
            comp_type = reader.getcomptype()
            comp_name = reader.getcompname()
            if (
                channels <= 0
                or sample_width <= 0
                or frame_rate <= 0
                or comp_type != "NONE"
            ):
                return wav_bytes, 0.0
            frame_bytes = reader.readframes(total_frames)
    except (wave.Error, EOFError, ValueError):
        return wav_bytes, 0.0

    bytes_per_frame = channels * sample_width
    drop_frames = leading_trim_frames(
        frame_bytes,
        bytes_per_frame=bytes_per_frame,
        sample_width=sample_width,
        frame_rate=frame_rate,
    )
    if drop_frames <= 0:
        return wav_bytes, 0.0

    trimmed_frame_bytes = frame_bytes[drop_frames * bytes_per_frame:]
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(sample_width)
        writer.setframerate(frame_rate)
        writer.setcomptype(comp_type, comp_name)
        writer.writeframes(trimmed_frame_bytes)

    trimmed_seconds = drop_frames / frame_rate
    logger.info(
        "Trimmed %.3fs of leading silence before OpenAI upload (%s -> %s frames)",
        trimmed_seconds,
        total_frames,
        total_frames - drop_frames,
    )
    return buffer.getvalue(), trimmed_seconds
