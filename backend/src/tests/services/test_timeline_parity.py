"""Epoch-anchoring parity harness (2G gate).

Decides whether the gated absolute-offset timeline path
(:func:`assign_token_timeline_from_offset`) can replace the repack heuristic
(:func:`assign_token_timeline`) as the live default. The offset path ships only
if a real recording confirms it tracks a full re-transcription at least as well
as the repack path; otherwise the repack heuristic remains the validated
fallback (and on-stop re-transcription yields file-accurate timestamps anyway).

The comparison math (``timeline_parity_report``) is pure and self-tested below
with an inline fixture, so the harness itself is always exercised. The
real-recording check is skipped unless a fixture is supplied.

Capturing a real fixture
------------------------
1. Record a short meeting (mic and/or system) with the live pipeline.
2. Capture, as JSON, the live ASR tokens for the session: each token's intrinsic
   absolute ``start``/``end`` (the values backing ``assign_*``), its text, and
   whether it is a silence marker; plus the cumulative ``stream_time_end`` used
   by the repack path and the per-track ``session_origin_offset`` (2E).
3. Run a full re-transcription of the same ``audio.wav`` (the validated on-stop
   path) and capture its segments as the ``ground_truth`` (file-accurate
   ``start``/``end``/``text``).
4. Write a JSON file with keys: ``tokens`` (list of
   ``{text,start,end,silence?}``), ``stream_time_end`` (float),
   ``session_origin_offset`` (float), and ``ground_truth`` (list of
   ``{text,start,end}``).
5. Point ``BASIL_TIMELINE_PARITY_FIXTURE`` at that file and run this module.

If the offset path wins (or ties) on mean start-time error, it is safe to wire
``assign_token_timeline_from_offset`` into the live pipeline; until then, do not
flip the default.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from api.services.whisper_live_core.token_timeline import (
    assign_token_timeline,
    assign_token_timeline_from_offset,
)


class _FakeToken:
    """Minimal ASR-token stand-in carrying intrinsic + assigned timeline times."""

    def __init__(self, text: str, start: float, end: float, silence: bool = False):
        self.text = text
        self.start = start
        self.end = end
        self._silence = silence
        self.timeline_start_seconds: Optional[float] = None
        self.timeline_end_seconds: Optional[float] = None

    def is_silence(self) -> bool:
        return self._silence


def _build_tokens(token_dicts: List[Dict[str, Any]]) -> List[_FakeToken]:
    return [
        _FakeToken(
            text=str(t.get("text", "")),
            start=float(t["start"]),
            end=float(t["end"]),
            silence=bool(t.get("silence", False)),
        )
        for t in token_dicts
    ]


def _alignment_error(
    assigned: List[_FakeToken],
    ground_truth: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Mean/max absolute start-time error of assigned speech tokens vs ground
    truth, matched positionally (both ordered by appearance). Compares only the
    overlapping prefix so a length mismatch never crashes the harness."""
    speech = [t for t in assigned if not t.is_silence() and t.timeline_start_seconds is not None]
    pairs = min(len(speech), len(ground_truth))
    if pairs == 0:
        return {"mean": float("inf"), "max": float("inf"), "pairs": 0.0}

    deltas = [
        abs(speech[i].timeline_start_seconds - float(ground_truth[i]["start"]))
        for i in range(pairs)
    ]
    return {
        "mean": sum(deltas) / pairs,
        "max": max(deltas),
        "pairs": float(pairs),
    }


def timeline_parity_report(
    token_dicts: List[Dict[str, Any]],
    *,
    stream_time_end: float,
    session_origin_offset: float,
    ground_truth: List[Dict[str, Any]],
) -> Dict[str, Dict[str, float]]:
    """Run both timeline strategies and report start-time error vs ground truth.

    Returns ``{"repack": {...}, "offset": {...}}`` where each inner dict holds
    ``mean``/``max``/``pairs`` absolute start-time error in seconds.
    """
    repack_tokens = _build_tokens(token_dicts)
    assign_token_timeline(repack_tokens, stream_time_end=stream_time_end)

    offset_tokens = _build_tokens(token_dicts)
    assign_token_timeline_from_offset(offset_tokens, session_origin_offset=session_origin_offset)

    return {
        "repack": _alignment_error(repack_tokens, ground_truth),
        "offset": _alignment_error(offset_tokens, ground_truth),
    }


# ---------------------------------------------------------------------------
# Self-test of the harness math (always runs; no fixture needed)
# ---------------------------------------------------------------------------

def test_parity_report_prefers_offset_when_token_times_are_accurate() -> None:
    # Tokens whose intrinsic absolute times already match the ground truth; the
    # repack path (anchored to a too-large stream_time_end) drifts, while the
    # offset path lands exactly. This validates the comparison plumbing.
    tokens = [
        {"text": "hello", "start": 100.0, "end": 100.5},
        {"text": "world", "start": 100.5, "end": 101.0},
    ]
    ground_truth = [
        {"text": "hello", "start": 100.0, "end": 100.5},
        {"text": "world", "start": 100.5, "end": 101.0},
    ]
    report = timeline_parity_report(
        tokens,
        stream_time_end=500.0,          # repack anchors the span to 500s -> drift
        session_origin_offset=0.0,
        ground_truth=ground_truth,
    )
    assert report["offset"]["mean"] < report["repack"]["mean"]
    assert report["offset"]["mean"] == pytest.approx(0.0, abs=1e-6)


def test_parity_report_handles_length_mismatch() -> None:
    tokens = [{"text": "a", "start": 1.0, "end": 1.5}]
    report = timeline_parity_report(
        tokens,
        stream_time_end=2.0,
        session_origin_offset=0.0,
        ground_truth=[],  # no ground truth pairs
    )
    assert report["offset"]["pairs"] == 0.0


# ---------------------------------------------------------------------------
# Real-recording gate (skipped unless a fixture is provided)
# ---------------------------------------------------------------------------

def _load_fixture() -> Optional[Dict[str, Any]]:
    path = os.environ.get("BASIL_TIMELINE_PARITY_FIXTURE")
    if not path:
        return None
    fixture_path = Path(path)
    if not fixture_path.exists():
        return None
    with open(fixture_path, "r") as handle:
        return json.load(handle)


def test_offset_path_matches_or_beats_repack_on_real_fixture() -> None:
    fixture = _load_fixture()
    if fixture is None:
        pytest.skip(
            "No parity fixture. Set BASIL_TIMELINE_PARITY_FIXTURE to a captured "
            "fixture JSON to gate the epoch-anchoring swap (see module docstring)."
        )

    report = timeline_parity_report(
        fixture["tokens"],
        stream_time_end=float(fixture["stream_time_end"]),
        session_origin_offset=float(fixture.get("session_origin_offset", 0.0)),
        ground_truth=fixture["ground_truth"],
    )

    # Decision criterion: the offset path must track the full re-transcription at
    # least as well as the repack heuristic (small tolerance for boundary noise)
    # before it is wired in as the live default.
    tolerance = float(fixture.get("tolerance_seconds", 0.05))
    assert report["offset"]["mean"] <= report["repack"]["mean"] + tolerance, (
        f"Offset anchoring did not match/beat repack: {report}. "
        "Keep assign_token_timeline (repack) as the live default."
    )
