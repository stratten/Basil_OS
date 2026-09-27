"""
Single source of truth for resolving a Whisper transcription model name to its
on-disk location, HuggingFace repo id, and a stable warm-cache key.

Both the on-demand/file transcription stack (``ModelManager``) and the
post-processing retranscription stack (``WhisperModelLoader``) resolve models
through this module so they share one warm-cache entry per model. It replaces
the two previously-duplicated mappings:

  * ``WhisperModelLoader.MODEL_NAME_MAPPING`` (display name -> on-disk dir), and
  * ``ModelManager._get_model_id_from_display_name`` (display name -> repo id).

Resolution prefers the local ``~/.basil/models/<on_disk_name>`` directory (the
canonical, offline location for a packaged app) and falls back to the
HuggingFace repo id only when the local directory is absent.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from api.settings import get_models_dir
from api.core.models.models_registry import (
    get_model,
    get_repo_info,
    get_transcription_models,
)

_HF_URL_PREFIX = "https://huggingface.co/"

# Files whose presence indicates a model directory has finished downloading.
# HuggingFace dirs always carry config.json; the downloader also drops a
# ``.downloaded`` marker. Either is sufficient evidence of a usable local copy.
_LOCAL_PRESENCE_MARKERS = ("config.json", ".downloaded")


@dataclass(frozen=True)
class WhisperModelSource:
    """Resolved load information for a single local Whisper model."""

    model_id: str
    display_name: str
    on_disk_name: Optional[str]
    local_dir: Path
    repo_id: Optional[str]
    revision: str
    exists_locally: bool

    @property
    def cache_key(self) -> str:
        """Stable key identifying these weights for the shared warm cache.

        Keyed by the local directory when present so the on-demand and
        post-processing stacks resolve to the SAME warm entry; otherwise keyed
        by the HuggingFace repo id used for the download fallback.
        """
        if self.exists_locally:
            return f"local:{self.local_dir}"
        if self.repo_id:
            return f"hf:{self.repo_id}"
        # Last resort: key by the on-disk dir even if not yet present, so a key
        # is always available. (Loading will fail clearly downstream.)
        return f"local:{self.local_dir}"


def _find_transcription_config(name_or_id: str) -> Tuple[str, Dict]:
    """Resolve ``name_or_id`` to a (model_id, config) from the local registry.

    Accepts either a registry id (e.g. "OpenAI-whisper-large-v3-turbo") or a
    display name (e.g. "Whisper Large V3 Turbo").
    """
    direct = get_model(name_or_id)
    if direct is not None:
        return name_or_id, direct

    for model_id, config in get_transcription_models().items():
        if config.get("display_name") == name_or_id:
            return model_id, config

    raise ValueError(
        f"Whisper transcription model is not registered: {name_or_id!r}"
    )


def _repo_id_from_url(repo_url: Optional[str]) -> Optional[str]:
    if not repo_url:
        return None
    if repo_url.startswith(_HF_URL_PREFIX):
        return repo_url[len(_HF_URL_PREFIX):]
    return repo_url


def _local_dir_is_present(local_dir: Path) -> bool:
    if not local_dir.is_dir():
        return False
    return any((local_dir / marker).exists() for marker in _LOCAL_PRESENCE_MARKERS)


def resolve_whisper_source(name_or_id: str) -> WhisperModelSource:
    """Resolve a Whisper model name/id to its load location and warm-cache key.

    Raises:
        ValueError: if ``name_or_id`` is not a registered local transcription
            model.
    """
    model_id, config = _find_transcription_config(name_or_id)

    on_disk_name = config.get("on_disk_name")
    # Fall back to a lowercased id only when the registry omits on_disk_name,
    # mirroring the prior loader behavior so nothing regresses.
    dir_name = on_disk_name or model_id.lower()
    local_dir = get_models_dir() / dir_name

    repo_info = get_repo_info(model_id)
    repo_url = repo_info[0] if repo_info else config.get("repo_url")
    revision = repo_info[1] if repo_info else config.get("revision", "main")
    repo_id = _repo_id_from_url(repo_url)

    return WhisperModelSource(
        model_id=model_id,
        display_name=config.get("display_name", model_id),
        on_disk_name=on_disk_name,
        local_dir=local_dir,
        repo_id=repo_id,
        revision=revision or "main",
        exists_locally=_local_dir_is_present(local_dir),
    )
