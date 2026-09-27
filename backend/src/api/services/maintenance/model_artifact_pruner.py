"""Prune redundant alternate formats from Basil's embedding-model snapshot."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

_EMBEDDING_ROOT = Path("sentence-transformers") / "all-MiniLM-L6-v2"
_REDUNDANT_PATHS = (
    Path("tf_model.h5"),
    Path("pytorch_model.bin"),
    Path("rust_model.ot"),
    Path("onnx"),
    Path("openvino"),
)


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    return 0


def prune_redundant_embedding_artifacts(models_dir: Path) -> dict[str, Any]:
    """Remove only known non-PyTorch formats from the retrieval embedding model."""
    model_root = models_dir / _EMBEDDING_ROOT
    report: dict[str, Any] = {
        "target": str(model_root),
        "removed_paths": [],
        "files_removed": 0,
        "bytes_removed": 0,
        "errors": [],
    }
    if not model_root.is_dir():
        return report

    for relative_path in _REDUNDANT_PATHS:
        candidate = model_root / relative_path
        if not candidate.exists() or candidate.is_symlink():
            continue
        try:
            bytes_removed = _path_size(candidate)
            files_removed = 1 if candidate.is_file() else sum(
                1 for item in candidate.rglob("*") if item.is_file()
            )
            if candidate.is_dir():
                shutil.rmtree(candidate)
            else:
                candidate.unlink()
            report["removed_paths"].append(str(candidate))
            report["files_removed"] += files_removed
            report["bytes_removed"] += bytes_removed
        except OSError as exc:
            report["errors"].append(f"{candidate}: {exc}")
            logger.warning("Embedding artifact cleanup failed for %s: %s", candidate, exc)

    if report["removed_paths"] or report["errors"]:
        logger.info(
            "Embedding artifact cleanup: target=%s files_removed=%s bytes_removed=%s paths=%s",
            report["target"],
            report["files_removed"],
            report["bytes_removed"],
            report["removed_paths"],
        )
    return report
