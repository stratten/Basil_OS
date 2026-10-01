"""Helpers for re-authorizing an existing MCP connection in place.

Reconnect keeps the connection id, so tool policies, cached tools, descriptions and audit history survive a fresh sign-in. Tokens still travel only to the Swift client over the WebSocket bridge; this module touches metadata only.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import HTTPException

from api.core.models.preferences import MCPConnectionRecord

from .connection_route_helpers import (
    connection_auth_kind,
    find_connection_or_404,
    load_connection_preferences,
    save_connection_preferences,
)
from .models import ConnectionAuthKind


def load_reconnect_target(
    connection_id: str,
    expected_kind: ConnectionAuthKind,
) -> MCPConnectionRecord:
    """Return the connection to re-authorize, or raise 404/400 route errors."""
    prefs = load_connection_preferences()
    record = find_connection_or_404(prefs, connection_id)
    actual_kind = connection_auth_kind(record)
    if actual_kind != expected_kind:
        raise HTTPException(
            status_code=400,
            detail=f"This connection uses {actual_kind} sign-in, not {expected_kind}.",
        )
    return record


def reauthorize_connection(
    connection_id: str,
    *,
    oauth_client_id: Optional[str],
    oauth_authorization_server: Optional[str],
    oauth_token_endpoint: Optional[str],
    oauth_scopes: List[str],
) -> Optional[MCPConnectionRecord]:
    """Overwrite the OAuth metadata of an existing connection after a fresh sign-in.

    Returns ``None`` when the connection was removed while sign-in was in progress. The status fields are cleared because the next successful tool refresh records the verified state.
    """
    prefs = load_connection_preferences()
    for record in prefs.connections.mcp_connections:
        if record.id != connection_id:
            continue
        record.oauth_client_id = oauth_client_id
        record.oauth_authorization_server = oauth_authorization_server
        record.oauth_token_endpoint = oauth_token_endpoint
        record.oauth_scopes = list(oauth_scopes)
        record.last_connection_check_at = None
        record.last_connection_status = None
        record.last_connection_status_message = None
        save_connection_preferences(prefs)
        return record
    return None


__all__ = [
    "load_reconnect_target",
    "reauthorize_connection",
]
