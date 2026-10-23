"""Query matching for attached-file search.

A query counts when its words appear together as a phrase, and a multi-word query also counts when one window of lines holds enough of its separate words. Phrase-only matching made a long natural-language question match nothing in real code, so the search fell back to the first lines of any file whose path happened to contain a query word.
"""

from __future__ import annotations

import math
import re
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from .similarity import STOPWORDS

MIN_WORD_LENGTH = 3
MAX_REQUIRED_WORDS = 3
PHRASE_WEIGHT = 2.0

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_QUERY_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*|[0-9]{3,}")


def query_words(query: str) -> List[str]:
    """Lower-cased words of a query with camelCase split and stopwords removed."""
    spaced = _CAMEL_BOUNDARY.sub(" ", query)
    return [word.lower() for word in _QUERY_WORD.findall(spaced) if word.lower() not in STOPWORDS]


def significant_words(query: str) -> List[str]:
    """The distinct query words long enough to mean something on their own, in first-seen order."""
    seen: Dict[str, None] = {}
    for word in query_words(query):
        if len(word) >= MIN_WORD_LENGTH:
            seen.setdefault(word, None)
    return list(seen)


def pattern_for_query(query: str) -> Optional[str]:
    """Regex that finds all of the query's words next to each other, or ``None`` when the query is too short to search."""
    words = query_words(query)
    if not words or len("".join(words)) < 4:
        return None
    return "[_\\-\\s.|]{0,3}".join(re.escape(word) for word in words)


class QueryMatcher:
    """One combined regex for a set of queries plus the rule that decides whether a window of matched lines counts."""

    def __init__(self, queries: Sequence[str]) -> None:
        self._phrase_groups: Set[str] = set()
        self._query_words: Dict[int, FrozenSet[str]] = {}
        self._required: Dict[int, int] = {}
        word_groups: Dict[str, str] = {}
        parts: List[str] = []
        for index, query in enumerate(queries):
            pattern = pattern_for_query(query)
            if not pattern:
                continue
            group = f"q{index}"
            self._phrase_groups.add(group)
            parts.append(f"(?P<{group}>{pattern})")
            words = significant_words(query)
            if len(words) < 2:
                continue
            self._query_words[index] = frozenset(words)
            self._required[index] = min(MAX_REQUIRED_WORDS, max(2, math.ceil(len(words) / 3)))
            for word in words:
                word_groups.setdefault(word, f"w{len(word_groups)}")
        self._word_for_group: Dict[str, str] = {group: word for word, group in word_groups.items()}
        parts.extend(f"(?P<{group}>{re.escape(word)})" for word, group in word_groups.items())
        self.regex: Optional["re.Pattern[str]"] = re.compile("|".join(parts), re.IGNORECASE) if parts else None

    @property
    def is_empty(self) -> bool:
        return self.regex is None

    def evaluate(self, groups: Set[str]) -> float:
        """Score for a window whose matches are ``groups``; zero when the window does not count as a match."""
        phrases = sum(1 for group in groups if group in self._phrase_groups)
        words = {self._word_for_group[group] for group in groups if group in self._word_for_group}
        best = 0
        for index, query_set in self._query_words.items():
            matched = len(query_set & words)
            if matched >= self._required[index]:
                best = max(best, matched)
        if phrases == 0 and best == 0:
            return 0.0
        return PHRASE_WEIGHT * phrases + best


def rank_windows(
    line_groups: Dict[int, Set[str]],
    line_count: int,
    matcher: QueryMatcher,
    *,
    context_lines: int,
    max_windows: int,
) -> List[Tuple[float, int, int]]:
    """The best non-overlapping ``(score, first_line, last_line)`` windows, zero-based, for matches keyed by line index."""
    scored: List[Tuple[float, int, int, int]] = []
    for line_index in line_groups:
        first = max(0, line_index - context_lines)
        last = min(line_count - 1, line_index + context_lines)
        window_groups: Set[str] = set()
        for neighbor in range(first, last + 1):
            window_groups |= line_groups.get(neighbor, set())
        value = matcher.evaluate(window_groups)
        if value > 0:
            scored.append((value, line_index, first, last))
    scored.sort(key=lambda window: (-window[0], window[1]))
    chosen: List[Tuple[float, int, int]] = []
    taken: List[int] = []
    for value, line_index, first, last in scored:
        if any(abs(line_index - other) <= 2 * context_lines for other in taken):
            continue
        taken.append(line_index)
        chosen.append((value, first, last))
        if len(chosen) >= max_windows:
            break
    return chosen
