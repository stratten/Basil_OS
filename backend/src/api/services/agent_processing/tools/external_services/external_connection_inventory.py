"""Compact, secret-free external connection inventory for agent routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from .external_connection_capability import (
    connection_routing_label,
    render_connection_capability_block,
)


DEFAULT_TOOL_NAME_LIMIT = 12


@dataclass(frozen=True)
class ExternalConnectionInventoryItem:
    """Safe metadata about one enabled external MCP connection."""

    connection_id: str
    friendly_name: str
    server_url: str
    cached_tool_count: int
    description: Optional[str] = None
    cached_tool_names: tuple[str, ...] = ()
    server_name: Optional[str] = None
    server_instructions: Optional[str] = None
    cached_tool_briefs: tuple[tuple[str, Optional[str]], ...] = ()
    cached_action_tool_names: tuple[str, ...] = ()


def _load_preferences():
    from api.core.models.preferences import Preferences

    return Preferences.load()


def _tool_name(tool: Any) -> Optional[str]:
    if isinstance(tool, dict):
        name = tool.get("name")
    else:
        name = getattr(tool, "name", None)
    return str(name) if name else None


def _tool_description(tool: Any) -> Optional[str]:
    if isinstance(tool, dict):
        description = tool.get("description")
    else:
        description = getattr(tool, "description", None)
    if isinstance(description, str) and description.strip():
        return description.strip()
    return None


def _tool_is_read_only(tool: Any) -> bool:
    """Return the server-declared read-only hint for a cached tool.

    Duck-typed like ``_tool_name``/``_tool_description`` so this works for both
    the persisted ``MCPCachedTool`` records and plain dict payloads. A missing
    or falsey hint is treated as "not read-only" (i.e. an action tool), matching
    the conservative default the approval policy already applies.
    """
    if isinstance(tool, dict):
        return bool(tool.get("is_read_only_hint"))
    return bool(getattr(tool, "is_read_only_hint", False))


def get_enabled_external_connections(
    *,
    preferences: Any = None,
    max_tool_names: int = DEFAULT_TOOL_NAME_LIMIT,
) -> list[ExternalConnectionInventoryItem]:
    """Return enabled MCP connections without reading tokens or Keychain state."""
    prefs = preferences if preferences is not None else _load_preferences()
    records = getattr(getattr(prefs, "connections", None), "mcp_connections", []) or []
    items: list[ExternalConnectionInventoryItem] = []

    for record in records:
        if not getattr(record, "enabled", False):
            continue
        cached_tools = list(getattr(record, "cached_tools", []) or [])
        bounded_tools = cached_tools[: max(0, max_tool_names)]
        tool_names = tuple(
            name for name in (_tool_name(tool) for tool in bounded_tools) if name
        )
        tool_briefs = tuple(
            (name, _tool_description(tool))
            for tool, name in (
                (tool, _tool_name(tool)) for tool in bounded_tools
            )
            if name
        )
        # Action (write-capable) tool names are derived from the FULL cached
        # tool list, not the name-bounded slice, so an action tool that sorts
        # past ``max_tool_names`` still surfaces in the capability block's
        # actions line. Read-only hint is the same signal the approval policy
        # trusts, so no new source of truth is introduced.
        action_tool_names = tuple(
            name
            for name, is_read_only in (
                (_tool_name(tool), _tool_is_read_only(tool)) for tool in cached_tools
            )
            if name and not is_read_only
        )
        server_name = getattr(record, "server_name", None)
        server_instructions = getattr(record, "server_instructions", None)
        description = getattr(record, "description", None)
        items.append(
            ExternalConnectionInventoryItem(
                connection_id=str(getattr(record, "id", "") or ""),
                friendly_name=str(getattr(record, "friendly_name", "") or "Unnamed connection"),
                description=(
                    str(description).strip()
                    if isinstance(description, str) and description.strip()
                    else None
                ),
                server_url=str(getattr(record, "server_url", "") or ""),
                cached_tool_count=len(cached_tools),
                cached_tool_names=tool_names,
                server_name=str(server_name).strip() if isinstance(server_name, str) and server_name.strip() else None,
                server_instructions=(
                    str(server_instructions).strip()
                    if isinstance(server_instructions, str) and server_instructions.strip()
                    else None
                ),
                cached_tool_briefs=tool_briefs,
                cached_action_tool_names=action_tool_names,
            )
        )

    return items


def enabled_connection_names(*, preferences: Any = None) -> list[str]:
    """Return enabled connection display names for first-pass routing hints."""
    return [item.friendly_name for item in get_enabled_external_connections(preferences=preferences, max_tool_names=0)]


def enabled_connection_routing_labels(*, preferences: Any = None) -> list[str]:
    """Return first-pass routing labels that include the served system.

    Each label is ``"{friendly_name} ({server_name})"`` when the captured MCP
    server name adds signal beyond the user-chosen friendly name, else just the
    friendly name. Used by family-level routing so selecting the ``external``
    family for a task like "update Salesforce" is no longer blind to which
    connection serves that system.
    """
    return [
        connection_routing_label(item)
        for item in get_enabled_external_connections(preferences=preferences, max_tool_names=0)
    ]


def render_connection_names_for_routing(*, preferences: Any = None) -> str:
    """Render a compact one-line connection list for family-routing metadata."""
    names = enabled_connection_names(preferences=preferences)
    if not names:
        return "No enabled external connections are currently registered."
    return ", ".join(names)


def render_connection_inventory_for_description(
    *,
    preferences: Any = None,
    max_tool_names: int = DEFAULT_TOOL_NAME_LIMIT,
) -> str:
    """Render the external_catalog CURRENT CONNECTIONS block."""
    items = get_enabled_external_connections(
        preferences=preferences,
        max_tool_names=max_tool_names,
    )
    if not items:
        return "**CURRENT CONNECTIONS:** No enabled external connections are currently registered."

    lines = ["**CURRENT CONNECTIONS:**"]
    for item in items:
        lines.append(render_connection_capability_block(item))
    return "\n".join(lines)


def inventory_as_dicts(items: Iterable[ExternalConnectionInventoryItem]) -> list[dict[str, Any]]:
    """Return JSON-safe inventory records for tests and diagnostics."""
    return [
        {
            "connection_id": item.connection_id,
            "friendly_name": item.friendly_name,
            "description": item.description,
            "server_url": item.server_url,
            "cached_tool_count": item.cached_tool_count,
            "cached_tool_names": list(item.cached_tool_names),
        }
        for item in items
    ]
