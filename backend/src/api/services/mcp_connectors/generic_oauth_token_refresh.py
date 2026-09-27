"""Shared generic-OAuth (non-Slack) access-token refresh for MCP connections.

Both the Settings "check connection status" flow (``connection_status_service.py``)
and the ``external_catalog`` dispatch layer need to recover from a merely-stale access token by exchanging the connection's stored refresh token, rather than surfacing ``auth_expired`` and forcing a full user reconnect for something a silent token-endpoint round-trip would fix. This is the single implementation of that exchange so every caller stays in lockstep instead of maintaining separate copies that could drift.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from api.core.models.preferences import MCPConnectionRecord
from api.services.mcp_connectors.oauth_coordinator import OAuthCoordinator
from api.services.mcp_connectors.swift_token_bridge import (
    _push_token_to_swift,
    _request_token_bundle_from_swift,
)

logger = logging.getLogger(__name__)


async def refresh_generic_oauth_access_token(
    record: MCPConnectionRecord,
    *,
    oauth_coordinator: Optional[OAuthCoordinator] = None,
    agent_task_id: Optional[str] = None,
    cancel_event: Optional[Any] = None,
) -> Optional[str]:
    """Exchange this connection's stored refresh token for a new access token.

    Safe to call unconditionally, mirroring ``refresh_slack_token``'s contract:
    a Slack connection is detected via the shared ``is_slack_connection``
    predicate and always returns ``None`` here, since Slack's rotating-token
    dance runs through ``SlackPKCECoordinator``/``refresh_slack_token`` instead
    - Slack connections also populate ``oauth_client_id``/``oauth_token_endpoint``,
    so field presence alone cannot be used to distinguish the two.

    Returns the new access token on success. Returns ``None`` when refresh is
    not possible or did not succeed - Slack connection, no token endpoint/
    client_id recorded, no refresh token available in Keychain, or the
    exchange itself failed - in which case the caller should fall back to
    surfacing the original auth error rather than retrying with nothing new
    to try.
    """
    from api.services.mcp_connectors.slack_token_service import is_slack_connection

    if is_slack_connection(record):
        return None
    if not record.oauth_token_endpoint or not record.oauth_client_id:
        return None

    bundle = await _request_token_bundle_from_swift(
        record.id,
        agent_task_id=agent_task_id,
        cancel_event=cancel_event,
    )
    if not bundle.refresh_token:
        return None

    coordinator = oauth_coordinator or OAuthCoordinator()
    try:
        token = await coordinator.refresh(
            token_endpoint=record.oauth_token_endpoint,
            client_id=record.oauth_client_id,
            refresh_token=bundle.refresh_token,
        )
    except Exception:
        logger.exception("Generic MCP token refresh failed for %s", record.id)
        return None

    await _push_token_to_swift(
        connection_id=record.id,
        access_token=token.access_token,
        refresh_token=token.refresh_token or bundle.refresh_token,
        expires_in=token.expires_in,
    )
    return token.access_token


__all__ = ["refresh_generic_oauth_access_token"]
