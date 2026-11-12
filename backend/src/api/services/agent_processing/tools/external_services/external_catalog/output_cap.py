"""Bound the size of an external_catalog result before it enters the agent's conversation.

The service tools clip their output to a share of the model's context window, but external_catalog returns whatever a connector sends. One connector call returned about 2.5 million characters and pushed a run past its model's window. A result over the limit is saved whole when a spill function is given, and the conversation receives a preview, an outline, and the id to read it back with. Without a spill function, or when saving fails, it is clipped to the limit.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

DEFAULT_MAX_RESULT_CHARS = 60_000
MIN_USABLE_LIMIT_CHARS = 3_000
MAX_PREVIEW_CHARS = 6_000
MIN_PREVIEW_CHARS = 500
_ENVELOPE_RESERVE_CHARS = 1_500
_OUTLINE_LISTS = ("largest", "largest_items")


def _preview_chars(limit: int) -> int:
    """A tenth of the limit, so the preview is a small share of a small window, between 500 and 6,000 characters."""
    return max(MIN_PREVIEW_CHARS, min(MAX_PREVIEW_CHARS, limit // 10))


def _trimmed_outline(outline: Any, entries: Optional[int]) -> Any:
    if not isinstance(outline, dict) or entries is None:
        return outline
    trimmed = dict(outline)
    for key in _OUTLINE_LISTS:
        if isinstance(trimmed.get(key), list):
            trimmed[key] = trimmed[key][:entries]
    return trimmed


def _stored_envelope(encoded: str, stored: Dict[str, Any], *, preview_chars: int, outline_entries: Optional[int]) -> str:
    preview = encoded[:preview_chars]
    result_id = stored["result_id"]
    file_name = stored.get("file")
    where = (
        f" It is also a file named {file_name} in this task's workspace folder, which shell commands such as grep and head can read."
        " To pick fields out of a JSON file, use jq if `command -v jq` finds it, because a Python script for the same job would ask the user for approval."
    ) if file_name else ""
    envelope: Dict[str, Any] = {
        "ok": True,
        "stored": True,
        "result_id": result_id,
        "original_size_chars": len(encoded),
        "message": (
            f"The connector returned {len(encoded):,} characters, more than fits in this conversation, so the whole result was saved as {result_id} and only a short preview is shown. "
            "Use the stored_result tool with this result_id instead of calling the connector again for the same data: action outline (with an optional path) shows what is inside and how big each part is, read returns one part, and search finds a value."
            f"{where} "
            "external_catalog has no output-size argument, so max_output_bytes does nothing here."
        ),
        "outline": _trimmed_outline(stored.get("outline"), outline_entries),
    }
    if file_name:
        envelope["file"] = file_name
    if preview:
        envelope["preview_chars"] = len(preview)
        envelope["preview"] = preview
    return json.dumps(envelope, ensure_ascii=False)


def cap_external_catalog_result(
    encoded: str,
    max_chars: Optional[int],
    *,
    spill: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
) -> str:
    """Return the encoded result unchanged when it fits, a stored-result envelope when it can be saved, and otherwise an envelope with its start and an instruction to ask for less."""
    limit = max_chars if isinstance(max_chars, int) and not isinstance(max_chars, bool) and max_chars >= MIN_USABLE_LIMIT_CHARS else DEFAULT_MAX_RESULT_CHARS
    if len(encoded) <= limit:
        return encoded
    if spill is not None:
        try:
            stored = spill(encoded)
        except Exception:
            stored = None
        if stored:
            preview = _preview_chars(limit)
            # Each step down gives up some preview and some of the outline, so a small window still gets the id and a pointer to the file
            for preview_chars, outline_entries in ((preview, None), (preview // 3, 8), (0, 4)):
                envelope = _stored_envelope(encoded, stored, preview_chars=preview_chars, outline_entries=outline_entries)
                if len(envelope) <= limit:
                    return envelope
    kept = encoded[: limit - _ENVELOPE_RESERVE_CHARS]
    return json.dumps(
        {
            "ok": True,
            "truncated": True,
            "original_size_chars": len(encoded),
            "kept_chars": len(kept),
            "message": (
                f"The connector returned {len(encoded):,} characters, more than fits in this conversation, so only the first {len(kept):,} are shown and the rest was discarded. "
                "external_catalog has no output-size argument, so max_output_bytes does nothing here. "
                "Call the connector tool again with narrower arguments, such as a specific id, a list of the fields or sections you need, a smaller limit, or one page, and ask only for what the task needs."
            ),
            "content_preview": f"{kept}\n...[TRUNCATED]...",
        },
        ensure_ascii=False,
    )
