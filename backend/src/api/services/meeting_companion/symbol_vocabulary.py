"""Maps spoken word sequences back to real symbol and file names in the attached roots."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .context_search import FileEntry, read_entry_text

SOURCE_EXTENSIONS = frozenset(
    {
        ".py", ".js", ".jsx", ".ts", ".tsx", ".swift", ".kt", ".java", ".go", ".rs", ".rb", ".c", ".h",
        ".cpp", ".hpp", ".cs", ".php", ".scala", ".m", ".mm",
    }
)
GENERIC_NAMES = frozenset(
    {
        "index", "main", "init", "utils", "util", "test", "tests", "config", "types", "model", "models",
        "setup", "readme", "helper", "helpers", "common", "base", "handler", "handlers", "service",
        "services", "client", "server", "routes", "route", "app", "application", "module", "default",
    }
)
_DEFINITION = re.compile(
    r"^[ \t]*(?:(?:export|public|private|protected|internal|static|final|abstract|async|pub|open|default|override)\s+)*"
    r"(?:def|class|function|func|struct|enum|protocol|interface|trait|type|fn|object|record)\s+"
    r"([A-Za-z_][A-Za-z0-9_]{3,})",
    re.MULTILINE,
)
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")


def normalize_key(name: str) -> str:
    """Lower-case alphanumeric-only key so ``RetryPolicy``, ``retry_policy`` and ``retry policy`` collide."""
    return _NON_ALNUM.sub("", name).lower()


class SymbolVocabulary:
    def __init__(self, max_names: int = 4000) -> None:
        self._max_names = max_names
        self._names: Dict[str, str] = {}

    def __len__(self) -> int:
        return len(self._names)

    @property
    def full(self) -> bool:
        return len(self._names) >= self._max_names

    def add(self, name: str) -> None:
        key = normalize_key(name)
        if len(key) < 5 or key in GENERIC_NAMES or key in self._names or self.full:
            return
        self._names[key] = name

    def match_words(self, words: Sequence[str]) -> List[str]:
        """Canonical names for runs of one to three consecutive words, longest run first, in order of appearance."""
        found: List[str] = []
        seen = set()
        index = 0
        while index < len(words):
            advanced = False
            for size in (3, 2, 1):
                if index + size > len(words):
                    continue
                key = normalize_key("".join(words[index : index + size]))
                canonical = self._names.get(key)
                if canonical is None:
                    continue
                if canonical not in seen:
                    seen.add(canonical)
                    found.append(canonical)
                index += size
                advanced = True
                break
            if not advanced:
                index += 1
        return found


def build_symbol_vocabulary(
    entries: Iterable[Tuple[str, FileEntry]],
    *,
    max_files: int = 600,
    max_bytes_per_file: int = 64_000,
    max_names: int = 4000,
    time_budget_seconds: float = 3.0,
    clock: Callable[[], float] = time.monotonic,
) -> SymbolVocabulary:
    """File stems for every entry, then definition names from the most recently modified source files."""
    vocabulary = SymbolVocabulary(max_names)
    started = clock()
    source_entries: List[FileEntry] = []
    for _root_id, entry in entries:
        relative = Path(entry.rel)
        vocabulary.add(relative.stem)
        if relative.suffix.lower() in SOURCE_EXTENSIONS:
            source_entries.append(entry)
    source_entries.sort(key=lambda candidate: -candidate.mtime)
    for entry in source_entries[:max_files]:
        if vocabulary.full or clock() - started > time_budget_seconds:
            break
        text = read_entry_text(entry, max_bytes_per_file)
        if text is None:
            continue
        for match in _DEFINITION.finditer(text):
            vocabulary.add(match.group(1))
    return vocabulary
