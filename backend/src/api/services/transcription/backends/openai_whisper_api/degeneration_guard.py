"""Detect Whisper non-speech degeneration in a chunk's returned segments.

Even after trimming leading silence, the hosted ``whisper-1`` decoder can fall
into a non-speech loop (e.g. a long quiet stretch mid-chunk) and emit a run of
punctuation-only tokens - the classic 74x ``"."`` pattern that overwrote a real
six-minute span. This guard recognizes that shape so the caller can drop the
garbage (leaving an honest gap) instead of merging it into the transcript.

It deliberately keys on *punctuation-only* text (no alphanumerics), so genuine
repeated backchannel like ``"Yeah"`` or ``"Mm hmm"`` is never flagged.
"""

from __future__ import annotations

from typing import Any, Dict, List

# A chunk needs at least this many segments before we even consider it
# degenerate (a couple of stray "." segments are not a degeneration loop).
MIN_DEGEN_SEGMENTS = 5
# This fraction of segments must be punctuation-only.
DEGEN_TRIVIAL_FRACTION = 0.9
# ...and those trivial segments must cover this fraction of the chunk duration.
DEGEN_SPAN_FRACTION = 0.8


def _is_trivial_text(text: str) -> bool:
    """Return True when text carries no alphanumeric content."""
    return not any(char.isalnum() for char in text)


def is_degenerate_segment_run(
    segments: List[Dict[str, Any]],
    *,
    chunk_duration_seconds: float,
) -> bool:
    """Return True if a chunk's segments look like a non-speech degeneration loop."""
    if len(segments) < MIN_DEGEN_SEGMENTS:
        return False

    trivial_segments = []
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if _is_trivial_text(text):
            trivial_segments.append(segment)

    trivial_fraction = len(trivial_segments) / len(segments)
    if trivial_fraction < DEGEN_TRIVIAL_FRACTION:
        return False

    if chunk_duration_seconds <= 0.0:
        # No reliable duration to gate on; the overwhelming trivial fraction
        # above is already conclusive.
        return True

    trivial_span = 0.0
    for segment in trivial_segments:
        try:
            start = float(segment["start"])
            end = float(segment["end"])
        except (KeyError, TypeError, ValueError):
            continue
        trivial_span += max(0.0, end - start)

    return trivial_span >= DEGEN_SPAN_FRACTION * chunk_duration_seconds
