"""Keep an oversized service-tool result out of the conversation without losing it.

A service tool (a file read, a shell command, an email search) can return more than the model should carry. The whole result is saved in the task workspace and replaced by a preview, an outline, and a result_id for the stored_result tool. Only when it cannot be saved, because there is no task chain or the write fails, is it clipped to a preview and the rest discarded.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from .spill import spill_result

logger = logging.getLogger(__name__)

MAX_PREVIEW_CHARS = 6_000
MIN_PREVIEW_CHARS = 500
CLIP_ENVELOPE_RESERVE_CHARS = 1_500
_OUTLINE_LISTS = ("largest", "largest_items")


@dataclass(frozen=True)
class CappedServiceOutput:
    """The text to hand the model, and whether the whole result was saved so the agent can still read all of it."""

    text: str
    stored: bool
    result_id: Optional[str] = None


def _trimmed_outline(outline: Any, entries: Optional[int]) -> Any:
    if not isinstance(outline, dict) or entries is None:
        return outline
    trimmed = dict(outline)
    for key in _OUTLINE_LISTS:
        if isinstance(trimmed.get(key), list):
            trimmed[key] = trimmed[key][:entries]
    return trimmed


def _stored_envelope(
    output: str,
    stored: Dict[str, Any],
    *,
    limit: int,
    context_tokens: int,
    preview_chars: int,
    outline_entries: Optional[int],
    published_fields: Dict[str, Any],
) -> str:
    result_id = stored["result_id"]
    file_name = stored.get("file")
    where = (
        f" It is also a file named {file_name} in this task's workspace folder, which shell commands such as grep and head can read."
        " To pick fields out of a JSON file, use jq if `command -v jq` finds it, because a Python script for the same job would ask the user for approval."
    ) if file_name else ""
    envelope: Dict[str, Any] = {
        "stored": True,
        "result_id": result_id,
        "original_size_chars": len(output),
        "original_size_bytes": len(output.encode("utf-8")),
        "limit_chars": limit,
        "context_limit_tokens": context_tokens,
        "message": (
            f"This tool returned {len(output):,} characters, more than fits in this conversation (the limit is {limit:,} characters for this model), "
            f"so the whole result was saved as {result_id} and only a short preview is shown. "
            "Use the stored_result tool with this result_id instead of calling the tool again for the same data: action outline (with an optional path) shows what is inside and how big each part is, "
            "read returns one part, and search finds a word or value."
            f"{where}"
        ),
        "outline": _trimmed_outline(stored.get("outline"), outline_entries),
    }
    if file_name:
        envelope["file"] = file_name
    preview = output[:preview_chars]
    if preview:
        envelope["preview_chars"] = len(preview)
        envelope["preview"] = preview
    envelope.update(published_fields)
    return json.dumps(envelope, ensure_ascii=False)


def _clipped_envelope(output: str, limit: int, context_tokens: int, published_fields: Dict[str, Any]) -> str:
    preview_size = limit - CLIP_ENVELOPE_RESERVE_CHARS
    clipped_info = {
        "truncated": True,
        "original_size_chars": len(output),
        "original_size_bytes": len(output.encode("utf-8")),
        "truncated_to_chars": limit,
        "context_limit_tokens": context_tokens,
        "message": (
            f"Tool output truncated from {len(output):,} chars to {limit:,} chars "
            f"to fit context window ({context_tokens:,} tokens). "
            f"The full content was too large to include in agent memory."
        ),
        "content_preview": output[:preview_size] + "\n\n...[CONTENT TRUNCATED]...",
        **published_fields,
    }
    return json.dumps(clipped_info, ensure_ascii=False)


def cap_service_tool_output(
    output: str,
    limit: int,
    *,
    context_tokens: int,
    published_fields: Optional[Dict[str, Any]] = None,
    spill: Callable[[str], Optional[Dict[str, Any]]] = spill_result,
) -> CappedServiceOutput:
    """Return `output` unchanged when it fits in `limit` characters, a stored-result envelope when the whole result could be saved, and otherwise the clipped preview."""
    if len(output) <= limit:
        return CappedServiceOutput(text=output, stored=False)
    fields = published_fields or {}
    try:
        stored = spill(output)
    except Exception as exc:
        logger.warning("Could not save an oversized tool result: %s", exc)
        stored = None
    if stored:
        preview = max(MIN_PREVIEW_CHARS, min(MAX_PREVIEW_CHARS, limit // 10))
        # Each step down gives up some preview and some of the outline, so a small window still gets the id and a pointer to the file
        for preview_chars, outline_entries in ((preview, None), (preview // 3, 8), (0, 4)):
            envelope = _stored_envelope(
                output,
                stored,
                limit=limit,
                context_tokens=context_tokens,
                preview_chars=preview_chars,
                outline_entries=outline_entries,
                published_fields=fields,
            )
            if len(envelope) <= limit:
                return CappedServiceOutput(text=envelope, stored=True, result_id=stored["result_id"])
    return CappedServiceOutput(text=_clipped_envelope(output, limit, context_tokens, fields), stored=False)
