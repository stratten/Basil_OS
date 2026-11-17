"""Stores a local stdio MCP server as a connection, and removes it again if it turns out not to start.

Registration does not launch anything. The caller launches the server through the normal tool refresh right afterwards and calls ``discard_local_server_record`` when that fails, so a command that does not work never stays in Settings → Connections.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from api.core.models.preferences import MCPConnectionRecord

from .stdio_transport import StdioSpecError, stdio_server_url, validate_spec_fields

MAX_FRIENDLY_NAME_LENGTH = 80
MAX_DESCRIPTION_LENGTH = 500
MAX_SOURCE_URL_LENGTH = 500


class DuplicateLocalServerError(ValueError):
    """The same command, arguments and folder are already set up as a connection."""


def _clean_optional(value: Optional[str], limit: int, label: str) -> Optional[str]:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > limit:
        raise StdioSpecError(f"The {label} is longer than {limit} characters.")
    return cleaned


def register_local_server_record(
    *,
    friendly_name: str,
    command: str,
    args: Optional[List[str]] = None,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    description: Optional[str] = None,
    source_url: Optional[str] = None,
) -> MCPConnectionRecord:
    """Validate and store one local server. Raises StdioSpecError for a command that cannot run and DuplicateLocalServerError for one already set up."""
    from api.core.preferences.preferences_io import load_preferences, save_preferences

    name = (friendly_name or "").strip()
    if not name:
        raise StdioSpecError("A local server needs a name.")
    if len(name) > MAX_FRIENDLY_NAME_LENGTH:
        raise StdioSpecError(f"The name is longer than {MAX_FRIENDLY_NAME_LENGTH} characters.")
    spec = validate_spec_fields(command, list(args or []), cwd, dict(env or {}))
    # The address is kept exactly as the person gave it, so the connection can say where it came from.
    spec.source_url = _clean_optional(source_url, MAX_SOURCE_URL_LENGTH, "source address")

    preferences = load_preferences()
    for existing in preferences.connections.mcp_connections:
        stored = existing.stdio
        if stored and (stored.command, stored.args, stored.cwd) == (spec.command, spec.args, spec.cwd):
            raise DuplicateLocalServerError(f"That server is already set up as '{existing.friendly_name}'.")

    record = MCPConnectionRecord(
        friendly_name=name,
        description=_clean_optional(description, MAX_DESCRIPTION_LENGTH, "description"),
        server_url="basil-stdio://pending",
        stdio=spec,
    )
    record.server_url = stdio_server_url(record.id)
    preferences.connections.mcp_connections.append(record)
    save_preferences(preferences)
    return record


def discard_local_server_record(connection_id: str) -> None:
    """Remove a local server record that was just registered, for a server that did not start. Does nothing when it is already gone."""
    from api.core.preferences.preferences_io import load_preferences, save_preferences

    preferences = load_preferences()
    kept = [record for record in preferences.connections.mcp_connections if not (record.id == connection_id and record.stdio is not None)]
    if len(kept) != len(preferences.connections.mcp_connections):
        preferences.connections.mcp_connections = kept
        save_preferences(preferences)
