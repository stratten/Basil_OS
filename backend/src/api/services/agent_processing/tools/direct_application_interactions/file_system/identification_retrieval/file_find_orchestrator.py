"""
File Find Orchestrator

Coordinates the two file-search backends and decides what to hand back to the
agent:

1. Spotlight (`FileRetrievalService.search_files_by_name`, backed by `mdfind`).
2. Cloud `find` (`CloudStorageService.search_cloud_files`) which reaches places
   Spotlight does not index, notably Google Drive's `.shortcut-targets-by-id`
   ("Shared with me") subtree.

If exactly one candidate is a confident match, the file content is prepared for
the LLM (`result_kind == "prepared"`, the historical shape). If several plausible
matches exist, a ranked candidate list is returned instead (`result_kind ==
"candidates"`) so the agent can choose (or ask the user) and then fetch the chosen
file with `prepare_path`, rather than silently preparing one wrong guess.

This module owns the guts that used to live in `FileSystemService.find_file_for_llm`
so that file stays thin and under the line budget.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..file_models import ContentEncoding
from .file_candidate_ranking import partition_candidates, rank_candidates

logger = logging.getLogger(__name__)

# Best Spotlight score below which we also consult cloud find. A genuinely strong
# local hit (name match + real document type) scores >= 100; weak/pointer hits
# fall well under this, which is exactly the Google Drive "Shared with me" case.
WEAK_SPOTLIGHT_SCORE = 60.0

MAX_CANDIDATES_RETURNED = 10


def _provider_for_path(path: str) -> Optional[str]:
    """Best-effort cloud provider label from a local sync path."""
    lowered = (path or "").lower()
    if "cloudstorage/googledrive" in lowered or "google drive" in lowered or "/googledrive" in lowered:
        return "google_drive"
    if "cloudstorage/onedrive" in lowered or "onedrive" in lowered:
        return "onedrive"
    if "dropbox" in lowered:
        return "dropbox"
    if "mobile documents" in lowered or "clouddocs" in lowered or "icloud" in lowered:
        return "icloud"
    return None


def _type_from_extension(extension: str) -> str:
    ext = (extension or "").lower()
    if ext == ".pdf":
        return "pdf"
    if ext in {".doc", ".docx", ".pages", ".rtf", ".odt"}:
        return "document"
    if ext in {".xls", ".xlsx", ".numbers", ".csv", ".ods"}:
        return "spreadsheet"
    if ext in {".ppt", ".pptx", ".key", ".odp"}:
        return "presentation"
    if ext in {".txt", ".md", ".json", ".yaml", ".yml", ".log", ".csv"}:
        return "text"
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".svg"}:
        return "image"
    return "unknown"


def _normalize_metadata_candidate(meta: Any) -> Dict[str, Any]:
    """Normalize a Spotlight `FileMetadata` into a ranking candidate dict."""
    modified = meta.modified_date
    modified_ts = modified.timestamp() if hasattr(modified, "timestamp") else float(modified or 0.0)
    file_type = meta.file_type.value if hasattr(meta.file_type, "value") else str(meta.file_type)
    return {
        "path": meta.path,
        "name": meta.name,
        "size": meta.size,
        "modified_date": modified_ts,
        "extension": (meta.extension or os.path.splitext(meta.name)[1]).lower(),
        "file_type": file_type,
        "provider": _provider_for_path(meta.path),
        "is_readable": getattr(meta, "is_readable", True),
        "source": "spotlight",
    }


def _normalize_cloud_candidate(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a `CloudStorageService.search_cloud_files` dict into a candidate."""
    path = str(entry.get("path") or "")
    name = entry.get("name") or os.path.basename(path)
    extension = os.path.splitext(name)[1].lower()
    return {
        "path": path,
        "name": name,
        "size": entry.get("size") or 0,
        "modified_date": float(entry.get("modified_date") or 0.0),
        "extension": extension,
        "file_type": _type_from_extension(extension),
        "provider": entry.get("cloud_provider") or _provider_for_path(path),
        "is_readable": entry.get("is_readable", True),
        "source": "cloud",
    }


def _iso_or_none(timestamp: float) -> Optional[str]:
    try:
        return datetime.fromtimestamp(float(timestamp)).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _not_found_result(filename: str, searched_cloud: bool) -> Dict[str, Any]:
    return {
        "success": False,
        "result_kind": "not_found",
        "error": f"File '{filename}' not found in local or cloud storage",
        "file_name": filename,
        "searched_cloud": searched_cloud,
    }


def _format_prepared_result(llm_request: Any) -> Dict[str, Any]:
    """Build the agent-facing 'prepared' dict (historical shape) from an LLMFileRequest."""
    content = llm_request.file_content
    metadata = content.metadata
    provider = _provider_for_path(llm_request.file_path)
    return {
        "success": True,
        "result_kind": "prepared",
        "file_path": llm_request.file_path,
        "file_name": metadata.name,
        "file_size": metadata.size,
        "file_type": metadata.file_type.value if hasattr(metadata.file_type, "value") else str(metadata.file_type),
        "content_encoding": llm_request.encoding_preference.value,
        "base64_content": content.base64_content,
        "extracted_text": content.extracted_text,
        "prompt_context": llm_request.prompt_context,
        "is_cloud_file": provider is not None,
        "cloud_provider": provider,
        "metadata": {
            "created_date": metadata.created_date.isoformat(),
            "modified_date": metadata.modified_date.isoformat(),
            "extension": metadata.extension,
            "mime_type": metadata.mime_type,
            "parent_directory": metadata.parent_directory,
        },
    }


def _format_candidate_for_output(candidate: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "path": candidate.get("path"),
        "name": candidate.get("name"),
        "size": candidate.get("size"),
        "modified_date": _iso_or_none(candidate.get("modified_date")),
        "file_type": candidate.get("file_type"),
        "provider": candidate.get("provider"),
        "score": round(float(candidate.get("score") or 0.0), 2),
    }


def _dedupe_by_path(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for candidate in candidates:
        try:
            key = os.path.realpath(str(candidate.get("path") or ""))
        except OSError:
            key = str(candidate.get("path") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


async def _gather_candidates(
    retrieval_service: Any,
    cloud_service: Any,
    filename: str,
    search_paths: Optional[List[str]],
) -> tuple[List[Dict[str, Any]], bool]:
    """Run Spotlight, then cloud find when the local result is empty or weak."""
    search_result = await retrieval_service.search_files_by_name(filename, search_paths)
    spotlight = [_normalize_metadata_candidate(meta) for meta in search_result.files_found]

    ranked_spotlight = rank_candidates(spotlight, filename) if spotlight else []
    best_local_score = ranked_spotlight[0]["score"] if ranked_spotlight else float("-inf")
    need_cloud = (not ranked_spotlight) or (best_local_score < WEAK_SPOTLIGHT_SCORE)

    searched_cloud = False
    combined = list(spotlight)
    if need_cloud:
        searched_cloud = True
        try:
            cloud_entries = await cloud_service.search_cloud_files(filename)
            combined.extend(_normalize_cloud_candidate(entry) for entry in cloud_entries)
        except Exception as exc:  # cloud find is best-effort, never fatal
            logger.debug(f"Cloud find failed for '{filename}': {exc}")

    return _dedupe_by_path(combined), searched_cloud


async def prepare_path(retrieval_service: Any, path: str, context: str = "") -> Dict[str, Any]:
    """Prepare a specific file path for the LLM (used after candidate selection)."""
    if not path or not os.path.exists(path):
        return {
            "success": False,
            "result_kind": "not_found",
            "error": f"Path does not exist or is not accessible: {path}",
            "file_path": path,
        }
    llm_request = await retrieval_service.prepare_file_for_llm(
        path, context, ContentEncoding.BASE64
    )
    if not llm_request:
        return {
            "success": False,
            "result_kind": "not_found",
            "error": f"Could not read or prepare file: {path}",
            "file_path": path,
        }
    return _format_prepared_result(llm_request)


async def find_or_list_candidates(
    retrieval_service: Any,
    cloud_service: Any,
    filename: str,
    context: str = "",
    search_paths: Optional[List[str]] = None,
    confident_only: bool = False,
) -> Dict[str, Any]:
    """Find a file by name; prepare a confident single match or list candidates.

    When `confident_only` is True (internal callers that need one result), the
    top-ranked candidate is always prepared, never a candidate list.
    """
    logger.info(f"🎯 Orchestrated find for '{filename}' (confident_only={confident_only})")

    candidates, searched_cloud = await _gather_candidates(
        retrieval_service, cloud_service, filename, search_paths
    )
    if not candidates:
        return _not_found_result(filename, searched_cloud)

    ranked = rank_candidates(candidates, filename)

    if confident_only:
        return await prepare_path(retrieval_service, ranked[0]["path"], context)

    confident, all_candidates = partition_candidates(ranked)
    if confident is not None:
        return await prepare_path(retrieval_service, confident["path"], context)

    total_candidates = len(all_candidates)
    returned_candidates = min(total_candidates, MAX_CANDIDATES_RETURNED)
    upstream_has_more = any(bool(candidate.get("discovery_has_more")) for candidate in all_candidates)
    return {
        "success": True,
        "result_kind": "candidates",
        "file_name": filename,
        "message": (
            f"Multiple files matched '{filename}'. Review the ranked candidates and "
            "call file_service_prepare_file_by_path with the chosen path to load its "
            "content. Do not assume the most recent one is correct."
        ),
        "searched_cloud": searched_cloud,
        "candidate_total_count": total_candidates,
        "candidate_returned_count": returned_candidates,
        "candidate_has_more": total_candidates > returned_candidates or upstream_has_more,
        "coverage_note": (
            "Candidate list is capped; do not treat this as exhaustive without a narrower search."
            if total_candidates > returned_candidates or upstream_has_more
            else "Candidate list is exhaustive for the searched sources."
        ),
        "candidates": [
            _format_candidate_for_output(candidate)
            for candidate in all_candidates[:MAX_CANDIDATES_RETURNED]
        ],
    }
