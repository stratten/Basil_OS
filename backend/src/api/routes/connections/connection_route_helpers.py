"""Shared helpers for MCP connection routes."""

from __future__ import annotations

from fastapi import HTTPException

from api.core.models.preferences import (
    MCPCachedTool,
    MCPConnectionRecord,
    MCPToolPolicy,
    Preferences,
)

from .models import CachedToolDTO, ConnectionDTO


def load_connection_preferences() -> Preferences:
    """Load preferences through the canonical migration-aware helper."""
    from api.core.preferences.preferences_io import load_preferences as _load

    return _load()


def save_connection_preferences(prefs: Preferences) -> None:
    """Persist preferences through the canonical helper."""
    from api.core.preferences.preferences_io import save_preferences as _save

    _save(prefs)


def find_connection_or_404(
    prefs: Preferences,
    connection_id: str,
) -> MCPConnectionRecord:
    """Return a connection record or raise the route-level 404."""
    for record in prefs.connections.mcp_connections:
        if record.id == connection_id:
            return record
    raise HTTPException(status_code=404, detail="Connection not found")


def default_policy_for_tool(tool: MCPCachedTool) -> MCPToolPolicy:
    """Default read-only tools to auto-allow; ask for mutating/unknown tools."""
    return "always_allow" if tool.is_read_only_hint else "always_ask"


def connection_to_dto(record: MCPConnectionRecord) -> ConnectionDTO:
    """Map one persisted connection record to the Swift-facing DTO."""
    tools = [
        CachedToolDTO(
            name=tool.name,
            description=tool.description,
            is_read_only_hint=tool.is_read_only_hint,
            policy=record.tool_policies.get(tool.name, default_policy_for_tool(tool)),
        )
        for tool in record.cached_tools
    ]
    return ConnectionDTO(
        id=record.id,
        friendly_name=record.friendly_name,
        description=record.description,
        server_url=record.server_url,
        enabled=record.enabled,
        registered_at=record.registered_at,
        last_tool_refresh_at=record.last_tool_refresh_at,
        last_connection_check_at=record.last_connection_check_at,
        last_connection_status=record.last_connection_status,
        last_connection_status_message=record.last_connection_status_message,
        server_name=record.server_name,
        server_instructions=record.server_instructions,
        tools=tools,
    )


__all__ = [
    "connection_to_dto",
    "default_policy_for_tool",
    "find_connection_or_404",
    "load_connection_preferences",
    "save_connection_preferences",
]
