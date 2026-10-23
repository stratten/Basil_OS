"""Memory-only cache of extracted document text, keyed by path, size and modification time."""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Sequence, Tuple

from .models import FINAL_STATUSES, DocumentReadLimits, DocumentText
from .reader import read_document_text

CacheKey = Tuple[str, int, float]


class DocumentTextCache:
    def __init__(self, max_entries: int = 200, max_chars: int = 6_000_000) -> None:
        self._max_entries = max_entries
        self._max_chars = max_chars
        self._lock = threading.Lock()
        self._entries: "OrderedDict[CacheKey, DocumentText]" = OrderedDict()
        self._chars = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def chars(self) -> int:
        with self._lock:
            return self._chars

    @staticmethod
    def key_for(path: Path, size: int, mtime: float) -> CacheKey:
        return (str(path), size, mtime)

    def get(self, key: CacheKey) -> Optional[DocumentText]:
        with self._lock:
            result = self._entries.get(key)
            if result is not None:
                self._entries.move_to_end(key)
            return result

    def put(self, key: CacheKey, result: DocumentText) -> None:
        """Remember ``result`` when its status describes the file itself; partial or deadline reads are not stored."""
        if result.status not in FINAL_STATUSES:
            return
        with self._lock:
            previous = self._entries.pop(key, None)
            if previous is not None:
                self._chars -= len(previous.text)
            self._entries[key] = result
            self._chars += len(result.text)
            while self._entries and (len(self._entries) > self._max_entries or self._chars > self._max_chars):
                _evicted_key, evicted = self._entries.popitem(last=False)
                self._chars -= len(evicted.text)

    def retain_under(self, roots: Sequence[Path]) -> int:
        """Drop every entry whose path is not inside one of ``roots``; returns how many were removed."""
        prefixes = [str(root) for root in roots]
        removed = 0
        with self._lock:
            for key in list(self._entries):
                path = key[0]
                if any(path == prefix or path.startswith(prefix + os.sep) for prefix in prefixes):
                    continue
                self._chars -= len(self._entries.pop(key).text)
                removed += 1
        return removed

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._chars = 0

    def read(
        self,
        path: Path,
        size: int,
        mtime: float,
        limits: DocumentReadLimits,
        *,
        deadline_seconds: Optional[float] = None,
        cold_ok: bool = True,
    ) -> Optional[DocumentText]:
        """Cached text, or a fresh read when ``cold_ok``; ``None`` when nothing is cached and reading is not allowed."""
        key = self.key_for(path, size, mtime)
        cached = self.get(key)
        if cached is not None:
            return cached
        if not cold_ok:
            return None
        result = read_document_text(path, limits, deadline_seconds=deadline_seconds)
        self.put(key, result)
        return result
