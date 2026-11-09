"""Remove a model's Hugging Face cache copy once Basil has its own installed copy.

Basil downloads model files through the Hugging Face cache (``hf_hub_download`` and
``snapshot_download``) and then copies them into its models directory. Until the copy is
verified the cache holds the only copy and is what lets an interrupted download resume, so
nothing here runs before a download has finished. After that the cache copy is a
duplicate that costs as much disk as the model itself.

Deletion goes through ``huggingface_hub.scan_cache_dir().delete_revisions`` and not
``shutil.rmtree`` on the repo folder, because newer ``huggingface_hub`` releases keep file
contents in a cache-wide shared blob store. Removing only the repo folder would leave those
shared blobs behind and free no space.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ...logging.api_logger import api_logger

_HF_HOST_MARKER = "huggingface.co/"


def repo_id_from_model_config(model_cfg: Dict[str, Any]) -> Optional[str]:
    """Return the ``owner/name`` Hugging Face repo id a registry entry downloads from."""
    url = model_cfg.get("repo_url") or model_cfg.get("download_url")
    if not isinstance(url, str) or _HF_HOST_MARKER not in url:
        return None
    segments = url.split(_HF_HOST_MARKER, 1)[1].split("/")
    if len(segments) < 2 or not segments[0] or not segments[1]:
        return None
    return f"{segments[0]}/{segments[1]}"


def discard_cached_repo(repo_id: str, cache_dir: Optional[Path] = None) -> int:
    """Delete every cached revision of one model repo and return the bytes freed.

    Returns 0 when the cache or the repo is absent. Raises nothing for a missing cache, and
    lets any other failure propagate so the caller decides whether it is fatal.
    """
    from huggingface_hub import constants, scan_cache_dir

    resolved_cache_dir = Path(cache_dir) if cache_dir is not None else Path(constants.HF_HUB_CACHE)
    if not resolved_cache_dir.is_dir():
        return 0

    cache_info = scan_cache_dir(resolved_cache_dir)
    revisions = [
        revision.commit_hash
        for repo in cache_info.repos
        if repo.repo_type == "model" and repo.repo_id == repo_id
        for revision in repo.revisions
    ]
    if not revisions:
        return 0

    strategy = cache_info.delete_revisions(*revisions)
    freed_bytes = int(strategy.expected_freed_size)
    strategy.execute()
    api_logger.info(
        "Removed Hugging Face cache copy of %s (%d revisions, %.2f GB freed)",
        repo_id,
        len(revisions),
        freed_bytes / 1e9,
    )
    return freed_bytes
