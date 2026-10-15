"""Bounded, read-only search over user-attached folders and files."""

from __future__ import annotations

import bisect
import fnmatch
import logging
import os
import re
import stat
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from api.services.document_reading import COMPANION_LIMITS, DocumentReadLimits, DocumentTextCache, is_document_path

from .context_pack import ContextExcerpt, ContextPack
from .similarity import STOPWORDS

logger = logging.getLogger(__name__)

DENY_DIRECTORY_NAMES = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
        ".mypy_cache", ".ruff_cache", ".tox", ".next", ".nuxt", "dist", "build", "out", "target", "Pods",
        "DerivedData", ".build", ".gradle", ".idea", ".vscode", ".cache", ".parcel-cache", "coverage",
        ".terraform", "vendor", "bower_components", ".ssh", ".aws", ".gnupg",
    }
)
DENY_DIRECTORY_SUFFIXES = (".app", ".framework", ".xcframework", ".xcassets", ".dSYM")
DENY_FILE_NAME_PATTERNS = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", "*.jks", "id_rsa*", "id_ed25519*",
    "id_ecdsa*", "*.sqlite", "*.sqlite3", "*.db", "credentials*", "secrets*", "*.secret", "*.secrets",
    ".netrc", ".npmrc", ".pypirc", "*.mobileprovision", "*.lock", "package-lock.json", "pnpm-lock.yaml",
    "*.min.js", "*.map", ".DS_Store",
)
DENY_EXTENSIONS = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".ico", ".icns", ".bmp", ".tiff", ".psd",
        ".mp3", ".wav", ".m4a", ".aac", ".flac", ".mp4", ".mov", ".avi", ".mkv", ".webm",
        ".zip", ".gz", ".tar", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".dmg", ".pkg", ".iso",
        ".woff", ".woff2", ".ttf", ".otf", ".eot", ".so", ".dylib", ".a", ".o", ".dll", ".exe",
        ".class", ".jar", ".pyc", ".pyo", ".bin", ".dat", ".onnx", ".gguf", ".safetensors", ".pt",
        ".doc", ".xls", ".ppt", ".key",
    }
)
SENSITIVE_HOME_SUBPATHS = (
    ".basil", ".ssh", ".aws", ".gnupg", ".config", ".kube", ".docker",
    "Library/Keychains", "Library/Cookies", "Library/Application Support", "Library/Mail",
    "Library/Messages", "Library/Safari", "Library/Containers", "Library/Group Containers",
)


class RootRejected(ValueError):
    """Raised when a path may not be attached as Companion context."""


def validate_root(path_text: str, *, home: Optional[Path] = None) -> Tuple[Path, str]:
    """Return ``(resolved_path, kind)`` for an attachable root, or raise ``RootRejected`` with a user-facing reason."""
    raw = Path(path_text).expanduser()
    if not raw.is_absolute():
        raise RootRejected("The path must be absolute.")
    try:
        resolved = raw.resolve(strict=True)
    except (OSError, RuntimeError):
        raise RootRejected("That path does not exist.")
    home_dir = (home if home is not None else Path.home()).resolve()
    if resolved == Path(resolved.anchor) or resolved == home_dir or resolved in home_dir.parents:
        raise RootRejected("Choose a specific project folder or file, not your home folder or the whole disk.")
    for relative in SENSITIVE_HOME_SUBPATHS:
        sensitive = home_dir / relative
        if resolved == sensitive or sensitive in resolved.parents or resolved in sensitive.parents:
            raise RootRejected("That location holds credentials or private app data and cannot be attached.")
    if resolved.is_dir():
        return resolved, "folder"
    if resolved.is_file():
        if _file_name_denied(resolved.name):
            raise RootRejected("That kind of file (credentials, binary or generated) cannot be attached.")
        return resolved, "file"
    raise RootRejected("Only folders and regular files can be attached.")


class GitignoreFilter:
    """Conservative subset of ``.gitignore``: plain names, globs, anchoring and directory-only rules; no negation."""

    def __init__(self, rules: List[Tuple[str, bool, bool]]) -> None:
        self._rules = rules

    @classmethod
    def from_root(cls, root: Path) -> "GitignoreFilter":
        rules: List[Tuple[str, bool, bool]] = []
        try:
            lines = (root / ".gitignore").read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return cls(rules)
        for line in lines:
            pattern = line.strip()
            if not pattern or pattern.startswith("#") or pattern.startswith("!"):
                continue
            directory_only = pattern.endswith("/")
            pattern = pattern.rstrip("/")
            anchored = pattern.startswith("/") or "/" in pattern
            pattern = pattern.lstrip("/")
            if pattern:
                rules.append((pattern, directory_only, anchored))
        return cls(rules)

    def ignores(self, relative_posix: str, *, is_dir: bool) -> bool:
        basename = relative_posix.rsplit("/", 1)[-1]
        for pattern, directory_only, anchored in self._rules:
            if directory_only and not is_dir:
                continue
            if anchored:
                if fnmatch.fnmatchcase(relative_posix, pattern):
                    return True
                if pattern.startswith("**/") and fnmatch.fnmatchcase(relative_posix, pattern[3:]):
                    return True
            elif fnmatch.fnmatchcase(basename, pattern):
                return True
        return False


@dataclass(frozen=True)
class SearchLimits:
    max_files: int = 1500
    max_file_bytes: int = 400_000
    max_total_bytes: int = 24_000_000
    time_budget_seconds: float = 2.5
    max_excerpts: int = 8
    max_excerpts_per_file: int = 3
    context_lines: int = 3
    max_excerpt_chars: int = 1200
    max_manifest_files: int = 20_000
    manifest_ttl_seconds: float = 60.0
    document_limits: DocumentReadLimits = COMPANION_LIMITS
    document_cold_seconds: float = 1.2
    max_warm_documents: int = 60
    warm_budget_seconds: float = 20.0
    warm_document_seconds: float = 8.0


@dataclass(frozen=True)
class FileEntry:
    rel: str
    path: Path
    size: int
    mtime: float


READ_FILE_MAX_BYTES = 1_000_000


@dataclass(frozen=True)
class AttachedFileText:
    """The result of reading one attached file: ``ok``, ``not_found`` (not a member of any attached root) or ``unreadable``."""

    status: str
    display_path: str = ""
    text: str = ""
    truncated: bool = False
    detail: str = ""


@dataclass
class _RootState:
    id: str
    path: Path
    kind: str
    display_name: str
    gitignore: GitignoreFilter
    manifest: List[FileEntry] = field(default_factory=list)
    manifest_built_at: Optional[float] = None


_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_QUERY_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*|[0-9]{3,}")


def query_words(query: str) -> List[str]:
    """Lower-cased words of a query with camelCase split and stopwords removed."""
    spaced = _CAMEL_BOUNDARY.sub(" ", query)
    return [word.lower() for word in _QUERY_WORD.findall(spaced) if word.lower() not in STOPWORDS]


def _pattern_for_query(query: str) -> Optional[str]:
    words = query_words(query)
    if not words or len("".join(words)) < 4:
        return None
    return "[_\\-\\s.|]{0,3}".join(re.escape(word) for word in words)


class ContextSearchService:
    def __init__(
        self,
        limits: Optional[SearchLimits] = None,
        clock: Callable[[], float] = time.monotonic,
        documents: Optional[DocumentTextCache] = None,
    ) -> None:
        self.limits = limits or SearchLimits()
        self._clock = clock
        self._lock = threading.RLock()
        self._roots: Dict[str, _RootState] = {}
        self._documents = documents if documents is not None else DocumentTextCache()
        self._generation = 0

    def add_root(self, root_id: str, resolved_path: Path, kind: str, display_name: str) -> None:
        gitignore = GitignoreFilter.from_root(resolved_path) if kind == "folder" else GitignoreFilter([])
        with self._lock:
            self._roots[root_id] = _RootState(root_id, resolved_path, kind, display_name, gitignore)

    def remove_root(self, root_id: str) -> None:
        with self._lock:
            removed = self._roots.pop(root_id, None)
            if removed is not None:
                self._generation += 1
        if removed is not None:
            self._documents.retain_under(self.root_paths())

    def has_roots(self) -> bool:
        with self._lock:
            return bool(self._roots)

    def root_paths(self) -> List[Path]:
        with self._lock:
            return [state.path for state in self._roots.values()]

    def manifest_entries(self) -> List[Tuple[str, FileEntry]]:
        """All eligible files as ``(root_id, entry)``; used to build the symbol vocabulary."""
        with self._lock:
            states = list(self._roots.values())
        now = self._clock()
        return [(state.id, entry) for state in states for entry in self._manifest(state, now)]

    def search(self, queries: Sequence[str], *, limits: Optional[SearchLimits] = None) -> ContextPack:
        """Search every attached root for ``queries`` within the limits; never raises for ordinary I/O problems."""
        active = limits or self.limits
        started = self._clock()
        generation = self._current_generation()
        pack = ContextPack(queries=list(queries))
        patterns = [(index, _pattern_for_query(query)) for index, query in enumerate(queries)]
        patterns = [(index, pattern) for index, pattern in patterns if pattern]
        with self._lock:
            states = list(self._roots.values())
        if not patterns or not states:
            pack.duration_ms = int((self._clock() - started) * 1000)
            return pack
        combined = re.compile(
            "|".join(f"(?P<q{index}>{pattern})" for index, pattern in patterns), re.IGNORECASE
        )
        path_words = sorted({word for query in queries for word in query_words(query)})
        candidates: List[Tuple[int, float, _RootState, FileEntry]] = []
        for state in states:
            for entry in self._manifest(state, started):
                candidates.append((_path_score(entry.rel.lower(), path_words), entry.mtime, state, entry))
        candidates.sort(key=lambda candidate: (-candidate[0], -candidate[1]))
        collected: List[Tuple[float, ContextExcerpt]] = []
        total_bytes = 0
        for path_score, _mtime, state, entry in candidates[: active.max_files]:
            if self._clock() - started > active.time_budget_seconds or total_bytes >= active.max_total_bytes:
                pack.budget_exhausted = True
                break
            text, counted_bytes = self._entry_text(entry, path_score, active, started)
            if text is None:
                continue
            pack.scanned_files += 1
            total_bytes += counted_bytes
            collected.extend(_excerpts_from_text(text, entry, state, path_score, combined, active))
        collected.sort(key=lambda scored: -scored[0])
        per_file: Dict[str, int] = {}
        chosen: List[ContextExcerpt] = []
        for score, excerpt in collected:
            key = f"{excerpt.root_id}:{excerpt.path}"
            if per_file.get(key, 0) >= active.max_excerpts_per_file:
                continue
            per_file[key] = per_file.get(key, 0) + 1
            chosen.append(
                ContextExcerpt(
                    id=f"c{len(chosen) + 1}",
                    root_id=excerpt.root_id,
                    path=excerpt.path,
                    line_start=excerpt.line_start,
                    line_end=excerpt.line_end,
                    text=excerpt.text,
                    score=round(score, 3),
                )
            )
            if len(chosen) >= active.max_excerpts:
                break
        pack.excerpts = chosen
        pack.duration_ms = int((self._clock() - started) * 1000)
        self._reconcile_documents(generation)
        return pack

    def _current_generation(self) -> int:
        with self._lock:
            return self._generation

    def _reconcile_documents(self, generation: int) -> None:
        """Drop cached text for sources detached while a search or warm-up was running."""
        if self._current_generation() != generation:
            self._documents.retain_under(self.root_paths())

    def _entry_text(
        self, entry: FileEntry, path_score: int, limits: SearchLimits, started: float
    ) -> Tuple[Optional[str], int]:
        """Text and the byte cost it counts against the scan budget, from disk or from the document cache."""
        if not is_document_path(entry.path):
            return read_entry_text(entry, limits.max_file_bytes), entry.size
        remaining = limits.time_budget_seconds - (self._clock() - started)
        cold_ok = path_score >= 1 and remaining > 0.2
        result = self._documents.read(
            entry.path,
            entry.size,
            entry.mtime,
            limits.document_limits,
            deadline_seconds=min(limits.document_cold_seconds, max(remaining, 0.0)),
            cold_ok=cold_ok,
        )
        if result is None or not result.usable:
            return None, 0
        return result.text, len(result.text)

    def warm_documents(self) -> int:
        """Read the newest attached documents into the cache within the warm-up budget; returns how many have text."""
        limits = self.limits
        started = self._clock()
        generation = self._current_generation()
        with self._lock:
            states = list(self._roots.values())
        entries = [entry for state in states for entry in self._manifest(state, started) if is_document_path(entry.path)]
        entries.sort(key=lambda candidate: -candidate.mtime)
        warmed = 0
        for entry in entries[: limits.max_warm_documents]:
            remaining = limits.warm_budget_seconds - (self._clock() - started)
            if remaining <= 0 or self._current_generation() != generation:
                break
            result = self._documents.read(
                entry.path,
                entry.size,
                entry.mtime,
                limits.document_limits,
                deadline_seconds=min(remaining, limits.warm_document_seconds),
                cold_ok=True,
            )
            if result is not None and result.usable:
                warmed += 1
        self._reconcile_documents(generation)
        return warmed

    def read_attached_file(self, display_path: str, *, deadline_seconds: float = 8.0) -> AttachedFileText:
        """Full text of one attached file by the path a search showed; only manifest members resolve."""
        wanted = (display_path or "").strip().replace("\\", "/").strip("/")
        if not wanted:
            return AttachedFileText(status="not_found")
        with self._lock:
            states = list(self._roots.values())
        now = self._clock()
        for state in states:
            if state.kind == "file":
                if wanted != state.display_name:
                    continue
                relative = state.path.name
            else:
                prefix = f"{state.display_name}/"
                if not wanted.startswith(prefix):
                    continue
                relative = wanted[len(prefix) :]
            entry = next((candidate for candidate in self._manifest(state, now) if candidate.rel == relative), None)
            if entry is None:
                continue
            canonical = state.display_name if state.kind == "file" else f"{state.display_name}/{entry.rel}"
            return self._read_entry(entry, canonical, deadline_seconds)
        return AttachedFileText(status="not_found")

    def _read_entry(self, entry: FileEntry, display_path: str, deadline_seconds: float) -> AttachedFileText:
        if is_document_path(entry.path):
            result = self._documents.read(
                entry.path,
                entry.size,
                entry.mtime,
                self.limits.document_limits,
                deadline_seconds=deadline_seconds,
                cold_ok=True,
            )
            if result is None or not result.usable:
                return AttachedFileText(status="unreadable", display_path=display_path, detail=result.status if result is not None else "unreadable")
            return AttachedFileText(status="ok", display_path=display_path, text=result.text, truncated=result.truncated)
        text = read_entry_text(entry, READ_FILE_MAX_BYTES)
        if text is None:
            return AttachedFileText(status="unreadable", display_path=display_path, detail="binary or larger than 1 MB")
        return AttachedFileText(status="ok", display_path=display_path, text=text)

    def _manifest(self, state: _RootState, now: float) -> List[FileEntry]:
        with self._lock:
            built_at = state.manifest_built_at
            if built_at is not None and now - built_at < self.limits.manifest_ttl_seconds:
                return state.manifest
            state.manifest = self._walk(state)
            state.manifest_built_at = now
            return state.manifest

    def _walk(self, state: _RootState) -> List[FileEntry]:
        entries: List[FileEntry] = []
        cap = self.limits.max_manifest_files
        if state.kind == "file":
            entry = _entry_for(state.path, state.path.name)
            return [entry] if entry is not None else []
        for current, directory_names, file_names in os.walk(state.path, followlinks=False):
            current_path = Path(current)
            relative_dir = current_path.relative_to(state.path).as_posix()
            relative_dir = "" if relative_dir == "." else relative_dir
            directory_names[:] = sorted(
                name
                for name in directory_names
                if _directory_allowed(state, relative_dir, name, current_path / name)
            )
            for name in sorted(file_names):
                relative = f"{relative_dir}/{name}" if relative_dir else name
                if _file_name_denied(name) or state.gitignore.ignores(relative, is_dir=False):
                    continue
                entry = _entry_for(current_path / name, relative)
                if entry is not None:
                    entries.append(entry)
                    if len(entries) >= cap:
                        return entries
        return entries


def _directory_allowed(state: _RootState, relative_dir: str, name: str, path: Path) -> bool:
    if name in DENY_DIRECTORY_NAMES or name.endswith(DENY_DIRECTORY_SUFFIXES) or path.is_symlink():
        return False
    relative = f"{relative_dir}/{name}" if relative_dir else name
    return not state.gitignore.ignores(relative, is_dir=True)


def _file_name_denied(name: str) -> bool:
    lowered = name.lower()
    if os.path.splitext(lowered)[1] in DENY_EXTENSIONS:
        return True
    return any(fnmatch.fnmatchcase(lowered, pattern.lower()) for pattern in DENY_FILE_NAME_PATTERNS)


def _entry_for(path: Path, relative: str) -> Optional[FileEntry]:
    try:
        info = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size == 0:
        return None
    return FileEntry(rel=relative, path=path, size=info.st_size, mtime=info.st_mtime)


def _path_score(relative_lower: str, words: Sequence[str]) -> int:
    basename = relative_lower.rsplit("/", 1)[-1]
    score = sum(1 for word in words if word in relative_lower)
    if any(word in basename for word in words):
        score += 1
    return score


def read_entry_text(entry: FileEntry, max_bytes: int) -> Optional[str]:
    if entry.size > max_bytes:
        return None
    try:
        descriptor = os.open(entry.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    try:
        with os.fdopen(descriptor, "rb") as handle:
            data = handle.read(max_bytes + 1)
    except OSError:
        return None
    if len(data) > max_bytes or b"\0" in data[:4096]:
        return None
    return data.decode("utf-8", errors="replace")


def _excerpts_from_text(
    text: str,
    entry: FileEntry,
    state: _RootState,
    path_score: int,
    pattern: "re.Pattern[str]",
    limits: SearchLimits,
) -> List[Tuple[float, ContextExcerpt]]:
    display_path = state.display_name if state.kind == "file" else f"{state.display_name}/{entry.rel}"
    lines = text.split("\n")
    newline_offsets = [match.start() for match in re.finditer("\n", text)]
    line_groups: Dict[int, set] = {}
    for match in pattern.finditer(text):
        line_index = bisect.bisect_right(newline_offsets, match.start())
        line_groups.setdefault(line_index, set()).add(match.lastgroup)
        if len(line_groups) >= 400:
            break

    def build(first: int, last: int, score: float) -> Tuple[float, ContextExcerpt]:
        body = "\n".join(line.rstrip("\r") for line in lines[first : last + 1])[: limits.max_excerpt_chars]
        excerpt = ContextExcerpt(
            id="",
            root_id=state.id,
            path=display_path,
            line_start=first + 1,
            line_end=last + 1,
            text=body,
            score=score,
        )
        return score, excerpt

    results: List[Tuple[float, ContextExcerpt]] = []
    if not line_groups:
        if path_score >= 1:
            results.append(build(0, min(len(lines) - 1, 14), 0.8 * path_score))
        return results
    ordered = sorted(line_groups.items(), key=lambda item: (-len(item[1]), item[0]))
    taken: List[int] = []
    for line_index, groups in ordered:
        if any(abs(line_index - other) <= 2 * limits.context_lines for other in taken):
            continue
        taken.append(line_index)
        first = max(0, line_index - limits.context_lines)
        last = min(len(lines) - 1, line_index + limits.context_lines)
        results.append(build(first, last, len(groups) * 2.0 + path_score * 1.5 + 0.2))
        if len(taken) >= limits.max_excerpts_per_file:
            break
    return results
