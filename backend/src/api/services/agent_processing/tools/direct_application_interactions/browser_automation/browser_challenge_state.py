"""Remember how often Basil has tried a text CAPTCHA and which temporary images it saved."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

MAX_TEXT_CAPTCHA_ATTEMPTS = 2

_lock = threading.Lock()
_attempts: Dict[Tuple[str, str], int] = {}
_images: Dict[Tuple[str, str], List[str]] = {}


def captcha_temp_directory() -> Path:
    """Return the shared temporary directory used for captures (`~/.basil/data/temp`)."""

    return Path.home() / ".basil" / "data" / "temp"


def _key(host: str) -> Tuple[str, str]:
    from .browser_pinned_target import browser_pin_key

    return (browser_pin_key() or "no-task", (host or "").strip().lower())


def attempts_used(host: str) -> int:
    with _lock:
        return _attempts.get(_key(host), 0)


def record_attempt(host: str) -> int:
    """Count one submitted code and return the new total for this task and host."""

    key = _key(host)
    with _lock:
        _attempts[key] = _attempts.get(key, 0) + 1
        return _attempts[key]


def reset_attempts(host: str) -> None:
    with _lock:
        _attempts.pop(_key(host), None)


def remember_image(host: str, path: str) -> None:
    with _lock:
        _images.setdefault(_key(host), []).append(str(path))


def delete_images(host: str) -> int:
    """Delete every image saved for this task and host. Returns how many files were removed."""

    with _lock:
        paths = _images.pop(_key(host), [])
    removed = 0
    for path in paths:
        try:
            Path(path).unlink()
            removed += 1
        except FileNotFoundError:
            continue
        except OSError as error:
            logger.debug("Could not delete CAPTCHA image %s: %s", path, error)
    return removed


def clear_all_state() -> None:
    """Forget every counter and image record. Used by tests."""

    with _lock:
        _attempts.clear()
        _images.clear()
