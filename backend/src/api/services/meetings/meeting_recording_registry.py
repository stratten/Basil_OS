"""Process-wide registry of live meeting recorders so a canceled recording part can be discarded."""

from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, Set

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_active: Dict[str, Any] = {}
_discarded: Set[str] = set()


def register(meeting_id: str, recorder: Any) -> None:
    with _lock:
        _active[meeting_id] = recorder


def unregister(meeting_id: str, recorder: Any) -> None:
    with _lock:
        if _active.get(meeting_id) is recorder:
            del _active[meeting_id]


def is_active(meeting_id: str) -> bool:
    with _lock:
        return meeting_id in _active


def is_discarded(meeting_id: str) -> bool:
    with _lock:
        return meeting_id in _discarded


def discard(meeting_id: str, meeting_dir: Path) -> bool:
    """Abandon any live recorder for ``meeting_id``, delete its directory, and refuse later recorders for it.

    Returns whether a live recorder or an on-disk directory was found.
    """
    with _lock:
        _discarded.add(meeting_id)
        recorder = _active.pop(meeting_id, None)
    if recorder is not None:
        try:
            recorder.abandon_recording()
        except Exception as error:
            logger.error("Failed to abandon recorder for %s: %s", meeting_id, error, exc_info=True)
    existed = meeting_dir.exists()
    if existed:
        shutil.rmtree(meeting_dir, ignore_errors=True)
    logger.info("Discarded meeting recording %s (active=%s, directory=%s)", meeting_id, recorder is not None, existed)
    return recorder is not None or existed
