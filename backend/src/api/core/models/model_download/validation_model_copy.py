"""Copy an installed model from one models folder into another, for validation sessions only.

A fresh validation session starts with an empty private model folder, so a first-run rehearsal normally has to download every model again. This module lets that session copy a model the normal Basil already has instead. The source folder is only ever read.

The copy resolves paths with the same ``ModelArtifactStore`` rules the downloader uses, so the files land exactly where an installed model is expected. Files are staged under a temporary name and renamed into place, so a canceled or failed copy never leaves something that looks installed.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ...logging.api_logger import api_logger
from ..models_registry import get_model
from .artifacts import ModelArtifactStore

ProgressCallback = Callable[[float, str, Optional[Dict[str, Any]]], None]

_COPY_CHUNK_BYTES = 8 * 1024 * 1024
_SKIPPED_NAMES = frozenset({".DS_Store", ".cache"})
_STAGING_SUFFIX = ".copying"


class ModelCopyCanceled(Exception):
    """Raised when the copy stops because the user canceled it."""


@dataclass(frozen=True)
class ModelCopyPlan:
    """The exact files to copy for one model and the staging rule for them."""

    model_id: str
    files: Tuple[Tuple[Path, Path], ...]
    # When set, every destination file lives under this directory and the whole directory is staged and renamed at the end.
    staged_directory: Optional[Tuple[Path, Path]] = None

    @property
    def total_bytes(self) -> int:
        return sum(source.stat().st_size for source, _ in self.files)


def _stores(source_root: Path, destination_root: Path) -> Tuple[ModelArtifactStore, ModelArtifactStore]:
    # A path that never exists stands in for the legacy folder, so each store resolves only inside its own root.
    source_store = ModelArtifactStore(source_root, source_root / ".no-legacy-models")
    destination_store = ModelArtifactStore(destination_root, destination_root / ".no-legacy-models")
    return source_store, destination_store


def _walk_files(directory: Path) -> List[Path]:
    found: List[Path] = []
    for current, directory_names, file_names in os.walk(directory):
        directory_names[:] = [name for name in directory_names if name not in _SKIPPED_NAMES]
        for file_name in file_names:
            if file_name in _SKIPPED_NAMES:
                continue
            path = Path(current) / file_name
            if path.is_file() and not path.is_symlink():
                found.append(path)
    return sorted(found)


def plan_model_copy(model_id: str, source_root: Path, destination_root: Path) -> Optional[ModelCopyPlan]:
    """Return what to copy, or None when the source folder does not hold a complete copy of this model."""
    config = get_model(model_id)
    if not config:
        return None
    source_store, destination_store = _stores(source_root, destination_root)

    manifest = source_store._manifest_files(config)
    if manifest:
        if not source_store.artifact_manifest_is_complete(config, source_root):
            return None
        artifact_root = source_store._safe_relative_artifact_path(config["artifact_root"])
        primary = str(config["primary_artifact"])
        names = [str(item.get("file")) for item in manifest]
        # The primary artifact goes last, so a model is never complete before its other parts are in place.
        names.sort(key=lambda name: name == primary)
        files = tuple(
            (source_root / artifact_root / name, destination_root / artifact_root / name)
            for name in names
        )
        return ModelCopyPlan(model_id=model_id, files=files)

    if config.get("handler") == "llama_cpp_vision":
        return None

    source_primary = source_store.get_model_path_for_id(model_id)
    destination_primary = destination_store.get_model_path_for_id(model_id)
    if source_primary.is_dir():
        files = tuple(
            (path, destination_primary / path.relative_to(source_primary))
            for path in _walk_files(source_primary)
        )
        if not files:
            return None
        staging = destination_primary.parent / f".{destination_primary.name}{_STAGING_SUFFIX}"
        return ModelCopyPlan(
            model_id=model_id,
            files=tuple((source, staging / destination.relative_to(destination_primary)) for source, destination in files),
            staged_directory=(staging, destination_primary),
        )
    if not source_primary.is_file():
        return None

    companions = []
    for companion in ModelArtifactStore.get_companion_downloads(config):
        companion_source = source_root / companion["file"]
        if not companion_source.is_file():
            return None
        companions.append((companion_source, destination_root / companion["file"]))
    return ModelCopyPlan(model_id=model_id, files=(*companions, (source_primary, destination_primary)))


def source_has_model(model_id: str, source_root: Path, destination_root: Path) -> bool:
    return plan_model_copy(model_id, source_root, destination_root) is not None


def _copy_one_file(
    source: Path,
    destination: Path,
    *,
    stage_in_place: bool,
    on_bytes: Callable[[int], None],
    cancel_event: Optional[asyncio.Event],
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    target = destination.with_name(destination.name + _STAGING_SUFFIX) if stage_in_place else destination
    try:
        with open(source, "rb") as reader, open(target, "wb") as writer:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise ModelCopyCanceled()
                chunk = reader.read(_COPY_CHUNK_BYTES)
                if not chunk:
                    break
                writer.write(chunk)
                on_bytes(len(chunk))
        shutil.copystat(source, target, follow_symlinks=False)
        if stage_in_place:
            os.replace(target, destination)
    except BaseException:
        if stage_in_place:
            target.unlink(missing_ok=True)
        raise


def copy_model(
    plan: ModelCopyPlan,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_event: Optional[asyncio.Event] = None,
) -> None:
    """Copy every planned file. Blocking, so callers run it in a worker thread."""
    total_bytes = max(plan.total_bytes, 1)
    total_files = len(plan.files)
    copied_bytes = 0
    staging_directory = plan.staged_directory

    if staging_directory is not None and staging_directory[0].exists():
        shutil.rmtree(staging_directory[0])

    def report(current_name: str, files_completed: int) -> None:
        if progress_callback is None:
            return
        progress_callback(
            min(copied_bytes / total_bytes, 0.999),
            "downloading",
            {
                "total_downloaded": copied_bytes,
                "total_size": total_bytes,
                "current_file": current_name,
                "files_completed": files_completed,
                "total_files": total_files,
                "message": "Copying from your normal Basil",
            },
        )

    def add_bytes(count: int) -> None:
        nonlocal copied_bytes
        copied_bytes += count

    try:
        for index, (source, destination) in enumerate(plan.files):
            report(source.name, index)
            _copy_one_file(
                source,
                destination,
                stage_in_place=staging_directory is None,
                on_bytes=lambda count, name=source.name, done=index: (add_bytes(count), report(name, done)),
                cancel_event=cancel_event,
            )
        if staging_directory is not None:
            staging, final = staging_directory
            if final.exists():
                shutil.rmtree(final)
            os.replace(staging, final)
    except BaseException:
        if staging_directory is not None:
            shutil.rmtree(staging_directory[0], ignore_errors=True)
        raise
    api_logger.info("[MODEL_COPY] copied %s (%d files, %d bytes)", plan.model_id, total_files, copied_bytes)
