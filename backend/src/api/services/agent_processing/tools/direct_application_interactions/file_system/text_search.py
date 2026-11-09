"""Read-only text search, folder listing, and line-range reading for agent file-service tools.

These exist so that "find the documents that mention X" and "read this file" do not need a shell command. A shell pipeline can be classified as read-only only when every part of it is understood, while these tools only ever read, so they need no approval prompt. Every call is bounded in files visited, bytes read, results returned, and time spent, and says so when a bound cut the answer short.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

from api.core.security.protected_runtime_paths import (
    PROTECTED_RUNTIME_REFUSAL,
    is_protected_runtime_path,
    log_protected_runtime_refusal,
)

logger = logging.getLogger(__name__)

# Folders full of generated or downloaded files. They are skipped unless the caller asks for them, and the result names every one that was skipped.
GENERATED_DIRECTORY_NAMES = frozenset(
    {
        "node_modules", ".git", ".venv", "venv", "__pycache__", ".next", ".cache",
        "DerivedData", "Pods", ".build", "dist", "build",
    }
)
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES_VISITED = 20_000
DEFAULT_MAX_MATCHES = 100
MAX_MATCHES_LIMIT = 500
DEFAULT_MAX_LISTED = 200
MAX_LISTED_LIMIT = 1000
DEFAULT_MAX_READ_LINES = 400
MAX_READ_LINES_LIMIT = 1000
MAX_LINE_CHARS = 300
MAX_READ_CHARS = 60_000
MAX_TERMS = 20
MAX_TERM_CHARS = 200
MAX_GLOBS = 20
BINARY_SNIFF_BYTES = 8192
TIME_BUDGET_SECONDS = 20.0


def _failure(path: str, error_type: str, error: str, **extra: Any) -> Dict[str, Any]:
    return {"success": False, "path": path, "error_type": error_type, "error": error, **extra}


def _resolve_path(raw: Any, *, must_be: str, surface: str) -> tuple[Optional[Path], Optional[Dict[str, Any]]]:
    """Turn the caller's text into an absolute path, or say why it cannot be used."""
    if not isinstance(raw, str) or not raw.strip():
        return None, _failure(str(raw), "invalid_path", "path must be a non-empty absolute path.")
    path = Path(os.path.expanduser(raw.strip()))
    if not path.is_absolute():
        return None, _failure(raw, "invalid_path", "path must be absolute, or start with ~/.")
    if is_protected_runtime_path(path):
        log_protected_runtime_refusal(surface)
        return None, _failure(raw, "policy_blocked", PROTECTED_RUNTIME_REFUSAL)
    if must_be == "directory" and not path.is_dir():
        kind = "not_a_directory" if path.exists() else "not_found"
        return None, _failure(raw, kind, f"{raw} is not an existing folder." if kind == "not_found" else f"{raw} is a file, not a folder.")
    if must_be == "file" and not path.is_file():
        kind = "not_a_file" if path.exists() else "not_found"
        return None, _failure(raw, kind, f"{raw} is not an existing file." if kind == "not_found" else f"{raw} is not a regular file.")
    return path, None


def _clean_strings(values: Any, *, limit: int, max_chars: int, label: str) -> tuple[List[str], Optional[str]]:
    if values is None:
        return [], None
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)) or not all(isinstance(value, str) for value in values):
        return [], f"{label} must be a list of strings."
    cleaned = [value for value in values if value.strip()]
    if len(cleaned) > limit:
        return [], f"{label} accepts at most {limit} entries."
    if any(len(value) > max_chars for value in cleaned):
        return [], f"Each entry in {label} must be at most {max_chars} characters."
    return cleaned, None


def _clamp(value: Any, *, default: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(1, min(value, maximum))


def _walk_files(root: Path, include_generated: bool, stats: Dict[str, Any]) -> Iterator[str]:
    """Yield regular files under the root in a stable order, never following symbolic links and never entering a protected path."""
    for current, directories, names in os.walk(root, followlinks=False):
        kept = []
        for directory in sorted(directories):
            if not include_generated and directory in GENERATED_DIRECTORY_NAMES:
                stats["generated_directories_skipped"].add(directory)
                continue
            if is_protected_runtime_path(os.path.join(current, directory)):
                continue
            kept.append(directory)
        directories[:] = kept
        for name in sorted(names):
            full = os.path.join(current, name)
            if os.path.islink(full):
                stats["symlinks_skipped"] += 1
                continue
            yield full


def _name_matches(name: str, globs: Sequence[str]) -> bool:
    if not globs:
        return True
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, pattern.lower()) for pattern in globs)


def _new_stats() -> Dict[str, Any]:
    return {"generated_directories_skipped": set(), "symlinks_skipped": 0, "binary_skipped": 0, "too_large_skipped": 0, "unreadable_skipped": 0}


def _summarize_stats(stats: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "generated_directories_skipped": sorted(stats["generated_directories_skipped"]),
        "symlinks_skipped": stats["symlinks_skipped"],
        "binary_files_skipped": stats["binary_skipped"],
        "files_over_2_mib_skipped": stats["too_large_skipped"],
        "unreadable_files_skipped": stats["unreadable_skipped"],
    }


def _read_bytes(full: str, stats: Dict[str, Any]) -> Optional[bytes]:
    """The file's bytes when it is a readable text file within the size bound, otherwise None and a count of why."""
    try:
        if os.path.getsize(full) > MAX_FILE_BYTES:
            stats["too_large_skipped"] += 1
            return None
        with open(full, "rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
    except OSError:
        stats["unreadable_skipped"] += 1
        return None
    if b"\0" in data[:BINARY_SNIFF_BYTES]:
        stats["binary_skipped"] += 1
        return None
    return data


def search_text_in_files(
    directory: Any,
    terms: Any,
    file_globs: Any = None,
    case_sensitive: Optional[bool] = False,
    max_matches: Any = None,
    include_generated_directories: Optional[bool] = False,
) -> Dict[str, Any]:
    """Find the lines under a folder that contain any of the given words or phrases (plain text, not a regular expression)."""
    root, failure = _resolve_path(directory, must_be="directory", surface="text search")
    if failure:
        return failure
    cleaned_terms, error = _clean_strings(terms, limit=MAX_TERMS, max_chars=MAX_TERM_CHARS, label="terms")
    if error or not cleaned_terms:
        return _failure(str(directory), "invalid_terms", error or "terms must name at least one word or phrase to look for.")
    globs, error = _clean_strings(file_globs, limit=MAX_GLOBS, max_chars=MAX_TERM_CHARS, label="file_globs")
    if error:
        return _failure(str(directory), "invalid_file_globs", error)

    exact = bool(case_sensitive)
    needles = cleaned_terms if exact else [term.lower() for term in cleaned_terms]
    limit = _clamp(max_matches, default=DEFAULT_MAX_MATCHES, maximum=MAX_MATCHES_LIMIT)
    stats = _new_stats()
    matches: List[Dict[str, Any]] = []
    per_file: Dict[str, int] = {}
    visited = 0
    truncation_reason: Optional[str] = None
    deadline = time.monotonic() + TIME_BUDGET_SECONDS

    for full in _walk_files(root, bool(include_generated_directories), stats):
        if not _name_matches(os.path.basename(full), globs):
            continue
        if visited >= MAX_FILES_VISITED:
            truncation_reason = "file_limit"
            break
        if time.monotonic() > deadline:
            truncation_reason = "time_limit"
            break
        visited += 1
        data = _read_bytes(full, stats)
        if data is None:
            continue
        for line_number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), start=1):
            haystack = line if exact else line.lower()
            if not any(needle in haystack for needle in needles):
                continue
            matches.append({"path": full, "line_number": line_number, "line": line.strip()[:MAX_LINE_CHARS]})
            per_file[full] = per_file.get(full, 0) + 1
            if len(matches) >= limit:
                truncation_reason = "match_limit"
                break
        if truncation_reason == "match_limit":
            break

    return {
        "success": True,
        "directory": str(root),
        "terms": cleaned_terms,
        "case_sensitive": exact,
        "files_visited": visited,
        "total_matches": len(matches),
        "matches": matches,
        "files_with_matches": [{"path": path, "match_count": count} for path, count in per_file.items()],
        "truncated": truncation_reason is not None,
        "truncation_reason": truncation_reason,
        "skipped": _summarize_stats(stats),
    }


def list_files_in_folder(
    directory: Any,
    name_globs: Any = None,
    max_results: Any = None,
    include_generated_directories: Optional[bool] = False,
) -> Dict[str, Any]:
    """List the files under a folder, optionally only those whose names match patterns such as ``*.md``."""
    root, failure = _resolve_path(directory, must_be="directory", surface="folder listing")
    if failure:
        return failure
    globs, error = _clean_strings(name_globs, limit=MAX_GLOBS, max_chars=MAX_TERM_CHARS, label="name_globs")
    if error:
        return _failure(str(directory), "invalid_name_globs", error)

    limit = _clamp(max_results, default=DEFAULT_MAX_LISTED, maximum=MAX_LISTED_LIMIT)
    stats = _new_stats()
    files: List[Dict[str, Any]] = []
    visited = 0
    truncation_reason: Optional[str] = None
    deadline = time.monotonic() + TIME_BUDGET_SECONDS

    for full in _walk_files(root, bool(include_generated_directories), stats):
        if visited >= MAX_FILES_VISITED:
            truncation_reason = "file_limit"
            break
        if time.monotonic() > deadline:
            truncation_reason = "time_limit"
            break
        visited += 1
        if not _name_matches(os.path.basename(full), globs):
            continue
        try:
            info = os.stat(full)
        except OSError:
            stats["unreadable_skipped"] += 1
            continue
        files.append(
            {
                "path": full,
                "size_bytes": info.st_size,
                "modified": datetime.fromtimestamp(info.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
        if len(files) >= limit:
            truncation_reason = "result_limit"
            break

    return {
        "success": True,
        "directory": str(root),
        "files_visited": visited,
        "total_listed": len(files),
        "files": files,
        "truncated": truncation_reason is not None,
        "truncation_reason": truncation_reason,
        "skipped": _summarize_stats(stats),
    }


def read_text_file(path: Any, start_line: Any = None, max_lines: Any = None) -> Dict[str, Any]:
    """Read a range of lines from one UTF-8 text file, with the file's SHA-256 for use as ``expected_sha256`` in a later edit."""
    target, failure = _resolve_path(path, must_be="file", surface="text file read")
    if failure:
        return failure
    stats = _new_stats()
    data = _read_bytes(str(target), stats)
    if data is None:
        if stats["too_large_skipped"]:
            return _failure(str(path), "too_large", "The file is over 2 MiB. Search it with search_text_in_files, or use the shell to read part of it.")
        if stats["binary_skipped"]:
            return _failure(str(path), "binary_file", "The file is binary, not text.")
        return _failure(str(path), "unreadable", "The file could not be read.")

    lines = data.decode("utf-8", errors="replace").splitlines()
    total = len(lines)
    # A start line past the end is honored and returns an empty range, so the caller learns the file is shorter instead of being handed its last line.
    first = start_line if isinstance(start_line, int) and not isinstance(start_line, bool) and start_line >= 1 else 1
    wanted = _clamp(max_lines, default=DEFAULT_MAX_READ_LINES, maximum=MAX_READ_LINES_LIMIT)
    selected: List[str] = []
    used = 0
    for line in lines[first - 1 : first - 1 + wanted]:
        clipped = line if len(line) <= MAX_READ_CHARS else line[:MAX_READ_CHARS]
        if selected and used + len(clipped) + 1 > MAX_READ_CHARS:
            break
        selected.append(clipped)
        used += len(clipped) + 1
    last = first + len(selected) - 1 if selected else first - 1
    return {
        "success": True,
        "path": str(target),
        "total_lines": total,
        "start_line": first,
        "end_line": last,
        "text": "\n".join(selected),
        "truncated": bool(selected) and last < total,
        "next_start_line": last + 1 if selected and last < total else None,
        "sha256": sha256(data).hexdigest(),
    }
