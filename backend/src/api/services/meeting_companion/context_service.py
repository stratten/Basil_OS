"""The single retrieval API used by the Companion session, chat and watches."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Literal, Optional, Sequence, Tuple

from .context_pack import ContextPack
from .context_search import ContextSearchService
from .prefetch import PrefetchCache, derive_queries, queries_fingerprint
from .symbol_vocabulary import SymbolVocabulary, build_symbol_vocabulary

logger = logging.getLogger(__name__)


@dataclass
class ContextLookup:
    pack: ContextPack
    cache: Literal["hit", "miss"]
    queries: List[str]


class ContextService:
    def __init__(
        self,
        search: Optional[ContextSearchService] = None,
        cache: Optional[PrefetchCache] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._search = search or ContextSearchService()
        self._cache = cache or PrefetchCache()
        self._clock = clock
        self._vocabulary = SymbolVocabulary()
        self._last_prefetch_fingerprint: Optional[Tuple[str, ...]] = None

    def has_roots(self) -> bool:
        return self._search.has_roots()

    def attach_root(self, root_id: str, resolved_path: Path, kind: str, display_name: str) -> None:
        self._search.add_root(root_id, resolved_path, kind, display_name)
        self._reset()

    def detach_root(self, root_id: str) -> None:
        self._search.remove_root(root_id)
        self._reset()

    def _reset(self) -> None:
        self._cache.clear()
        self._last_prefetch_fingerprint = None
        if not self._search.has_roots():
            self._vocabulary = SymbolVocabulary()

    async def rebuild_vocabulary(self) -> int:
        """Rebuild the symbol vocabulary from the attached roots; returns the number of names."""
        if not self._search.has_roots():
            self._vocabulary = SymbolVocabulary()
            return 0
        try:
            vocabulary = await asyncio.to_thread(lambda: build_symbol_vocabulary(self._search.manifest_entries()))
        except Exception as error:
            logger.warning("Companion vocabulary build failed: %s", error, exc_info=True)
            return len(self._vocabulary)
        self._vocabulary = vocabulary
        return len(vocabulary)

    def derive(self, text: str) -> List[str]:
        return derive_queries(text, self._vocabulary)

    async def prefetch(self, recent_text: str) -> Optional[ContextLookup]:
        """Search ahead for the topic in ``recent_text``; ``None`` when there is nothing new to fetch."""
        if not self._search.has_roots():
            return None
        queries = self.derive(recent_text)
        if not queries:
            return None
        fingerprint = queries_fingerprint(queries)
        if fingerprint == self._last_prefetch_fingerprint:
            return None
        self._last_prefetch_fingerprint = fingerprint
        return await self._fetch(queries)

    async def lookup(self, text: str, *, extra_queries: Sequence[str] = ()) -> Optional[ContextLookup]:
        """Context for an answer, chat turn or watch; a cache hit when prefetch already covered the topic."""
        if not self._search.has_roots():
            return None
        queries: List[str] = []
        for query in list(extra_queries) + self.derive(text):
            if query not in queries:
                queries.append(query)
        queries = queries[:4]
        if not queries:
            return None
        return await self._fetch(queries)

    async def _fetch(self, queries: List[str]) -> Optional[ContextLookup]:
        now = self._clock()
        cached = self._cache.find(queries, now)
        if cached is not None:
            return ContextLookup(pack=cached, cache="hit", queries=queries)
        try:
            pack = await asyncio.to_thread(self._search.search, queries)
        except Exception as error:
            logger.warning("Companion search failed: %s", error, exc_info=True)
            return None
        self._cache.put(queries, pack, self._clock())
        return ContextLookup(pack=pack, cache="miss", queries=queries)
