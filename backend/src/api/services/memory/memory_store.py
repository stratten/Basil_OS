"""Filesystem-backed working memory storage for Basil.

This module intentionally keeps storage schema-light: small markdown files are
the source of truth, while services above this layer decide what should be
written or promoted.
"""

from __future__ import annotations

import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from api.core.config.api_settings import settings


MEMORY_FILE_LIMITS_BYTES: Dict[str, int] = {
    "essentials.md": 2 * 1024,
    "now.md": 1 * 1024,
    "recent.md": 3 * 1024,
    "user.md": 4 * 1024,
    "buffer.md": 8 * 1024,
}

BOOTSTRAP_MEMORY_FILES = tuple(MEMORY_FILE_LIMITS_BYTES.keys())


class MemoryStoreError(Exception):
    """Base exception for working memory storage failures."""


class MemoryFileNotFoundError(MemoryStoreError):
    """Raised when callers request an unknown managed memory file."""


class MemoryFileBackpressureError(MemoryStoreError):
    """Raised when a write would exceed a managed file's hard cap."""

    def __init__(self, file_name: str, cap_bytes: int, attempted_bytes: int) -> None:
        super().__init__(
            f"{file_name} would exceed its {cap_bytes} byte cap "
            f"({attempted_bytes} bytes attempted)."
        )
        self.file_name = file_name
        self.cap_bytes = cap_bytes
        self.attempted_bytes = attempted_bytes


@dataclass(frozen=True)
class MemoryDocument:
    """A managed working-memory markdown document."""

    file_name: str
    path: Path
    content: str
    cap_bytes: Optional[int]
    size_bytes: int


@dataclass(frozen=True)
class MemorySearchResult:
    """A simple full-text search hit from managed memory files."""

    file_name: str
    path: Path
    line_number: int
    line: str


class MemoryStore:
    """Low-level file store for Basil's plain-text working memory."""

    def __init__(self, memory_dir: Optional[Path] = None) -> None:
        self.memory_dir = memory_dir or settings.STORAGE_DIR / "memory"
        self._lock = threading.RLock()
        self.bootstrap_memory_files()

    def bootstrap_memory_files(self) -> None:
        """Create the memory directory and empty managed files if missing."""
        with self._lock:
            self.memory_dir.mkdir(parents=True, exist_ok=True)
            (self.memory_dir / "user").mkdir(parents=True, exist_ok=True)
            for file_name in BOOTSTRAP_MEMORY_FILES:
                path = self.resolve_memory_file_path(file_name)
                if not path.exists():
                    self._write_file_atomic(path, "")

    def resolve_memory_file_path(self, file_name: str) -> Path:
        """Resolve a managed memory file name to an on-disk path."""
        self._validate_managed_file_name(file_name)
        return self.memory_dir / file_name

    def read_memory_file(self, file_name: str) -> MemoryDocument:
        """Read a managed memory markdown file."""
        path = self.resolve_memory_file_path(file_name)
        content = path.read_text(encoding="utf-8")
        return MemoryDocument(
            file_name=file_name,
            path=path,
            content=content,
            cap_bytes=MEMORY_FILE_LIMITS_BYTES.get(file_name),
            size_bytes=len(content.encode("utf-8")),
        )

    def list_memory_documents(self) -> List[MemoryDocument]:
        """Return all managed always-known memory documents."""
        return [self.read_memory_file(file_name) for file_name in BOOTSTRAP_MEMORY_FILES]

    def write_memory_file(self, file_name: str, content: str) -> MemoryDocument:
        """Replace a managed memory file after enforcing its byte cap."""
        path = self.resolve_memory_file_path(file_name)
        encoded_size = len(content.encode("utf-8"))
        self._raise_if_cap_exceeded(file_name, encoded_size)

        with self._lock:
            self._write_file_atomic(path, content)
            return self.read_memory_file(file_name)

    def append_to_memory_file(self, file_name: str, entry: str) -> MemoryDocument:
        """Append an entry to a managed memory file, rejecting over-cap writes."""
        path = self.resolve_memory_file_path(file_name)
        with self._lock:
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            separator = "" if existing == "" or existing.endswith("\n") else "\n"
            normalized_entry = entry if entry.endswith("\n") else f"{entry}\n"
            next_content = f"{existing}{separator}{normalized_entry}"
            encoded_size = len(next_content.encode("utf-8"))
            self._raise_if_cap_exceeded(file_name, encoded_size)
            self._write_file_atomic(path, next_content)
            return self.read_memory_file(file_name)

    def search_memory_files(
        self,
        query: str,
        *,
        max_results: int = 20,
        include_user_overflow: bool = True,
    ) -> List[MemorySearchResult]:
        """Run a lightweight case-insensitive line search over memory files."""
        normalized_query = query.strip().casefold()
        if not normalized_query:
            return []

        results: List[MemorySearchResult] = []
        for path in self._iter_searchable_paths(include_user_overflow):
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if normalized_query in line.casefold():
                    results.append(
                        MemorySearchResult(
                            file_name=str(path.relative_to(self.memory_dir)),
                            path=path,
                            line_number=line_number,
                            line=line,
                        )
                    )
                    if len(results) >= max_results:
                        return results
        return results

    def get_memory_file_cap_bytes(self, file_name: str) -> int:
        """Return the hard cap for a managed memory file."""
        self._validate_managed_file_name(file_name)
        return MEMORY_FILE_LIMITS_BYTES[file_name]

    def _iter_searchable_paths(self, include_user_overflow: bool) -> Iterable[Path]:
        for file_name in BOOTSTRAP_MEMORY_FILES:
            yield self.resolve_memory_file_path(file_name)

        if include_user_overflow:
            user_dir = self.memory_dir / "user"
            if user_dir.exists():
                yield from sorted(user_dir.glob("*.md"))

    def _validate_managed_file_name(self, file_name: str) -> None:
        if file_name not in MEMORY_FILE_LIMITS_BYTES:
            raise MemoryFileNotFoundError(f"Unknown managed memory file: {file_name}")

    def _raise_if_cap_exceeded(self, file_name: str, attempted_bytes: int) -> None:
        cap_bytes = self.get_memory_file_cap_bytes(file_name)
        if attempted_bytes > cap_bytes:
            raise MemoryFileBackpressureError(file_name, cap_bytes, attempted_bytes)

    def _write_file_atomic(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_path = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, path)
        finally:
            temporary = Path(temporary_path)
            if temporary.exists():
                temporary.unlink()


_memory_store_singleton: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    """Return the process-wide working-memory store."""
    global _memory_store_singleton
    if _memory_store_singleton is None:
        _memory_store_singleton = MemoryStore()
    return _memory_store_singleton
