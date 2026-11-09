"""Agent tool for reading a tool result that was too large to place in the conversation."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile

from .stored_result.shape import PathError, outline_text, select_node
from .stored_result.store import load_result

logger = logging.getLogger(__name__)

TOOL_NAME = "stored_result"
DEFAULT_READ_CHARS = 8_000
MIN_READ_CHARS = 500
MAX_READ_CHARS = 20_000
DEFAULT_MATCHES = 8
MAX_MATCHES = 20
DEFAULT_CONTEXT_CHARS = 150
MAX_CONTEXT_CHARS = 500

SLIM_DESCRIPTION = (
    "Read a tool result that was too large for the conversation and was saved; its result_id was given with a preview and an outline. Use this instead of calling the connector again for the same data. "
    "Actions (all need result_id): outline (what is inside and how big each part is; path looks inside one part, such as request.investigation.steps), "
    "read (one part's text; path, offset, max_chars up to 20000), search (find a word or value; query). "
    "Paths use dots for keys and [n] for array items. The same data is also a file in the task workspace that shell commands can read."
)

_FULL_DESCRIPTION = """Read a tool result that was too large for the conversation. When a connector or tool returns more than fits, Basil saves the whole result and gives you a result_id, a short preview, and an outline of what is inside. Use this tool instead of calling the connector again for the same data.

Every action needs result_id. A path names one part of the result: keys separated by dots, and [n] for an array item, such as request.investigation.steps[3].command. Leave path out to use the whole result.

Actions:
- outline: what is inside and how big each part is. Pass path to look inside one part, such as request.investigation.steps.
- read: the text of one part. Pass path and, to continue a long part, offset. At most max_chars (default 8000, up to 20000) come back, with has_more and next_offset.
- search: find a word or value. Pass query, and path to search inside one part. Returns the offset of each match with surrounding text; read the same path from that offset to see more.

The same data is also saved as a file in the task workspace (the stored envelope names it), which shell commands such as grep and head can read when the shell tools are loaded. Saved results are kept for 14 days and can be read only from the task they came from."""


class StoredResultInput(BaseModel):
    """Input schema for the stored result tool."""

    action: Literal["outline", "read", "search"] = Field(description="outline, read, or search.")
    result_id: str = Field(description="The result_id given with the stored result, such as r-1a2b3c4d.")
    path: Optional[str] = Field(default=None, description="Part of the result to use: keys separated by dots and [n] for array items. Omit for the whole result.")
    offset: Optional[int] = Field(default=None, description="For read: character position to start from. Default 0.")
    max_chars: Optional[int] = Field(default=None, description="For read: characters to return, 500 to 20000. Default 8000.")
    query: Optional[str] = Field(default=None, description="For search: the text to find, case-insensitive.")
    max_matches: Optional[int] = Field(default=None, description="For search: matches to return, 1 to 20. Default 8.")
    context_chars: Optional[int] = Field(default=None, description="For search: characters of context around each match, up to 500. Default 150.")


def _json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _error(message: str) -> str:
    return _json({"ok": False, "error": message})


def _clamp(value: Optional[int], default: int, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        return default
    return max(low, min(high, value))


def _node_text(node: Any) -> str:
    return node if isinstance(node, str) else json.dumps(node, ensure_ascii=False, default=str)


async def _stored_result_impl(
    action: str,
    result_id: str,
    path: Optional[str] = None,
    offset: Optional[int] = None,
    max_chars: Optional[int] = None,
    query: Optional[str] = None,
    max_matches: Optional[int] = None,
    context_chars: Optional[int] = None,
) -> str:
    raw = load_result(result_id)
    if raw is None:
        return _error("No stored result with that result_id exists for this task. It may belong to another task or have expired; call the connector again for the data you need.")
    cleaned_path = (path or "").strip()
    try:
        if action == "outline":
            return _json({"ok": True, "result_id": result_id, "outline": outline_text(raw, cleaned_path)})
        node = select_node(raw, cleaned_path)
        if action == "read":
            text = _node_text(node)
            start = max(0, offset) if isinstance(offset, int) and not isinstance(offset, bool) else 0
            size = _clamp(max_chars, DEFAULT_READ_CHARS, MIN_READ_CHARS, MAX_READ_CHARS)
            piece = text[start:start + size]
            end = start + len(piece)
            return _json(
                {
                    "ok": True,
                    "result_id": result_id,
                    "path": cleaned_path,
                    "offset": start,
                    "returned_chars": len(piece),
                    "total_chars": len(text),
                    "has_more": end < len(text),
                    "next_offset": end if end < len(text) else None,
                    "content": piece,
                }
            )
        if action == "search":
            if not query or not query.strip():
                return _error("search needs a query.")
            text = _node_text(node)
            limit = _clamp(max_matches, DEFAULT_MATCHES, 1, MAX_MATCHES)
            around = _clamp(context_chars, DEFAULT_CONTEXT_CHARS, 0, MAX_CONTEXT_CHARS)
            matches = []
            total = 0
            for match in re.finditer(re.escape(query.strip()), text, re.IGNORECASE):
                total += 1
                if len(matches) < limit:
                    begin = max(0, match.start() - around)
                    finish = min(len(text), match.end() + around)
                    matches.append({"offset": match.start(), "snippet": text[begin:finish]})
            return _json(
                {
                    "ok": True,
                    "result_id": result_id,
                    "path": cleaned_path,
                    "query": query.strip(),
                    "total_matches": total,
                    "returned": len(matches),
                    "matches": matches,
                }
            )
    except PathError as exc:
        return _error(str(exc))
    return _error("Unknown action. Use outline, read, or search.")


def create_stored_result_tool(profile=None) -> StructuredTool:
    """Build the LangChain StructuredTool for reading stored results."""
    return StructuredTool.from_function(
        func=_stored_result_impl,
        name=TOOL_NAME,
        description=select_description_for_profile(profile, _FULL_DESCRIPTION, SLIM_DESCRIPTION),
        args_schema=StoredResultInput,
        coroutine=_stored_result_impl,
    )
