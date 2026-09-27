"""File result extraction for agent task finalization."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple
from urllib.parse import unquote, urlparse


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and len(value.strip()) > 0


def _basename(path: str) -> str:
    """Extract basename from POSIX or HFS-style path without importing pathlib.
    - POSIX: split on '/'
    - HFS  : split on ':'
    Returns last non-empty segment; if none, returns original path.
    """
    if not _is_non_empty_string(path):
        return path
    if ":" in path:
        parts = [seg for seg in path.split(":") if seg]
        return parts[-1] if parts else path
    parts = [seg for seg in path.split("/") if seg]
    return parts[-1] if parts else path


def _normalize_path_generic(path: str) -> str:
    """Normalize arbitrary path inputs to a resolvable form without special-casing locations.

    Behavior:
    - Preserve HFS paths (":"-separated) as-is so frontends that support HFS can convert reliably
    - Convert file:// URLs to POSIX paths
    - Expand environment variables and '~' for POSIX-like inputs
    - Normalize POSIX path (remove redundant segments) but do not force an absolute root if unknown
    """
    if not _is_non_empty_string(path):
        return path

    s = path.strip()

    # Keep HFS style untouched (e.g., 'Macintosh HD:Users:...:Desktop:sample.txt')
    if ":" in s and "/" not in s and not s.lower().startswith("file:"):
        return s

    # file:// URL -> POSIX
    if s.lower().startswith("file://"):
        parsed = urlparse(s)
        return unquote(parsed.path or "") or s

    # POSIX-like: expand env vars and user, then normalize
    expanded = os.path.expandvars(os.path.expanduser(s))
    try:
        normalized = os.path.normpath(expanded)
    except Exception:
        normalized = expanded
    return normalized


def extract_files_from_steps(steps: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Collect file impacts from structured step results only.
    Accept keys:
      - file_path, path, output_path (full path)
      - file_name (basename)
      - operation (create|modify|delete or free text)
    Never read free-form script bodies or reprs.
    """
    files: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()  # (name, full_path)

    for step in steps or []:
        result = step.get("result") if isinstance(step, dict) else None
        if not isinstance(result, dict):
            result = {}
        result_payload = result.get("result") if isinstance(result.get("result"), dict) else result

        declared_artifacts = result_payload.get("file_artifacts")
        if isinstance(declared_artifacts, list):
            for artifact in declared_artifacts:
                if not isinstance(artifact, dict):
                    continue
                full_path = artifact.get("full_path") or artifact.get("path")
                name = artifact.get("name") or (_basename(full_path) if _is_non_empty_string(full_path) else "")
                operation = artifact.get("operation")
                if not (_is_non_empty_string(name) and _is_non_empty_string(full_path) and _is_non_empty_string(operation)):
                    continue
                entry = {
                    "name": name.strip(),
                    "full_path": _normalize_path_generic(full_path),
                    "operation": operation.strip().lower(),
                }
                if _is_non_empty_string(artifact.get("source_path")):
                    entry["source_path"] = _normalize_path_generic(artifact["source_path"])
                if _is_non_empty_string(artifact.get("kind")):
                    entry["kind"] = artifact["kind"].strip().lower()
                key = (entry["name"], entry["full_path"])
                if key not in seen:
                    files.append(entry)
                    seen.add(key)
            if declared_artifacts:
                continue

        # Prefer any path-like field the service returned
        full_path = None
        for key in ("file_path", "path", "output_path"):
            value = result.get(key)
            if _is_non_empty_string(value):
                full_path = _normalize_path_generic(value)
                break

        # Derive filename
        name = None
        if _is_non_empty_string(result.get("file_name")):
            name = result["file_name"].strip()
        elif _is_non_empty_string(full_path):
            name = _basename(full_path)

        # Operation hint (optional)
        operation = result.get("operation")
        if _is_non_empty_string(operation):
            operation = operation.strip().lower()

        # FALLBACK: mine ExecutionResult.parameters_used (and context_data) for file path and action
        if full_path is None:
            params = step.get("parameters_used") if isinstance(step, dict) else None
            if isinstance(params, dict):
                context_data = params.get("context_data")
                if not isinstance(context_data, dict):
                    context_data = {}
                # Try context_data first
                for key in ("file_path", "path", "output_path"):
                    value = context_data.get(key)
                    if _is_non_empty_string(value):
                        full_path = _normalize_path_generic(value)
                        break
                # Then top-level params
                if full_path is None:
                    for key in ("file_path", "path", "output_path"):
                        value = params.get(key)
                        if _is_non_empty_string(value):
                            full_path = _normalize_path_generic(value)
                            break
                # If operation was not set, infer from action/operation keys
                if not _is_non_empty_string(operation):
                    op_candidate = context_data.get("action") or params.get("action") or params.get("operation")
                    if _is_non_empty_string(op_candidate):
                        operation = op_candidate.strip().lower()

        # If we discovered a path but still lack a name, derive it
        if name is None and _is_non_empty_string(full_path):
            name = _basename(full_path)

        if name and full_path:
            key = (name, full_path)
            if key not in seen:
                files.append({
                    "name": name,
                    "full_path": full_path,
                    "operation": operation or "",
                })
                seen.add(key)

    return files
