"""Deterministic query derivation and the prefetch pack cache."""

from __future__ import annotations

import re
from collections import Counter, OrderedDict
from typing import List, Optional, Sequence, Tuple

from .context_pack import ContextPack
from .similarity import BACKCHANNEL, STOPWORDS, jaccard, tokens
from .symbol_vocabulary import SymbolVocabulary, normalize_key

MAX_QUERIES = 4
_IDENTIFIER = re.compile(
    r"\b(?:[A-Za-z]+_[A-Za-z0-9_]+"
    r"|[a-z]+[A-Z][A-Za-z0-9]*"
    r"|[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*"
    r"|[\w\-]+\.(?:py|js|ts|tsx|jsx|swift|kt|java|go|rs|rb|cpp|md|json|ya?ml|toml|sql|html|css|sh)\b)"
)


def derive_queries(
    text: str,
    vocabulary: Optional[SymbolVocabulary] = None,
    *,
    max_queries: int = MAX_QUERIES,
) -> List[str]:
    """Search queries for the recent transcript text; empty when nothing searchable was said."""
    queries: List[str] = []
    seen: set = set()

    def add(query: str) -> None:
        key = normalize_key(query)
        if len(key) < 4 or key in seen or len(queries) >= max_queries:
            return
        seen.add(key)
        queries.append(query)

    for match in _IDENTIFIER.finditer(text):
        add(match.group(0))
    words = tokens(text)
    if vocabulary is not None and len(vocabulary) > 0:
        for name in vocabulary.match_words(words):
            add(name)
    if not queries:
        counts = Counter(
            word for word in words if len(word) >= 5 and word not in STOPWORDS and word not in BACKCHANNEL
        )
        ranked = sorted(counts.items(), key=lambda pair: (-pair[1], -len(pair[0]), pair[0]))
        for word, _count in ranked[:2]:
            add(word)
    return queries


def queries_fingerprint(queries: Sequence[str]) -> Tuple[str, ...]:
    return tuple(sorted({normalize_key(query) for query in queries if normalize_key(query)}))


class PrefetchCache:
    """Small TTL + LRU cache of context packs keyed by their query fingerprint."""

    def __init__(self, *, max_entries: int = 16, ttl_seconds: float = 120.0, min_overlap: float = 0.5) -> None:
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._min_overlap = min_overlap
        self._entries: "OrderedDict[Tuple[str, ...], Tuple[float, ContextPack]]" = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()

    def put(self, queries: Sequence[str], pack: ContextPack, now: float) -> None:
        key = queries_fingerprint(queries)
        if not key:
            return
        self._entries[key] = (now, pack)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def get(self, queries: Sequence[str], now: float) -> Optional[ContextPack]:
        self._expire(now)
        key = queries_fingerprint(queries)
        entry = self._entries.get(key)
        if entry is None:
            return None
        self._entries.move_to_end(key)
        return entry[1]

    def find(self, queries: Sequence[str], now: float) -> Optional[ContextPack]:
        """Exact entry, else the freshest entry whose key set overlaps enough with ``queries``."""
        exact = self.get(queries, now)
        if exact is not None:
            return exact
        wanted = set(queries_fingerprint(queries))
        best_key: Optional[Tuple[str, ...]] = None
        best_score = 0.0
        for key in reversed(self._entries):
            score = jaccard(wanted, set(key))
            if score >= self._min_overlap and score > best_score:
                best_key, best_score = key, score
        if best_key is None:
            return None
        self._entries.move_to_end(best_key)
        return self._entries[best_key][1]

    def _expire(self, now: float) -> None:
        stale = [key for key, (created, _pack) in self._entries.items() if now - created > self._ttl_seconds]
        for key in stale:
            del self._entries[key]
