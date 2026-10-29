"""Deterministic overlap detection for skill candidates and saved skills.

This module is a *backstop detector only*. It ranks existing skill material
against a task so the evaluator can be shown the most relevant bodies, and it
flags when a freshly proposed candidate strongly overlaps an existing pending
candidate. It never merges or rewrites content; merging is always performed by
the reasoning model. All functions are pure and depend only on the standard
library so they can be unit tested without a model or filesystem.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Set, Tuple


# Number of existing items (pending candidates + saved skills, combined) that
# receive full bodies in the evaluator context. Everything else is sent as
# metadata only to keep the prompt bounded.
BODY_INCLUSION_TOP_K = 6

# A freshly proposed candidate whose combined text similarity to an existing
# pending candidate reaches this Jaccard score is treated as a suspected
# overlap and routed to the model for a merge/confirm decision.
STRONG_OVERLAP_JACCARD = 0.45

# A freshly proposed candidate whose source-task overlap (intersection over
# union of source_task_ids) reaches this value is likewise routed to the model.
STRONG_SOURCE_TASK_IOU = 0.34

# Tokens shorter than this are ignored when comparing text.
_MIN_TOKEN_LENGTH = 2

# Small stopword set so generic glue words do not inflate similarity scores.
_STOPWORDS: Set[str] = {
    "the", "and", "for", "with", "from", "that", "this", "into", "your", "you",
    "are", "was", "were", "will", "have", "has", "had", "use", "used", "using",
    "when", "then", "than", "out", "via", "per", "all", "any", "can", "should",
    "task", "tasks", "step", "steps", "result", "results",
}

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class RankableItem:
    """An existing item that can be ranked for body inclusion.

    `key` is a candidate id or a skill slug; `text` is the searchable metadata
    text (title, when-to-use, triggers) for that item.
    """

    key: str
    text: str


def tokenize(text: str) -> Set[str]:
    """Lowercase, split on non-alphanumeric runs, drop stopwords/short tokens."""
    if not text:
        return set()
    tokens = _TOKEN_PATTERN.findall(text.casefold())
    return {
        token
        for token in tokens
        if len(token) >= _MIN_TOKEN_LENGTH and token not in _STOPWORDS
    }


def jaccard_similarity(left: Set[str], right: Set[str]) -> float:
    """Return |intersection| / |union| for two token sets (0.0 when both empty)."""
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    if intersection == 0:
        return 0.0
    union = len(left | right)
    return intersection / union if union else 0.0


def text_similarity(text_a: str, text_b: str) -> float:
    """Token-Jaccard similarity between two free-text strings."""
    return jaccard_similarity(tokenize(text_a), tokenize(text_b))


def source_task_overlap(left: Sequence[str], right: Sequence[str]) -> float:
    """Intersection-over-union of two source_task_ids collections."""
    left_set = {str(item) for item in left if item}
    right_set = {str(item) for item in right if item}
    if not left_set or not right_set:
        return 0.0
    intersection = len(left_set & right_set)
    if intersection == 0:
        return 0.0
    union = len(left_set | right_set)
    return intersection / union if union else 0.0


def select_body_keys(
    task_text: str,
    items: Iterable[RankableItem],
    *,
    top_k: int = BODY_INCLUSION_TOP_K,
) -> Set[str]:
    """Return the keys of the up-to-`top_k` items most similar to the task.

    Items with zero similarity are never selected, so an unrelated catalog
    contributes no bodies at all. Ties are broken by original ordering.
    """
    if top_k <= 0:
        return set()

    task_tokens = tokenize(task_text)
    scored: List[Tuple[float, int, str]] = []
    for index, item in enumerate(items):
        score = jaccard_similarity(task_tokens, tokenize(item.text))
        if score > 0.0:
            scored.append((score, index, item.key))

    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    return {key for _, _, key in scored[:top_k]}


def proposal_overlaps_candidate(
    *,
    proposal_text: str,
    proposal_source_task_ids: Sequence[str],
    candidate_text: str,
    candidate_source_task_ids: Sequence[str],
) -> bool:
    """Backstop predicate: does a new proposal strongly overlap a pending candidate?

    Returns True when either the combined text similarity or the source-task
    overlap crosses its threshold. This only signals "route to the model for a
    merge/confirm decision"; it does not itself merge anything.
    """
    if text_similarity(proposal_text, candidate_text) >= STRONG_OVERLAP_JACCARD:
        return True
    if source_task_overlap(proposal_source_task_ids, candidate_source_task_ids) >= STRONG_SOURCE_TASK_IOU:
        return True
    return False
