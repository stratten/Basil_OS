"""Guarded cleanup for the retired MemVid derived-data directory."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from api.settings import get_settings


logger = logging.getLogger(__name__)


def get_legacy_memvid_root() -> Path:
    """Resolve the former MemVid location from Basil's configured data root."""
    return Path(get_settings().data_dir).expanduser().resolve() / "memvid"


def _count_tree(path: Path) -> tuple[int, int]:
    files = 0
    bytes_removed = 0
    for item in path.rglob("*"):
        if item.is_file():
            files += 1
            bytes_removed += item.stat().st_size
    return files, bytes_removed


def _is_direct_child_of_data_root(target: Path) -> bool:
    data_root = Path(get_settings().data_dir).expanduser().resolve()
    return target.parent == data_root and target.name == "memvid"


def _remove_tree_bottom_up(target: Path) -> None:
    for item in sorted(target.rglob("*"), key=lambda path: len(path.parts), reverse=True):
        if item.is_dir() and not item.is_symlink():
            item.rmdir()
        else:
            item.unlink()
    target.rmdir()


def cleanup_legacy_memvid_data(delete: bool = False) -> dict[str, Any]:
    """Inspect or remove only the computed retired MemVid root."""
    target = get_legacy_memvid_root()
    report: dict[str, Any] = {
        "target": str(target),
        "exists": target.exists(),
        "deleted": False,
        "files_removed": 0,
        "bytes_removed": 0,
        "error": None,
    }
    if not target.exists():
        return report
    if not _is_direct_child_of_data_root(target) or target.is_symlink():
        report["error"] = "Refusing cleanup target outside the configured Basil data root."
        logger.warning("Legacy MemVid cleanup refused target=%s", target)
        return report

    try:
        files_removed, bytes_removed = _count_tree(target)
        report["files_removed"] = files_removed
        report["bytes_removed"] = bytes_removed
        if delete:
            _remove_tree_bottom_up(target)
            report["deleted"] = True
            logger.info(
                "Legacy MemVid cleanup: target=%s files_removed=%s bytes_removed=%s",
                target,
                files_removed,
                bytes_removed,
            )
    except OSError as exc:
        report["error"] = str(exc)
        logger.warning("Legacy MemVid cleanup failed for %s: %s", target, exc)
    return report
