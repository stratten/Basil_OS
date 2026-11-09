"""Shared rendering + capture helpers for external MCP connection capability.

This module isolates the "what system does this connection serve, and what can
it do" concern so both routing surfaces stay thin:

* The meeting-analysis planner's capability digest and the agent task runner's
  ``external_catalog`` tool description both render connections through
  :func:`render_connection_capability_block`.
* First-pass family routing labels connections via
  :func:`connection_routing_label`.
* Connection registration/refresh captures the MCP server's self-description
  via :func:`apply_server_metadata_to_record`.

All functions are secret-free: they only read display-safe fields
(``friendly_name``, ``server_name``, ``server_instructions``, cached tool
names/descriptions) and never touch tokens. Inputs are duck-typed so this
module never imports the inventory or preference models at runtime (avoids an
import cycle); only static type checkers see the concrete shapes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from api.core.models.preference_models.execution_and_connections import (
        MCPConnectionRecord,
    )
    from .external_connection_inventory import ExternalConnectionInventoryItem


# Deterministic bounds so a connection with long instructions or many verbose
# tool descriptions cannot crowd out the user's actual request in any prompt.
MAX_TOOLS_IN_BLOCK = 8
MAX_TOOL_DESC_CHARS = 120
MAX_USER_DESCRIPTION_CHARS = 240
MAX_INSTRUCTIONS_CHARS = 240
MAX_ACTIONS_IN_BLOCK = 8


def _truncate(text: str, limit: int) -> str:
    """Return ``text`` clipped to ``limit`` chars with an ellipsis when clipped."""
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "…"


def _server_name_is_informative(friendly_name: str, server_name: Optional[str]) -> bool:
    """True when ``server_name`` adds signal beyond the user-chosen friendly name."""
    if not server_name:
        return False
    normalized = server_name.strip()
    if not normalized:
        return False
    return normalized.lower() != (friendly_name or "").strip().lower()


def apply_server_metadata_to_record(
    record: "MCPConnectionRecord", server: Optional[dict]
) -> bool:
    """Copy secret-free server self-description onto a connection record.

    ``server`` is the ``server`` block from an ``MCPClientService.list_tools``
    envelope (``{"name", "version", "protocol", "instructions"}``). Returns
    ``True`` when ``record`` was mutated so the caller can decide whether to
    persist. Defensive against ``None`` / missing keys / non-string values.
    """
    if not isinstance(server, dict):
        return False

    changed = False

    name = server.get("name")
    if isinstance(name, str) and name.strip() and record.server_name != name.strip():
        record.server_name = name.strip()
        changed = True

    instructions = server.get("instructions")
    if (
        isinstance(instructions, str)
        and instructions.strip()
        and record.server_instructions != instructions.strip()
    ):
        record.server_instructions = instructions.strip()
        changed = True

    return changed


def connection_routing_label(item: "ExternalConnectionInventoryItem") -> str:
    """Return a first-pass routing label that includes the served system.

    ``"{friendly_name} ({server_name})"`` when the server name adds signal,
    otherwise just ``friendly_name``. Keeps friendly names that already match
    the server name from rendering as redundant ``Foo (Foo)``.
    """
    friendly_name = getattr(item, "friendly_name", "") or "Unnamed connection"
    server_name = getattr(item, "server_name", None)
    if _server_name_is_informative(friendly_name, server_name):
        return f"{friendly_name} ({server_name.strip()})"
    return friendly_name


def render_connection_capability_block(item: "ExternalConnectionInventoryItem") -> str:
    """Render one connection's enriched, bounded capability block.

    Format (lines after the header are indented two spaces)::

        - <friendly_name> (connection_id=<id>, cached_tools=<n>)
          server: <server_name>
          guidance: <truncated instructions>
          tools: <name: desc>; <name: desc>; … <k> more

    ``server`` / ``guidance`` lines are omitted when absent. The ``tools`` line
    falls back to bare names when descriptions are missing, and to a refresh
    hint when nothing is cached yet, preserving prior behavior.
    """
    friendly_name = getattr(item, "friendly_name", "") or "Unnamed connection"
    connection_id = getattr(item, "connection_id", "") or ""
    cached_tool_count = int(getattr(item, "cached_tool_count", 0) or 0)

    lines = [
        f"- {friendly_name} (connection_id={connection_id}, "
        f"cached_tools={cached_tool_count})"
    ]

    description = getattr(item, "description", None)
    if isinstance(description, str) and description.strip():
        lines.append(f"  description: {_truncate(description, MAX_USER_DESCRIPTION_CHARS)}")

    server_name = getattr(item, "server_name", None)
    if _server_name_is_informative(friendly_name, server_name):
        lines.append(f"  server: {server_name.strip()}")

    instructions = getattr(item, "server_instructions", None)
    if isinstance(instructions, str) and instructions.strip():
        lines.append(f"  guidance: {_truncate(instructions, MAX_INSTRUCTIONS_CHARS)}")

    lines.append(f"  tools: {_render_tools_summary(item, cached_tool_count)}")
    actions_summary = _render_actions_summary(item)
    if actions_summary:
        lines.append(f"  actions: {actions_summary}")
    return "\n".join(lines)


def _render_tools_summary(
    item: "ExternalConnectionInventoryItem", cached_tool_count: int
) -> str:
    """Render up to ``MAX_TOOLS_IN_BLOCK`` tools with truncated descriptions."""
    briefs = list(getattr(item, "cached_tool_briefs", ()) or ())

    if not briefs:
        # Fall back to bare names if briefs were not populated, else the hint.
        names = list(getattr(item, "cached_tool_names", ()) or ())
        if not names:
            return "tool list not cached yet; call describe_server to refresh"
        shown_names = names[:MAX_TOOLS_IN_BLOCK]
        summary = ", ".join(shown_names)
        remaining = cached_tool_count - len(shown_names)
        if remaining > 0:
            summary += f", … {remaining} more"
        return summary

    shown: list[Any] = briefs[:MAX_TOOLS_IN_BLOCK]
    rendered: list[str] = []
    for entry in shown:
        name, description = entry
        if isinstance(description, str) and description.strip():
            rendered.append(f"{name}: {_truncate(description, MAX_TOOL_DESC_CHARS)}")
        else:
            rendered.append(str(name))
    summary = "; ".join(rendered)

    remaining = cached_tool_count - len(shown)
    if remaining > 0:
        summary += f"; … {remaining} more"
    return summary


def _render_actions_summary(item: "ExternalConnectionInventoryItem") -> str:
    """Render up to ``MAX_ACTIONS_IN_BLOCK`` write-capable tool names, or ``''``.

    Action tools are the connection's non-read-only tools (see
    ``ExternalConnectionInventoryItem.cached_action_tool_names``). Surfacing them
    on their own line keeps a connection from reading as passive/lookup-only when
    it can actually perform work. The ``(require approval)`` suffix reflects that
    these default to the user's per-tool approval policy. Returns ``''`` when the
    connection exposes no action tools so the caller omits the line entirely.
    """
    names = list(getattr(item, "cached_action_tool_names", ()) or ())
    if not names:
        return ""
    shown = names[:MAX_ACTIONS_IN_BLOCK]
    summary = ", ".join(shown)
    remaining = len(names) - len(shown)
    if remaining > 0:
        summary += f", … {remaining} more"
    return f"{summary} (require approval)"


def _compact_group_key(item: "ExternalConnectionInventoryItem") -> Optional[tuple]:
    """Return the key under which connections to one server share a body, or ``None`` when sharing would be unsafe.

    Connections with no cached tool names are never grouped, because "same tools" would claim more than is known. The
    key holds everything the shared lines are rendered from (server, instructions, tool names with their descriptions,
    tool count, and action names), so connections share a body only when printing it once loses nothing.
    """
    names = tuple(getattr(item, "cached_tool_names", ()) or ())
    if not names:
        return None
    return (
        getattr(item, "server_name", None),
        getattr(item, "server_url", ""),
        getattr(item, "server_instructions", None),
        int(getattr(item, "cached_tool_count", 0) or 0),
        names,
        tuple(getattr(item, "cached_tool_briefs", ()) or ()),
        tuple(getattr(item, "cached_action_tool_names", ()) or ()),
    )


def _compact_header_lines(item: "ExternalConnectionInventoryItem") -> list[str]:
    """Render the identity lines every connection keeps: name, id, count, and the user's own description."""
    friendly_name = getattr(item, "friendly_name", "") or "Unnamed connection"
    connection_id = getattr(item, "connection_id", "") or ""
    cached_tool_count = int(getattr(item, "cached_tool_count", 0) or 0)
    lines = [f"- {friendly_name} (connection_id={connection_id}, cached_tools={cached_tool_count})"]
    description = getattr(item, "description", None)
    if isinstance(description, str) and description.strip():
        lines.append(f"  description: {_truncate(description, MAX_USER_DESCRIPTION_CHARS)}")
    return lines


def _compact_body_lines(item: "ExternalConnectionInventoryItem") -> list[str]:
    """Render the server, guidance, tools, and action lines that connections to one server share, exactly as the full block does."""
    friendly_name = getattr(item, "friendly_name", "") or "Unnamed connection"
    cached_tool_count = int(getattr(item, "cached_tool_count", 0) or 0)
    lines: list[str] = []
    server_name = getattr(item, "server_name", None)
    if _server_name_is_informative(friendly_name, server_name):
        lines.append(f"  server: {server_name.strip()}")
    instructions = getattr(item, "server_instructions", None)
    if isinstance(instructions, str) and instructions.strip():
        lines.append(f"  guidance: {_truncate(instructions, MAX_INSTRUCTIONS_CHARS)}")
    lines.append(f"  tools: {_render_tools_summary(item, cached_tool_count)}")
    actions_summary = _render_actions_summary(item)
    if actions_summary:
        lines.append(f"  actions: {actions_summary}")
    return lines


def render_compact_connection_blocks(items: list[Any]) -> str:
    """Render every connection's capability block, printing a body once when several connections would repeat it exactly.

    This drops no information. A connection that shares no body with another renders exactly as
    ``render_connection_capability_block`` renders it. Connections that do share one (separate accounts on one server,
    with the same instructions, tools, tool descriptions, and actions) each keep their own identity lines (name,
    connection_id, tool count, the user's description), and the server, guidance, tools, and actions follow once.
    """
    groups: list[list[Any]] = []
    group_index_by_key: dict[tuple, int] = {}
    for item in items:
        key = _compact_group_key(item)
        if key is not None and key in group_index_by_key:
            groups[group_index_by_key[key]].append(item)
            continue
        if key is not None:
            group_index_by_key[key] = len(groups)
        groups.append([item])

    lines: list[str] = []
    for members in groups:
        for member in members:
            lines.extend(_compact_header_lines(member))
        if len(members) > 1:
            lines.append("  (the connections above are separate accounts on one server; the lines below apply to each of them)")
        lines.extend(_compact_body_lines(members[0]))
    return "\n".join(lines)
