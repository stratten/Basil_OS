"""Stores a local stdio MCP server as a connection, and removes it again if it turns out not to start.

Registration does not launch anything. The caller launches the server through the normal tool refresh right afterwards and calls ``discard_local_server_record`` when that fails, so a command that does not work never stays in Settings → Connections.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable, List, Optional

from api.core.models.preferences import MCPConnectionRecord, MCPStdioSpec

from .local_server_spec import build_local_server_spec
from .stdio_transport import StdioSpecError, stdio_server_url

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


def _find_duplicate(records: Iterable[MCPConnectionRecord], spec: MCPStdioSpec) -> Optional[MCPConnectionRecord]:
    for existing in records:
        stored = existing.stdio
        if stored and (stored.command, stored.args, stored.cwd) == (spec.command, spec.args, spec.cwd):
            return existing
    return None


def find_existing_local_server(spec: MCPStdioSpec) -> Optional[MCPConnectionRecord]:
    """The stored local server that already runs this command, arguments and folder, or None."""
    from api.core.preferences.preferences_io import load_preferences

    return _find_duplicate(load_preferences().connections.mcp_connections, spec)


def register_local_server_record(
    *,
    friendly_name: str,
    command: str,
    args: Optional[List[str]] = None,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    description: Optional[str] = None,
    source_url: Optional[str] = None,
    secret_env: Optional[List[str]] = None,
    companion: Optional[Dict[str, Any]] = None,
    install: Optional[Dict[str, Any]] = None,
    connection_id: Optional[str] = None,
    replace_id: Optional[str] = None,
) -> MCPConnectionRecord:
    """Validate and store one local server. Raises StdioSpecError for a command that cannot run and DuplicateLocalServerError for one already set up.

    ``secret_env``, ``companion`` and ``install`` are described in ``local_server_spec`` and ``local_server_recipe``. ``connection_id`` lets the caller choose the id (a UUID), so secret values can be saved under it before the first launch. ``replace_id`` names an existing local server whose definition is rewritten in place: it keeps its id, its saved secrets and its place in Settings, and loses its cached tool list.
    """
    from api.core.preferences.preferences_io import load_preferences, save_preferences

    name = (friendly_name or "").strip()
    if not name:
        raise StdioSpecError("A local server needs a name.")
    if len(name) > MAX_FRIENDLY_NAME_LENGTH:
        raise StdioSpecError(f"The name is longer than {MAX_FRIENDLY_NAME_LENGTH} characters.")
    spec = build_local_server_spec(
        command=command,
        args=list(args or []),
        cwd=cwd,
        env=dict(env or {}),
        secret_env=secret_env,
        companion=companion,
        install=install,
    )
    # The address is kept exactly as the person gave it, so the connection can say where it came from.
    spec.source_url = _clean_optional(source_url, MAX_SOURCE_URL_LENGTH, "source address")

    preferences = load_preferences()
    replaced = None
    if replace_id is not None:
        replaced = next((record for record in preferences.connections.mcp_connections if record.id == replace_id and record.stdio is not None), None)
        if replaced is None:
            raise StdioSpecError("There is no local server with that connection id to replace.")
    duplicate = _find_duplicate([record for record in preferences.connections.mcp_connections if record is not replaced], spec)
    if duplicate is not None:
        raise DuplicateLocalServerError(f"That server is already set up as '{duplicate.friendly_name}'.")
    if replaced is not None:
        replaced.friendly_name = name
        replaced.description = _clean_optional(description, MAX_DESCRIPTION_LENGTH, "description") or replaced.description
        replaced.stdio = spec
        replaced.cached_tools = []
        replaced.last_connection_status = None
        replaced.last_connection_status_message = None
        save_preferences(preferences)
        return replaced

    identity: Dict[str, Any] = {}
    if connection_id is not None:
        try:
            identity["id"] = str(uuid.UUID(connection_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise StdioSpecError("The connection id is not valid.") from exc
        if any(existing.id == identity["id"] for existing in preferences.connections.mcp_connections):
            raise StdioSpecError("That connection id is already in use.")

    record = MCPConnectionRecord(
        **identity,
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
