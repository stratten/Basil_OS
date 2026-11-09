"""Outline and navigate a stored JSON result without reading all of it into the conversation."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Union

MAX_OUTLINE_ENTRIES = 40
MAX_LARGEST_ITEMS = 10
MAX_ITEMS_MEASURED = 5_000
MAX_KEY_CHARS = 80
MAX_KEYS_SHOWN_IN_ERROR = 15
_PATH_TOKEN = re.compile(r"\[(\d+)\]|([^.\[\]]+)")

PathPart = Union[str, int]


class PathError(ValueError):
    """The requested path cannot be read from the stored result."""


def parse_path(path: Optional[str]) -> List[PathPart]:
    """Split a path such as request.investigation.steps[3].command into keys and array positions."""
    text = (path or "").strip()
    parts: List[PathPart] = []
    index = 0
    while index < len(text):
        if text[index] == ".":
            index += 1
            continue
        match = _PATH_TOKEN.match(text, index)
        if match is None or match.end() == index:
            raise PathError(f"Cannot read the path {path!r} at position {index}. Use keys separated by dots and [n] for array items, such as result.items[2].name.")
        parts.append(int(match.group(1)) if match.group(1) is not None else match.group(2))
        index = match.end()
    return parts


def resolve_path(root: Any, parts: List[PathPart]) -> Any:
    """Walk the parsed path from the root and return the value there."""
    node = root
    walked = ""
    for part in parts:
        if isinstance(part, int):
            if not isinstance(node, list):
                raise PathError(f"{walked or 'The top level'} is not an array, so [{part}] cannot be read from it.")
            if part >= len(node):
                raise PathError(f"{walked or 'The top level'} has {len(node)} items, so [{part}] does not exist.")
            node = node[part]
            walked = f"{walked}[{part}]"
            continue
        if isinstance(node, list):
            raise PathError(f"{walked or 'The top level'} is an array of {len(node)} items; use [n] to pick one.")
        if not isinstance(node, dict):
            raise PathError(f"{walked or 'The top level'} is a single value, so it has no key {part!r}.")
        if part not in node:
            available = ", ".join(str(key)[:MAX_KEY_CHARS] for key in list(node.keys())[:MAX_KEYS_SHOWN_IN_ERROR])
            raise PathError(f"{walked or 'The top level'} has no key {part!r}. Keys there: {available}.")
        node = node[part]
        walked = f"{walked}.{part}" if walked else str(part)
    return node


def select_node(raw: str, path: Optional[str]) -> Any:
    """The value at path in a stored result: parsed JSON for a JSON result, or the whole text for a plain-text result."""
    try:
        data = json.loads(raw)
    except ValueError:
        if (path or "").strip():
            raise PathError("This stored result is plain text, so it has no paths.")
        return raw
    return resolve_path(data, parse_path(path))


def _chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def _kind(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if value is None:
        return "null"
    return "number"


def describe_node(node: Any) -> Dict[str, Any]:
    """A small description of a value: its type, size, and the largest parts inside it."""
    if isinstance(node, dict):
        entries = []
        for key, value in node.items():
            entry: Dict[str, Any] = {"key": str(key)[:MAX_KEY_CHARS], "type": _kind(value), "chars": _chars(value)}
            if isinstance(value, (list, dict)):
                entry["length"] = len(value)
            entries.append(entry)
        entries.sort(key=lambda entry: entry["chars"], reverse=True)
        outline: Dict[str, Any] = {"type": "object", "keys": len(node), "total_chars": _chars(node), "largest": entries[:MAX_OUTLINE_ENTRIES]}
        if len(entries) > MAX_OUTLINE_ENTRIES:
            outline["omitted_keys"] = len(entries) - MAX_OUTLINE_ENTRIES
        return outline
    if isinstance(node, list):
        measured = [(position, _chars(item)) for position, item in enumerate(node[:MAX_ITEMS_MEASURED])]
        measured.sort(key=lambda pair: pair[1], reverse=True)
        outline = {
            "type": "array",
            "length": len(node),
            "total_chars": _chars(node),
            "item_types": sorted({_kind(item) for item in node[:MAX_ITEMS_MEASURED]}),
            "largest_items": [{"index": position, "chars": size} for position, size in measured[:MAX_LARGEST_ITEMS]],
        }
        if node and isinstance(node[0], dict):
            outline["first_item_keys"] = [str(key)[:MAX_KEY_CHARS] for key in list(node[0].keys())[:20]]
        if len(node) > MAX_ITEMS_MEASURED:
            outline["sized_first"] = MAX_ITEMS_MEASURED
        return outline
    if isinstance(node, str):
        return {"type": "string", "chars": len(node), "lines": node.count("\n") + 1}
    return {"type": _kind(node), "value": node}


def outline_text(raw: str, path: Optional[str] = None) -> Dict[str, Any]:
    """Describe the value at path (or the whole result) of a stored result."""
    node = select_node(raw, path)
    outline = describe_node(node)
    outline["path"] = (path or "").strip()
    return outline
