"""Output-stage repetition/non-speech degeneration guard for live transcription.

The live SimulStreaming decoder occasionally falls into a token-repetition loop
on non-speech audio (music, hold tones, applause) - the classic
``no, no, no, ...`` / ``the blue, the blue, ...`` / ``[Music] [Music] ...``
runs that fill a bubble in the live transcript but never appear in the
offline retranscription (which has its own guards). The streaming decoder's
only non-speech defense fires at segment start on Whisper's ``no_speech``
token, which music does not trigger, so these loops slip through.

This module is the live analog of the hosted-API
``degeneration_guard`` (which keys on punctuation-only runs): it operates on
the *decoder output* (committed word tokens), keyed purely on degenerate
*structure* - a unit repeated far more than humans repeat words, or runs of
bracketed non-speech markers. Legible speech never has that structure, so the
guard has no recall cost and is independent of the (deliberately lenient)
per-source VAD input gate. Detected runs are collapsed to leave an honest gap
that on-stop retranscription fills.

Because a loop can span multiple ``process_iter`` commits, the detector accepts
a small ``carry`` describing the trailing run of the previous commit and
returns an updated one; :class:`RepetitionDegenerationTracker` holds that state
per audio source.

It is pure (no torch/model imports) so the decision is unit-testable in
isolation, mirroring ``token_timeline`` and ``vad_threshold_policy``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Microphone / fallback streams are clean close-talking speech that rarely
# degenerates, so they get the more conservative thresholds (a human can say
# "no, no, no" a handful of times). Mirrors STRICT_SOURCES in
# ``vad_threshold_policy`` so the two source policies stay aligned.
STRICT_SOURCES = frozenset({"microphone", "unknown"})

# Inner-text keywords that mark a token as a non-speech annotation rather than
# spoken words. Matched against the normalized token text.
_MARKER_KEYWORDS = frozenset(
    {
        "music",
        "blank_audio",
        "blankaudio",
        "inaudible",
        "applause",
        "silence",
        "noise",
        "laughter",
        "foreign",
    }
)


@dataclass(frozen=True)
class RepetitionPolicy:
    """Thresholds governing what counts as a degenerate run.

    - ``run_threshold``: consecutive repeats of a single normalized word before
      the run is treated as a loop (only copies beyond the first are dropped).
    - ``max_cycle_len`` / ``cycle_threshold``: a repeating phrase up to
      ``max_cycle_len`` words long, repeated ``cycle_threshold`` times, is a loop
      (e.g. "the blue, the blue, ...").
    - ``marker_run_threshold``: consecutive non-speech markers (e.g. ``[Music]``)
      before the whole run is dropped (markers carry no spoken content, so none
      are kept).
    """

    run_threshold: int
    max_cycle_len: int
    cycle_threshold: int
    marker_run_threshold: int


# Conservative profile = microphone / unknown / empty sources.
STRICT_POLICY = RepetitionPolicy(
    run_threshold=8,
    max_cycle_len=3,
    cycle_threshold=5,
    marker_run_threshold=4,
)

# Eager profile = system/produced audio, where music-driven loops concentrate.
LENIENT_POLICY = RepetitionPolicy(
    run_threshold=6,
    max_cycle_len=3,
    cycle_threshold=4,
    marker_run_threshold=3,
)


def repetition_policy_for_source(source: Optional[str]) -> RepetitionPolicy:
    """Return the :class:`RepetitionPolicy` for the given audio source name.

    Microphone, ``"unknown"``, and empty/``None`` sources use the conservative
    profile; any other named source (system audio) uses the eager profile.
    """
    normalized = (source or "").strip()
    if not normalized or normalized.lower() in STRICT_SOURCES:
        return STRICT_POLICY
    return LENIENT_POLICY


def _token_is_silence(token: Any) -> bool:
    """Return True when a token is a silence marker rather than speech.

    Defensive about a foreign token type lacking ``is_silence`` so it is treated
    as speech rather than crashing (matches ``token_timeline._token_is_silence``).
    """
    is_silence = getattr(token, "is_silence", None)
    if callable(is_silence):
        try:
            return bool(is_silence())
        except Exception:
            return False
    return False


def _normalize(text: str) -> str:
    """Lower-case and keep only alphanumerics/spaces, collapsing whitespace.

    Word tokens like ``" no,"`` / ``" I."`` / ``"blue,"`` normalize to ``"no"`` /
    ``"i"`` / ``"blue"`` so attached punctuation/casing does not hide a run.
    Pure-punctuation tokens normalize to ``""`` (treated as non-participating).
    """
    kept = [ch.lower() if (ch.isalnum() or ch.isspace()) else " " for ch in text]
    return " ".join("".join(kept).split())


def _is_nonspeech_marker(text: str) -> bool:
    """Return True when a token reads as a non-speech annotation.

    Matches bracket/parenthesis-wrapped tokens (``[Music]``, ``(upbeat music)``)
    and bare known markers. Split markers (e.g. ``"[MUSIC"``) are not relied on
    here; the ordinary repetition detector backstops them at its higher
    threshold, so marker handling only *lowers* the threshold, never gates it.
    """
    stripped = text.strip()
    if not stripped:
        return False
    if stripped[0] == "[" and stripped[-1] == "]":
        return True
    if stripped[0] == "(" and stripped[-1] == ")":
        return True
    normalized = _normalize(text).replace(" ", "_")
    return normalized in _MARKER_KEYWORDS


def _trailing_run(
    norms: Sequence[Optional[str]], max_cycle_len: int
) -> Tuple[Tuple[str, ...], int]:
    """Return the ``(unit, repeat_count)`` of the longest repeating suffix.

    ``unit`` is the repeating phrase (as normalized tokens) and ``repeat_count``
    how many times it repeats at the very end of ``norms``. Empty when the final
    token does not participate in any repetition.
    """
    n = len(norms)
    if n == 0 or norms[-1] is None:
        return ((), 0)

    best_unit: Tuple[str, ...] = ()
    best_reps = 0
    for period in range(1, max_cycle_len + 1):
        if period > n:
            break
        unit = norms[n - period : n]
        if any(u is None for u in unit):
            continue
        reps = 0
        idx = n
        while idx - period >= 0 and list(norms[idx - period : idx]) == list(unit):
            reps += 1
            idx -= period
        if reps >= 1 and reps * period > best_reps * len(best_unit or (None,)):
            best_unit = tuple(u for u in unit if u is not None)
            best_reps = reps
    return (best_unit, best_reps)


def _degenerate_real_drop_indices(
    norms: List[Optional[str]],
    markers: List[bool],
    *,
    phantom_len: int,
    policy: RepetitionPolicy,
) -> set:
    """Indices (into the real region, phantom-relative) to drop as degenerate.

    Scans the combined phantom+real normalized sequence for the
    highest-coverage consecutive repetition at each position; when a run meets
    its threshold, keeps the first ``keep`` units and marks the remainder for
    dropping. Only indices in the real region (``>= phantom_len``) are returned,
    re-based to real-token coordinates.
    """
    n = len(norms)
    drop: set = set()
    i = 0
    while i < n:
        if norms[i] is None:
            i += 1
            continue

        best_period = 0
        best_reps = 0
        best_end = i
        for period in range(1, policy.max_cycle_len + 1):
            if i + period > n:
                break
            unit = norms[i : i + period]
            if any(u is None for u in unit):
                continue
            reps = 1
            j = i + period
            while j + period <= n and norms[j : j + period] == unit:
                reps += 1
                j += period
            if reps >= 2 and reps * period > best_reps * max(best_period, 1):
                best_period, best_reps, best_end = period, reps, j

        if best_period == 0:
            i += 1
            continue

        if best_period == 1 and markers[i]:
            threshold, keep = policy.marker_run_threshold, 0
        elif best_period == 1:
            threshold, keep = policy.run_threshold, 1
        else:
            threshold, keep = policy.cycle_threshold, 1

        if best_reps >= threshold:
            drop_start = i + keep * best_period
            for k in range(drop_start, best_end):
                if k >= phantom_len:
                    drop.add(k - phantom_len)
            i = best_end
        else:
            i += 1
    return drop


def trim_degenerate_repetition(
    tokens: List[Any],
    *,
    carry: Optional[Dict[str, Any]] = None,
    policy: RepetitionPolicy,
) -> Tuple[List[Any], Dict[str, Any]]:
    """Drop degenerate repetition runs from a commit's tokens.

    ``carry`` describes the trailing run of the previous commit
    (``{"unit": tuple, "count": int}``); a loop continuing it is suppressed even
    though it crosses the commit boundary. Returns the kept tokens (original
    objects, order preserved, silence/punctuation untouched) and the updated
    carry to thread into the next call.
    """
    next_empty_carry: Dict[str, Any] = {"unit": (), "count": 0}
    if not tokens:
        return tokens, (carry or next_empty_carry)

    norms: List[Optional[str]] = []
    markers: List[bool] = []
    for token in tokens:
        if _token_is_silence(token):
            norms.append(None)
            markers.append(False)
            continue
        text = str(getattr(token, "text", "") or "")
        normalized = _normalize(text)
        if not normalized:
            norms.append(None)
            markers.append(False)
        else:
            norms.append(normalized)
            markers.append(_is_nonspeech_marker(text))

    carry = carry or next_empty_carry
    carry_unit: Tuple[str, ...] = tuple(carry.get("unit") or ())
    carry_count = int(carry.get("count") or 0)

    # Prepend a (capped) phantom copy of the prior trailing run so a loop that
    # crosses the commit boundary is detected. Beyond threshold the behavior is
    # identical, so the cap bounds cost without changing the outcome.
    phantom_norms: List[Optional[str]] = []
    if carry_unit and carry_count > 0:
        cap_units = policy.run_threshold + policy.max_cycle_len
        phantom_norms = list(carry_unit) * min(carry_count, cap_units)
    phantom_len = len(phantom_norms)

    combined_norms: List[Optional[str]] = phantom_norms + norms
    combined_markers: List[bool] = [False] * phantom_len + markers

    drop = _degenerate_real_drop_indices(
        combined_norms, combined_markers, phantom_len=phantom_len, policy=policy
    )

    kept = [token for idx, token in enumerate(tokens) if idx not in drop]

    unit, count = _trailing_run(combined_norms, policy.max_cycle_len)
    new_carry: Dict[str, Any] = {"unit": unit, "count": count}
    return kept, new_carry


class RepetitionDegenerationTracker:
    """Stateful per-source wrapper that threads ``carry`` across commits."""

    def __init__(self, policy: RepetitionPolicy):
        self.policy = policy
        self._carry: Dict[str, Any] = {"unit": (), "count": 0}

    def filter(self, tokens: List[Any]) -> List[Any]:
        kept, self._carry = trim_degenerate_repetition(
            tokens, carry=self._carry, policy=self.policy
        )
        return kept

    def reset(self) -> None:
        self._carry = {"unit": (), "count": 0}
