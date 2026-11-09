"""Save an oversized tool result and describe it, for the cap that keeps it out of the conversation."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from .shape import outline_text
from .store import save_result

logger = logging.getLogger(__name__)


def _readable(encoded: str) -> str:
    """The result with one JSON value per line, so a shell tool such as grep or head returns a small piece instead of one enormous line. Text that is not JSON is saved as it is."""
    try:
        return json.dumps(json.loads(encoded), ensure_ascii=False, indent=1)
    except (ValueError, RecursionError):
        return encoded


def spill_result(encoded: str) -> Optional[Dict[str, Any]]:
    """Store the full result and return its id, its file name inside the task workspace, and its outline, or None when it cannot be stored."""
    stored = save_result(_readable(encoded))
    if stored is None:
        return None
    try:
        outline: Optional[Dict[str, Any]] = outline_text(encoded)
    except Exception as exc:
        logger.warning("Stored result %s could not be outlined: %s", stored["result_id"], exc)
        outline = None
    return {"result_id": stored["result_id"], "file": stored["file"], "outline": outline}
