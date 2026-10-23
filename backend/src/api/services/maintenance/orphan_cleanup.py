"""One-shot startup helper for purging Huey-era / JSON-progress leftovers.

Invoked from `api/main.py` and `basil_api.py` startup hooks (step 1.6.18 of
the Huey-removal plan). Runs once per process boot, swallows every error,
and never raises -- the goal is "best-effort hygiene", not correctness.

What gets removed:

  * `~/.basil/huey/`             -- Huey SQLite storage root (if it exists).
  * `~/.basil/.huey.pid`         -- legacy PID file written by old dev.sh.
  * `~/.basil/tasks/`            -- Huey task DB directory (`tasks.db` lived
                                    here under some configs).
  * Per-model `progress_*.json`  -- the file-based IPC channel deleted in
                                    step 1.2.6. Only `progress_<id>.json`
                                    plus their `.json.tmp` siblings are
                                    targeted; nothing else under the models
                                    directory is touched.
  * `<base>/.huey.db`            -- legacy single-file Huey storage that
                                    older `dev.sh` runs left alongside the
                                    repo root.

All deletes are guarded with `exists()` and a broad `try/except` so an
unexpected file shape (mounted volume, permissions glitch, etc.) cannot
break startup.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


def _safe_unlink(path: Path) -> bool:
    try:
        if path.exists():
            path.unlink()
            return True
    except Exception as exc:
        logger.debug(f"[ORPHAN_CLEANUP] unlink failed for {path}: {exc}")
    return False


def _safe_rmtree(path: Path) -> bool:
    try:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
            return True
    except Exception as exc:
        logger.debug(f"[ORPHAN_CLEANUP] rmtree failed for {path}: {exc}")
    return False


def _iter_progress_files(models_dir: Optional[Path]) -> Iterable[Path]:
    """Yield `progress_*.json[.tmp]` paths under `models_dir`, if it exists.

    The glob is intentionally narrow so a misconfigured `models_dir` (e.g.
    pointing at the user's home) cannot wipe unrelated files.
    """
    if not models_dir or not models_dir.exists() or not models_dir.is_dir():
        return ()
    try:
        files = list(models_dir.glob("progress_*.json"))
        files.extend(models_dir.glob("progress_*.json.tmp"))
        return files
    except Exception as exc:
        logger.debug(
            f"[ORPHAN_CLEANUP] glob failed for {models_dir}: {exc}"
        )
        return ()


def cleanup_huey_orphans(models_dir: Optional[Path] = None) -> dict:
    """Remove Huey-era + JSON-progress leftovers. Best-effort, idempotent.

    Args:
        models_dir: optional explicit models directory (used to scope the
            `progress_*.json` cleanup). When omitted, the helper still
            handles the `~/.basil/*` leftovers; the per-model JSON cleanup
            simply no-ops.

    Returns:
        Counts dict (for logging only): `{"dirs": N, "files": N}`.
    """
    counts = {"dirs": 0, "files": 0}

    home = Path.home()
    basil_root = home / ".basil"

    huey_dir = basil_root / "huey"
    huey_pid = basil_root / ".huey.pid"
    huey_tasks_dir = basil_root / "tasks"

    if _safe_rmtree(huey_dir):
        counts["dirs"] += 1
        logger.info(f"[ORPHAN_CLEANUP] removed {huey_dir}")

    if _safe_rmtree(huey_tasks_dir):
        counts["dirs"] += 1
        logger.info(f"[ORPHAN_CLEANUP] removed {huey_tasks_dir}")

    if _safe_unlink(huey_pid):
        counts["files"] += 1
        logger.info(f"[ORPHAN_CLEANUP] removed {huey_pid}")

    # Legacy single-file Huey storage that old dev.sh runs sometimes left
    # next to the repo root. Look for both common locations.
    for legacy_db in (Path.cwd() / ".huey.db", basil_root / ".huey.db"):
        if _safe_unlink(legacy_db):
            counts["files"] += 1
            logger.info(f"[ORPHAN_CLEANUP] removed {legacy_db}")

    for progress_file in _iter_progress_files(models_dir):
        if _safe_unlink(progress_file):
            counts["files"] += 1

    if counts["files"] or counts["dirs"]:
        logger.info(
            "[ORPHAN_CLEANUP] cleanup complete: "
            f"{counts['files']} file(s), {counts['dirs']} dir(s) removed"
        )
    else:
        logger.debug("[ORPHAN_CLEANUP] no leftovers to remove")

    return counts
