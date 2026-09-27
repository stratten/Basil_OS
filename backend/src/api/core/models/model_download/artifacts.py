"""Filesystem artifact helpers for model downloads.

This module sits behind ``ModelDownloader`` and owns the disk-facing behavior:
path resolution, installed-model discovery, companion metadata, and artifact
removal. Keeping this logic here lets ``model_downloader.py`` remain the public
facade without carrying all filesystem details inline.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Set

from ...logging.api_logger import api_logger
from ..models_registry import get_downloadable_models, get_model, get_on_disk_name
from ..models_registry.local_vision_registry import local_vision_files_present


class ModelArtifactStore:
    """Resolve and manage model artifacts under Basil's model directories."""

    def __init__(self, models_dir: Path, legacy_models_dir: Path) -> None:
        self.models_dir = models_dir
        self.legacy_models_dir = legacy_models_dir

    @staticmethod
    def _manifest_files(model_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        files = model_cfg.get("artifact_files")
        if not isinstance(files, list):
            return []
        return [item for item in files if isinstance(item, dict)]

    @staticmethod
    def _safe_relative_artifact_path(value: Any) -> Path:
        candidate = Path(str(value or ""))
        if not candidate.parts or candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Invalid relative artifact path: {value!r}")
        return candidate

    def artifact_manifest_is_complete(
        self,
        model_cfg: Dict[str, Any],
        base_dir: Path,
    ) -> bool:
        """Return whether every declared artifact exists beneath one manifest root."""
        artifacts = self._manifest_files(model_cfg)
        if not artifacts:
            return False
        root_name = model_cfg.get("artifact_root")
        primary_name = model_cfg.get("primary_artifact")
        if not isinstance(root_name, str) or not isinstance(primary_name, str):
            return False
        try:
            root = base_dir / self._safe_relative_artifact_path(root_name)
            primary = root / self._safe_relative_artifact_path(primary_name)
            if not primary.is_file():
                return False
            return all(
                (root / self._safe_relative_artifact_path(item.get("file"))).is_file()
                for item in artifacts
            )
        except ValueError:
            return False

    def _manifest_primary_path(
        self,
        model_cfg: Dict[str, Any],
        base_dir: Path,
    ) -> Path:
        return (
            base_dir
            / self._safe_relative_artifact_path(model_cfg["artifact_root"])
            / self._safe_relative_artifact_path(model_cfg["primary_artifact"])
        )

    def get_model_path_for_id(self, model_id: str) -> Path:
        """Return the expected primary artifact path for one registry model."""
        on_disk_name = get_on_disk_name(model_id)
        cfg = get_model(model_id)
        if not on_disk_name or not cfg:
            raise ValueError(f"Model '{model_id}' not found in registry")

        if self._manifest_files(cfg):
            if self.artifact_manifest_is_complete(cfg, self.legacy_models_dir):
                return self._manifest_primary_path(cfg, self.legacy_models_dir)
            return self._manifest_primary_path(cfg, self.models_dir)

        download_url = cfg.get("download_url")
        if download_url:
            extension = Path(download_url).suffix
            new_path = self.models_dir / f"{on_disk_name}{extension}"
            legacy_path = self.legacy_models_dir / f"{on_disk_name}{extension}"
        else:
            new_path = self.models_dir / on_disk_name
            legacy_path = self.legacy_models_dir / on_disk_name
        return legacy_path if legacy_path.exists() else new_path

    @staticmethod
    def get_companion_downloads(model_cfg: Dict[str, Any]) -> List[Dict[str, str]]:
        """Return normalized companion file download metadata for a model."""
        companions: List[Dict[str, str]] = []
        for companion in model_cfg.get("companion_downloads") or []:
            filename = companion.get("file") or Path(companion.get("download_url", "")).name
            download_url = companion.get("download_url")
            if filename and download_url:
                companions.append({"file": filename, "download_url": download_url})
        return companions

    def get_installed_models(self) -> Dict[str, Any]:
        """Get installed models, requiring all files for a sharded manifest."""
        installed: Dict[str, Any] = {}

        def normalize(name: str) -> str:
            for suffix in ["-base", ".gguf", ".safetensors", ".bin", ".pt", ".pth"]:
                if name.endswith(suffix):
                    name = name[: -len(suffix)]
            return name.lower()

        disk_files: Dict[str, Path] = {}
        for entry in self.models_dir.iterdir():
            if entry.is_dir() or entry.suffix in [".gguf", ".safetensors", ".bin", ".pt", ".pth"]:
                disk_files[normalize(entry.name)] = entry

        for model_id, cfg in get_downloadable_models().items():
            provider, variant = model_id.split("-", 1) if "-" in model_id else (model_id, model_id)

            if self._manifest_files(cfg):
                installed_base = None
                for base_dir in (self.models_dir, self.legacy_models_dir):
                    if self.artifact_manifest_is_complete(cfg, base_dir):
                        installed_base = base_dir
                        break
                if installed_base is None:
                    continue
                path = self._manifest_primary_path(cfg, installed_base)
            elif cfg.get("handler") == "llama_cpp_vision":
                if not local_vision_files_present(self.models_dir, cfg):
                    continue
                path = self.models_dir / cfg["main_model_file"]
            else:
                on_disk = cfg.get("on_disk_name", variant)
                path = disk_files.get(normalize(on_disk)) or disk_files.get(normalize(variant))
                if path is None:
                    continue

            installed.setdefault(provider, {"variants": {}})["variants"][variant] = {
                "model_id": model_id,
                "valid": True,
                "name": cfg.get("display_name", model_id),
                "path": str(path),
                "capabilities": cfg.get("capabilities", []),
            }
        return installed

    def remove_model(self, model_type: str, variant: str) -> bool:
        """Remove one complete model artifact set and its Hugging Face cache."""
        model_id = f"{model_type}-{variant}"
        model_cfg = get_model(model_id)
        if not model_cfg:
            return False

        success = True
        if self._manifest_files(model_cfg):
            root_name = self._safe_relative_artifact_path(model_cfg["artifact_root"])
            for base_dir in (self.models_dir, self.legacy_models_dir):
                root = base_dir / root_name
                if root.exists():
                    try:
                        shutil.rmtree(root)
                    except Exception as exc:
                        api_logger.error("Error removing artifact root %s: %s", root, exc)
                        success = False
        else:
            model_path = self.get_model_path_for_id(model_id)
            if model_path.exists():
                try:
                    if model_path.is_file():
                        os.remove(model_path)
                    else:
                        shutil.rmtree(model_path)
                except Exception as exc:
                    api_logger.error("Error removing model: %s", exc)
                    success = False

            companion_names: Set[str] = {
                companion["file"] for companion in self.get_companion_downloads(model_cfg)
            }
            if model_cfg.get("mmproj_file"):
                companion_names.add(str(model_cfg["mmproj_file"]))
            for companion_name in companion_names:
                for base_dir in (self.models_dir, self.legacy_models_dir):
                    companion_path = base_dir / companion_name
                    if not companion_path.exists():
                        continue
                    try:
                        os.remove(companion_path)
                    except Exception as exc:
                        api_logger.error("Error removing companion model file: %s", exc)
                        success = False

        hf_url = model_cfg.get("repo_url") or model_cfg.get("download_url")
        if hf_url and "huggingface.co/" in hf_url:
            try:
                path_part = hf_url.split("huggingface.co/", 1)[1]
                path_segments = path_part.split("/")
                if len(path_segments) >= 2:
                    repo_id = f"{path_segments[0]}/{path_segments[1]}"
                    cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
                    repo_cache_dir = cache_dir / ("models--" + repo_id.replace("/", "--"))
                    if repo_cache_dir.exists():
                        shutil.rmtree(repo_cache_dir)
            except Exception as exc:
                api_logger.error("Error removing HF cache: %s", exc)
                success = False
        return success

    def remove_partial_artifacts(self, model_type: str, variant: str) -> bool:
        """Remove local incomplete artifacts without discarding resumable HF blobs."""
        model_id = f"{model_type}-{variant}"
        model_cfg = get_model(model_id)
        if not model_cfg:
            return False
        success = True
        if self._manifest_files(model_cfg):
            root_name = self._safe_relative_artifact_path(model_cfg["artifact_root"])
            for base_dir in (self.models_dir, self.legacy_models_dir):
                root = base_dir / root_name
                if root.exists():
                    try:
                        shutil.rmtree(root)
                    except Exception as exc:
                        api_logger.error("Error removing partial artifact root %s: %s", root, exc)
                        success = False
            return success

        model_path = self.get_model_path_for_id(model_id)
        if model_path.exists():
            try:
                if model_path.is_file():
                    os.remove(model_path)
                else:
                    shutil.rmtree(model_path)
            except Exception as exc:
                api_logger.error("Error removing partial model: %s", exc)
                success = False
        return success
