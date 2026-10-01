"""Internal Basil runtime paths that agent tools must never read, write, or reference."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROTECTED_RUNTIME_REFUSAL = "This action is not permitted by Basil's internal safety policy."
_REFERENCE_MARKERS = ("backend_credentials.json", ".basil/runtime")
_REMOVED_REFERENCE_CHARACTERS = str.maketrans("", "", "'\"`")
_REPEATED_SEPARATORS = re.compile(r"/{2,}")
_CURRENT_DIRECTORY_SEGMENTS = re.compile(r"/(?:\./)+")


def protected_runtime_directory() -> Path:
    return Path.home() / ".basil" / "runtime"


def is_protected_runtime_path(path: str | os.PathLike[str]) -> bool:
    try:
        candidate = Path(os.path.expanduser(os.fspath(path))).resolve(strict=False)
        protected = protected_runtime_directory().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return True
    return candidate == protected or protected in candidate.parents


def _normalized_reference_text(value: str) -> str:
    normalized = value.replace("\\", "/").translate(_REMOVED_REFERENCE_CHARACTERS).lower()
    normalized = _REPEATED_SEPARATORS.sub("/", normalized)
    return _CURRENT_DIRECTORY_SEGMENTS.sub("/", normalized)


def references_protected_runtime_path(*values: Optional[str]) -> bool:
    for value in values:
        if not value:
            continue
        normalized = _normalized_reference_text(str(value))
        if any(marker in normalized for marker in _REFERENCE_MARKERS):
            return True
    return False


def log_protected_runtime_refusal(surface: str) -> None:
    logger.warning("Refused agent %s that targets a protected Basil runtime path", surface)
