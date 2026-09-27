"""Token timeline assignment and silence-coverage suppression.

Extracted from ``audio_processor.py`` to keep that module focused and to make
the wall-clock timeline mapping and the silence-hallucination guard independently
testable.

- ``assign_token_timeline`` attaches meeting-elapsed timing to ASR tokens
  without changing ASR internals (formerly ``_apply_wall_clock_timeline_to_tokens``).
- ``suppress_hallucinated_silence_tokens`` drops committed speech tokens for a
  PCM chunk that carries no acoustic energy (the "engvid on silence" case),
  reusing the pure-numpy ``analyze_parakeet_audio_coverage`` RMS analyzer.
"""

from __future__ import annotations

from typing import Any, List

import numpy as np

from api.services.transcription.backends.parakeet_components.parakeet_coverage import (
    analyze_parakeet_audio_coverage,
)


def _token_is_silence(token: Any) -> bool:
    """Return True when a token is a silence marker rather than speech.

    Tokens expose ``is_silence()`` (a callable); be defensive about absence so a
    foreign token type is treated as speech rather than crashing.
    """
    is_silence = getattr(token, "is_silence", None)
    if callable(is_silence):
        try:
            return bool(is_silence())
        except Exception:
            return False
    return False


def assign_token_timeline(tokens: List[Any], stream_time_end: float) -> None:
    """Attach meeting-elapsed timing to ASR tokens without changing ASR internals.

    Maps each speech token's intrinsic ``start``/``end`` onto the wall-clock
    window ending at ``stream_time_end`` and lasting the token span's duration.
    Mutates tokens in place (sets ``timeline_start_seconds`` / ``timeline_end_seconds``).
    """
    speech_tokens = [token for token in tokens if not _token_is_silence(token)]
    if not speech_tokens:
        return

    token_starts = [token.start for token in speech_tokens if token.start is not None]
    token_ends = [token.end for token in speech_tokens if token.end is not None]
    if not token_starts or not token_ends:
        return

    token_start = min(token_starts)
    token_end = max(token_ends)
    token_duration = max(0.0, token_end - token_start)

    timeline_end = max(0.0, stream_time_end)
    timeline_start = max(0.0, timeline_end - token_duration)

    for token in speech_tokens:
        if token_duration > 0 and token.start is not None and token.end is not None:
            start_ratio = max(0.0, min(1.0, (token.start - token_start) / token_duration))
            end_ratio = max(0.0, min(1.0, (token.end - token_start) / token_duration))
            token.timeline_start_seconds = timeline_start + (start_ratio * token_duration)
            token.timeline_end_seconds = timeline_start + (end_ratio * token_duration)
        else:
            token.timeline_start_seconds = timeline_start
            token.timeline_end_seconds = timeline_end


def assign_token_timeline_from_offset(
    tokens: List[Any],
    *,
    session_origin_offset: float = 0.0,
) -> None:
    """Anchor token timing to the ASR's real absolute times (gated alternative).

    Unlike :func:`assign_token_timeline` (which repacks the token span against
    cumulative stream time and can drift), this trusts each token's intrinsic
    absolute ``start``/``end`` (derived from the ASR's ``buffer_time_offset`` /
    backend ``self.end``) and only adds the per-track ``session_origin_offset``
    from cross-track skew correction (2E).

    This is the 2G epoch-anchoring path. It is intentionally **not** wired into
    the live pipeline by default: per the plan it ships only if a live-vs-
    retranscription parity fixture confirms equivalence; otherwise the repack in
    :func:`assign_token_timeline` is retained as the validated fallback and
    on-stop re-transcription (2B) yields file-accurate timestamps regardless.
    """
    for token in tokens:
        if _token_is_silence(token):
            continue
        if token.start is None or token.end is None:
            continue
        token.timeline_start_seconds = max(0.0, session_origin_offset + token.start)
        token.timeline_end_seconds = max(0.0, session_origin_offset + token.end)


def suppress_hallucinated_silence_tokens(
    pcm_array: np.ndarray,
    tokens: List[Any],
    *,
    sample_rate: int,
    active_ratio_floor: float = 0.0,
) -> List[Any]:
    """Drop speech tokens emitted over an acoustically silent PCM chunk.

    A chunk whose windowed-RMS coverage shows no active windows
    (``active_window_ratio <= active_ratio_floor``) contains no speech, so any
    speech tokens committed for it are hallucinations and are removed. Silence
    marker tokens are always preserved. Chunks with any real energy (including
    low-but-real near-threshold speech, which produces active windows) are
    returned unchanged.
    """
    if not tokens:
        return tokens

    speech_tokens = [token for token in tokens if not _token_is_silence(token)]
    if not speech_tokens:
        # Nothing speech-like to suppress; leave as-is.
        return tokens

    if pcm_array is None or getattr(pcm_array, "size", 0) == 0 or sample_rate <= 0:
        return tokens

    coverage = analyze_parakeet_audio_coverage(pcm_array, sample_rate=sample_rate)
    if coverage.total_windows > 0 and coverage.active_window_ratio <= active_ratio_floor:
        # Fully silent chunk: keep only non-speech (silence) markers.
        return [token for token in tokens if _token_is_silence(token)]

    return tokens
