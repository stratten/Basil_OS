"""
File Candidate Ranking

Pure ranking utilities shared by the file-find orchestrator. Given normalized
candidate dicts (from Spotlight and/or cloud find) and the caller's query, produce
a deterministic ranked ordering and decide whether a single candidate is a
confident match or whether the caller should disambiguate among several.

A "normalized candidate" is a plain dict with at least these keys:
    path (str), name (str), size (int), modified_date (float epoch seconds),
    extension (str, lowercased, includes the dot), file_type (str)

These functions have no I/O and no dependencies on the service layer so they can
be unit-tested in isolation.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

# Google Drive/Docs "pointer" stubs are tiny JSON files that only reference a
# cloud document; they are almost never what the user wants prepared inline.
POINTER_STUB_EXTENSIONS = {
    ".gdoc", ".gsheet", ".gslides", ".gdraw", ".gform", ".gmap", ".gsite", ".glink",
}
POINTER_STUB_MAX_SIZE = 512

# Real, directly-usable document types get a mild preference over unknown blobs.
PREFERRED_TYPE_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".txt", ".md", ".rtf", ".pages",
    ".pptx", ".ppt", ".key", ".xlsx", ".xls", ".csv",
}

_NAME_MATCH_WEIGHT = 100.0
_SUBSTRING_BONUS = 30.0
_PREFERRED_TYPE_BONUS = 10.0
_POINTER_STUB_PENALTY = 60.0

# Minimum lead (in score points) the top candidate must have over the runner-up
# to be treated as a confident, auto-preparable match.
DEFAULT_DOMINANCE_MARGIN = 25.0


def _tokenize(text: str) -> set[str]:
    """Lowercase alphanumeric tokens, with the trailing extension stripped."""
    stem, _ = os.path.splitext(text or "")
    return {token for token in re.split(r"[^a-z0-9]+", stem.lower()) if token}


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _extension_of(candidate: Dict[str, Any]) -> str:
    ext = str(candidate.get("extension") or "").lower()
    if ext:
        return ext
    name = candidate.get("name") or os.path.basename(str(candidate.get("path") or ""))
    return os.path.splitext(name)[1].lower()


def score_candidate(candidate: Dict[str, Any], query: str) -> float:
    """Deterministic relevance score for a single candidate against the query."""
    name = str(candidate.get("name") or os.path.basename(str(candidate.get("path") or "")))
    extension = _extension_of(candidate)
    try:
        size = int(candidate.get("size") or 0)
    except (TypeError, ValueError):
        size = 0

    query_tokens = _tokenize(query)
    name_tokens = _tokenize(name)

    score = 0.0
    if query_tokens:
        overlap = len(query_tokens & name_tokens) / len(query_tokens)
        score += overlap * _NAME_MATCH_WEIGHT

    query_compact = _compact(os.path.splitext(query or "")[0])
    if query_compact and query_compact in _compact(name):
        score += _SUBSTRING_BONUS

    if extension in PREFERRED_TYPE_EXTENSIONS:
        score += _PREFERRED_TYPE_BONUS

    if extension in POINTER_STUB_EXTENSIONS or (0 < size < POINTER_STUB_MAX_SIZE):
        score -= _POINTER_STUB_PENALTY

    return score


def rank_candidates(candidates: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """Return a new list of candidates with a `score` key, best first.

    Ties on score are broken by most-recent modification, so recency only ever
    matters between otherwise equally-relevant files.
    """
    scored: List[Dict[str, Any]] = []
    for candidate in candidates:
        enriched = dict(candidate)
        enriched["score"] = score_candidate(candidate, query)
        scored.append(enriched)

    def _sort_key(item: Dict[str, Any]) -> Tuple[float, float]:
        try:
            modified = float(item.get("modified_date") or 0.0)
        except (TypeError, ValueError):
            modified = 0.0
        return (item["score"], modified)

    scored.sort(key=_sort_key, reverse=True)
    return scored


def partition_candidates(
    ranked: List[Dict[str, Any]],
    dominance_margin: float = DEFAULT_DOMINANCE_MARGIN,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split a ranked list into (confident_single, all_candidates).

    `confident_single` is non-None only when there is exactly one candidate, or
    when the top candidate leads the runner-up by at least `dominance_margin` and
    has a positive score. Otherwise the caller should disambiguate.
    """
    if not ranked:
        return None, []
    if len(ranked) == 1:
        top = ranked[0]
        return (top if top.get("score", 0.0) > 0 else None), ranked

    top, runner_up = ranked[0], ranked[1]
    top_score = float(top.get("score") or 0.0)
    runner_score = float(runner_up.get("score") or 0.0)
    if top_score > 0 and (top_score - runner_score) >= dominance_margin:
        return top, ranked
    return None, ranked
