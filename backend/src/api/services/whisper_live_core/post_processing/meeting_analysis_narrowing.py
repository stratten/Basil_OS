"""Narrow the suggested-actions transcript to the windows cited by action items."""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, Iterable, Optional

from .meeting_analysis_coverage import (
    estimate_model_tokens,
    format_transcript_segments,
)

logger = logging.getLogger(__name__)

NARROWING_WINDOW_SECONDS = 90.0
MIN_TRANSCRIPT_TOKENS_FOR_NARROWING = 6000


def _cited_timestamp(item: Any) -> Optional[float]:
    raw = item.get("timestamp") if isinstance(item, dict) else getattr(item, "timestamp", None)
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0.0:
        return None
    return value


def narrow_transcript_for_suggestions(
    transcript: Dict[str, Any],
    action_items: Optional[Iterable[Any]],
    model: Any = None,
) -> Dict[str, Any]:
    """Return a transcript holding only segments near cited action-item timestamps.

    The full transcript is returned unchanged when there are no action items, any
    item lacks a usable timestamp, the transcript is short, or the windows would not
    remove anything. Callers must still validate model timestamps against the full
    transcript.
    """
    segments = transcript.get("segments") or []
    items = list(action_items or [])
    if not segments or not items:
        return transcript
    cited = []
    for item in items:
        timestamp = _cited_timestamp(item)
        if timestamp is None:
            return transcript
        cited.append(timestamp)
    full_tokens = estimate_model_tokens(
        "\n".join(format_transcript_segments(transcript)), model
    )
    if full_tokens < MIN_TRANSCRIPT_TOKENS_FOR_NARROWING:
        return transcript
    selected = []
    for segment in segments:
        start = float(segment.get("start", 0.0))
        end = max(start, float(segment.get("end", start)))
        if any(
            start <= timestamp + NARROWING_WINDOW_SECONDS
            and end >= timestamp - NARROWING_WINDOW_SECONDS
            for timestamp in cited
        ):
            selected.append(segment)
    if not selected or len(selected) == len(segments):
        return transcript
    logger.info(
        "Narrowed suggested-actions transcript from %s to %s segments around %s cited timestamps",
        len(segments),
        len(selected),
        len(cited),
    )
    narrowed = dict(transcript)
    narrowed["segments"] = selected
    return narrowed
