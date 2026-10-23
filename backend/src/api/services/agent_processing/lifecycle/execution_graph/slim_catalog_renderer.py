"""
Plan B.3 - Slim text-catalog renderer for the LlamaCpp adapter.

When the active ``RuntimeModelProfile.tool_rendering`` is
``slim_text_catalog``, the adapter omits the OpenAI ``tools=`` kwarg and
instead injects a synthetic ``SystemMessage`` preamble that describes the
available tools to the model in a flat text catalog. This lives outside
the function-calling protocol entirely; the model is expected to emit
plain JSON tool calls in its content text, which the adapter parses
before yielding the final ``AIMessage``.

This module is a *renderer only*. It does not mutate tools; it only
reads ``tool.description`` (already slim by Plan B.1.5) and a
mechanically generated signature derived from ``tool.args_schema``.

The catalog format is intentionally compact:

  Available tools (call as: <tool_calls>[{"name": "...", "arguments": {...}}]</tool_calls>):
  - <tool_name>(<arg>: <type>, <arg>: <type>, ...): <slim description>
  - ...

Field types are rendered using JSON-Schema primitives (``string``,
``integer``, ``number``, ``boolean``, ``array``, ``object``). Required
arguments come first; optional ones are suffixed with ``?`` and a
default value when the schema declares one.

This rendering is bytes-cheaper than a full OpenAI tool-array because it
drops field descriptions, ``$ref`` chains, ``additionalProperties``
metadata, and the per-tool ``parameters`` envelope. The tool's purpose
text is the slim description verbatim - no further compression here.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Marker tokens the adapter watches for when parsing the model's reply
# under slim_text_catalog mode. They are intentionally distinct from
# OpenAI's native tool-call envelope so a model that drifts back to
# OpenAI-style tool calls is still detected by the adapter's existing
# JSON parsers.
SLIM_CATALOG_OPEN_TAG = "<tool_calls>"
SLIM_CATALOG_CLOSE_TAG = "</tool_calls>"


def _resolve_property_type(prop_schema: Dict[str, Any]) -> str:
    """Render a single JSON-schema property to a compact type tag.

    Handles the common shapes the agent's tools emit:
    - ``{"type": "string"}`` and the other JSON-Schema primitives
    - ``{"enum": [...]}`` (Literal[...])
    - ``{"anyOf": [{"type": "string"}, {"type": "null"}]}`` (Optional[...])
    - ``{"$ref": "..."}`` (rendered as ``object`` since the catalog is flat)
    """
    enum_values = prop_schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        rendered = "|".join(str(v) for v in enum_values)
        return rendered

    any_of = prop_schema.get("anyOf")
    if isinstance(any_of, list) and any_of:
        non_null = [
            entry for entry in any_of
            if isinstance(entry, dict) and entry.get("type") != "null"
        ]
        if len(non_null) == 1:
            return _resolve_property_type(non_null[0])
        if non_null:
            rendered_parts = [_resolve_property_type(entry) for entry in non_null]
            return "|".join(rendered_parts)

    primitive = prop_schema.get("type")
    if isinstance(primitive, list):
        non_null = [t for t in primitive if t != "null"]
        if non_null:
            return non_null[0]
    if isinstance(primitive, str) and primitive:
        return primitive

    if "$ref" in prop_schema:
        return "object"

    return "any"


def _render_tool_signature(tool: Any) -> str:
    """Build ``tool_name(arg: type, arg?: type=default, ...)`` from args_schema.

    Returns just the parenthesized arg list, with the tool name prefixed.
    Falls back to ``tool_name(...)`` if the schema cannot be resolved.
    """
    name = getattr(tool, "name", None) or "tool"
    schema_obj = getattr(tool, "args_schema", None)
    if schema_obj is None:
        return f"{name}(...)"

    try:
        schema = schema_obj.model_json_schema()
    except Exception as exc:
        logger.debug(f"slim_catalog_renderer: schema extraction failed for {name}: {exc}")
        return f"{name}(...)"

    properties = schema.get("properties") or {}
    required: List[str] = list(schema.get("required") or [])
    required_set = set(required)

    parts: List[str] = []
    # Required first, in declaration order from the schema.
    for prop_name in properties:
        if prop_name not in required_set:
            continue
        prop_schema = properties[prop_name] or {}
        parts.append(f"{prop_name}: {_resolve_property_type(prop_schema)}")

    for prop_name, prop_schema in properties.items():
        if prop_name in required_set:
            continue
        prop_schema = prop_schema or {}
        type_tag = _resolve_property_type(prop_schema)
        if "default" in prop_schema and prop_schema["default"] is not None:
            try:
                default_repr = json.dumps(prop_schema["default"], ensure_ascii=False)
            except (TypeError, ValueError):
                default_repr = repr(prop_schema["default"])
            parts.append(f"{prop_name}?: {type_tag}={default_repr}")
        else:
            parts.append(f"{prop_name}?: {type_tag}")

    return f"{name}({', '.join(parts)})"


def render_slim_catalog_preamble(
    tools: Iterable[Any],
    *,
    extra_invariants: Optional[List[str]] = None,
) -> str:
    """Render the synthetic system-message preamble for slim_text_catalog mode.

    Args:
        tools: The bound tools, as ``BaseTool`` (or duck-typed equivalents
            with ``.name``, ``.description``, and ``.args_schema``).
        extra_invariants: Optional extra invariants to include verbatim
            below the catalog (e.g. "every assistant turn must end with
            either a tool call or a final answer").

    Returns:
        The preamble text, ready to be inserted at the head of the
        conversation as a ``SystemMessage``. Empty string when ``tools``
        is empty.
    """
    rendered_lines: List[str] = []
    rendered_count = 0
    for tool in tools or []:
        signature = _render_tool_signature(tool)
        purpose = (getattr(tool, "description", "") or "").strip()
        # Catalog purpose is the slim description verbatim. We strip
        # surrounding whitespace only to keep the catalog single-line per
        # tool; line breaks inside the description survive but are rare
        # in slim companions (Plan B.1.5 authoring rule #1: single line).
        rendered_lines.append(f"- {signature}: {purpose}")
        rendered_count += 1

    if rendered_count == 0:
        return ""

    invariants = list(extra_invariants or [])
    invariant_block = ""
    if invariants:
        invariant_block = "\n\nInvariants:\n" + "\n".join(f"- {inv}" for inv in invariants)

    preamble = (
        "Available tools "
        f"(call as: {SLIM_CATALOG_OPEN_TAG}"
        '[{"name": "...", "arguments": {...}}]'
        f"{SLIM_CATALOG_CLOSE_TAG}):\n"
        + "\n".join(rendered_lines)
        + invariant_block
    )
    return preamble


def parse_slim_catalog_tool_calls(content: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Parse a model reply for slim_text_catalog tool calls.

    Looks for a ``<tool_calls>...</tool_calls>`` block whose body is a
    JSON array of ``{"name": "...", "arguments": {...}}`` objects. If
    found, returns ``(content_without_block, list_of_calls)``. If not
    found or unparseable, returns ``(content, [])`` and the adapter
    treats the reply as plain text.
    """
    if not content:
        return content, []
    open_idx = content.find(SLIM_CATALOG_OPEN_TAG)
    if open_idx < 0:
        return content, []
    close_idx = content.find(SLIM_CATALOG_CLOSE_TAG, open_idx)
    if close_idx < 0:
        return content, []

    body_start = open_idx + len(SLIM_CATALOG_OPEN_TAG)
    body = content[body_start:close_idx].strip()
    after = content[close_idx + len(SLIM_CATALOG_CLOSE_TAG):]
    cleaned = (content[:open_idx] + after).strip()

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.warning(
            f"slim_catalog_renderer: tool_calls block was not valid JSON: {exc}; "
            "passing through as plain text."
        )
        return content, []

    calls: List[Dict[str, Any]] = []
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return content, []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("tool")
        args = entry.get("arguments") or entry.get("args") or {}
        if not name:
            continue
        if not isinstance(args, dict):
            continue
        calls.append({"name": str(name), "arguments": args})

    if not calls:
        return content, []
    return cleaned, calls
