"""Process-wide registry of live meeting recorders so a canceled recording part can be discarded.

Also fans recorder lifecycle and transcript-segment notifications out to registered listeners (the live meeting Companion). Listeners run synchronously inside the audio results loop, so they must be non-blocking and must never raise; a raising listener is logged and isolated.
"""

from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# listener(event, meeting_id, recorder, payload) where event is one of
# "started", "stopped", "discarded", "segment".
RecorderListener = Callable[[str, str, Any, Optional[Dict[str, Any]]], None]

_lock = threading.Lock()
_active: Dict[str, Any] = {}
_discarded: Set[str] = set()
_listeners: List[RecorderListener] = []


def add_listener(listener: RecorderListener) -> None:
    with _lock:
        if listener not in _listeners:
            _listeners.append(listener)


def remove_listener(listener: RecorderListener) -> None:
    with _lock:
        if listener in _listeners:
            _listeners.remove(listener)


def active_recorders() -> List[Any]:
    """Snapshot of the recorders that are currently registered."""
    with _lock:
        return list(_active.values())


def _notify(event: str, meeting_id: str, recorder: Any, payload: Optional[Dict[str, Any]] = None) -> None:
    with _lock:
        listeners = list(_listeners)
    for listener in listeners:
        try:
            listener(event, meeting_id, recorder, payload)
        except Exception as error:
            logger.error("Recording listener failed on %s for %s: %s", event, meeting_id, error, exc_info=True)


def notify_segment(recorder: Any, segment: Dict[str, Any]) -> None:
    """Announce one finalized transcript segment appended by ``recorder``."""
    _notify("segment", getattr(recorder, "meeting_id", ""), recorder, {"segment": segment})


def register(meeting_id: str, recorder: Any) -> None:
    with _lock:
        _active[meeting_id] = recorder
    _notify("started", meeting_id, recorder)


def unregister(meeting_id: str, recorder: Any) -> None:
    removed = False
    with _lock:
        if _active.get(meeting_id) is recorder:
            del _active[meeting_id]
            removed = True
    if removed:
        _notify("stopped", meeting_id, recorder)


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
    _notify("discarded", meeting_id, recorder)
    logger.info("Discarded meeting recording %s (active=%s, directory=%s)", meeting_id, recorder is not None, existed)
    return recorder is not None or existed
