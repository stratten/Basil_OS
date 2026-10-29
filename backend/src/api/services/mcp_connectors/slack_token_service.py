"""Slack token refresh orchestration.

Slack PKCE desktop flows issue rotating user tokens with a refresh
token that expires after 30 days. This module wires the moving pieces
together so the rest of the backend can rotate a Slack connection's
tokens without re-implementing the dance:

  1. Look up the persisted ``MCPConnectionRecord`` so we have the
     Slack ``client_id`` for that connection.
  2. Ask Swift for the current access + refresh token bundle over
     the WebSocket bridge (``_request_token_bundle_from_swift``).
  3. Call :class:`SlackPKCECoordinator`'s refresh endpoint with the
     refresh token to mint a new access token (and, when Slack
     returns one, a rotated refresh token).
  4. Push the new tokens back to Swift via ``_push_token_to_swift``
     so Keychain stays the source of truth.

The module owns the refresh choreography only. Detecting when a
refresh is needed (proactively from ``expires_in`` or reactively
from an ``auth_expired`` envelope) is the caller's responsibility.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from api.core.models.preferences import MCPConnectionRecord, Preferences
from api.services.mcp_connectors.slack_local_server import (
    LOCAL_SLACK_SENTINEL_URL,
)
from api.services.mcp_connectors.slack_pkce_coordinator import (
    SLACK_MCP_SERVER_URL,
    SlackPKCECoordinator,
    SlackPKCEError,
)
from api.services.mcp_connectors.swift_token_bridge import (
    MCP_TOKEN_REQUEST_TIMEOUT_SECONDS,
    _push_token_to_swift,
    _request_token_bundle_from_swift,
)

logger = logging.getLogger(__name__)


@dataclass
class SlackRefreshOutcome:
    """Result of attempting a Slack PKCE refresh.

    ``kind`` is one of:
      * ``refreshed``        - new access token (and possibly refresh
                                token) was minted and pushed to Swift.
      * ``not_a_slack_connection`` - the connection record does not
                                point at the Slack MCP server.
      * ``missing_refresh_token`` - Swift had no refresh token; the
                                user must reconnect Slack.
      * ``client_unavailable``    - no Swift client is online.
      * ``slack_error``      - Slack rejected the refresh (e.g.
                                ``token_revoked``, ``invalid_grant``).
      * ``error``            - any other failure (HTTP, exception).
    """

    kind: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None
    message: Optional[str] = None
    error_code: Optional[str] = None


@dataclass
class SlackValidationOutcome:
    """Result of validating a Slack access token against Slack Web API."""

    kind: str
    message: Optional[str] = None
    error_code: Optional[str] = None


def _load_preferences() -> Preferences:
    from api.core.preferences.preferences_io import load_preferences as _load
    return _load()


def _find_slack_connection(prefs: Preferences, connection_id: str) -> Optional[MCPConnectionRecord]:
    for record in prefs.connections.mcp_connections:
        if record.id == connection_id:
            return record
    return None


def is_slack_connection(record: MCPConnectionRecord) -> bool:
    """Heuristic: trust the persisted ``server_url`` to identify Slack.

    Two URLs both indicate a Slack connection:

      * ``basil-local://slack`` — the in-process embedded MCP server
        used while Basil's Slack app awaits Marketplace approval. This
        is what new Slack connections persist today.
      * ``https://mcp.slack.com/mcp`` — Slack's hosted MCP server, used
        by any pre-existing connection records and by all connections
        again once Marketplace approval lands and we flip the
        persistence in ``slack_routes._persist_slack_connection``.

    The token refresh path is identical for both URLs because the
    OAuth flow itself is unchanged; only the dispatch destination of
    the resulting access token differs.

    Public (no leading underscore): this is the single canonical
    Slack-connection predicate. Any code that needs to tell a Slack
    MCP connection apart from a generic one - including the generic
    OAuth refresh path, which must never attempt a plain
    ``grant_type=refresh_token`` exchange against Slack's endpoint -
    should import this rather than re-deriving the same two URLs.
    """
    raw = (record.server_url or "").rstrip("/")
    return raw == SLACK_MCP_SERVER_URL.rstrip("/") or raw == LOCAL_SLACK_SENTINEL_URL.rstrip("/")


async def refresh_slack_token(
    *,
    connection_id: str,
    coordinator: SlackPKCECoordinator,
    timeout_s: Optional[float] = MCP_TOKEN_REQUEST_TIMEOUT_SECONDS,
    agent_task_id: Optional[str] = None,
) -> SlackRefreshOutcome:
    """Rotate the Slack tokens for ``connection_id``.

    Safe to call without first checking whether the connection is a
    Slack connection; the function returns ``not_a_slack_connection``
    if the persisted server URL does not match. The caller can then
    fall through to a normal re-consent prompt.
    """
    prefs = _load_preferences()
    record = _find_slack_connection(prefs, connection_id)
    if record is None:
        return SlackRefreshOutcome(
            kind="error",
            message=f"Unknown connection {connection_id}.",
        )
    if not is_slack_connection(record):
        return SlackRefreshOutcome(
            kind="not_a_slack_connection",
            message="This connection is not a Slack MCP connection.",
        )
    client_id = (record.oauth_client_id or "").strip()
    if not client_id:
        return SlackRefreshOutcome(
            kind="error",
            message="Slack connection is missing its client ID. Reconnect Slack to fix this.",
        )

    bundle = await _request_token_bundle_from_swift(
        connection_id=connection_id,
        timeout_s=timeout_s,
        agent_task_id=agent_task_id,
    )
    if bundle.kind == "client_unavailable":
        return SlackRefreshOutcome(
            kind="client_unavailable",
            message=bundle.message,
        )
    if not bundle.refresh_token:
        return SlackRefreshOutcome(
            kind="missing_refresh_token",
            message=(
                bundle.message
                or "Basil does not have a Slack refresh token stored. "
                "Reconnect Slack in Settings -> Connections."
            ),
        )

    try:
        token = await coordinator.refresh(
            client_id=client_id,
            refresh_token=bundle.refresh_token,
        )
    except SlackPKCEError as exc:
        code = str(exc)
        logger.warning("Slack refresh failed for %s: %s", connection_id, code)
        return SlackRefreshOutcome(
            kind="slack_error",
            error_code=code,
            message=f"Slack refused to refresh the token ({code}).",
        )
    except Exception as exc:
        logger.exception("Unexpected Slack refresh failure for %s", connection_id)
        return SlackRefreshOutcome(
            kind="error",
            message=f"Unexpected Slack refresh failure: {exc}",
        )

    await _push_token_to_swift(
        connection_id=connection_id,
        access_token=token.access_token,
        refresh_token=token.refresh_token or bundle.refresh_token,
        expires_in=token.expires_in,
    )
    return SlackRefreshOutcome(
        kind="refreshed",
        access_token=token.access_token,
        refresh_token=token.refresh_token or bundle.refresh_token,
        expires_in=token.expires_in,
    )


async def validate_slack_access_token(
    access_token: str,
    *,
    timeout_s: float = 15.0,
) -> SlackValidationOutcome:
    """Validate a Slack token with ``auth.test``.

    The embedded Slack MCP server advertises a static catalog, so catalog
    refresh alone does not prove Slack will accept the token. ``auth.test`` is
    Slack's cheapest real credential check and has no user-visible side effect.
    """
    if not access_token:
        return SlackValidationOutcome(
            kind="invalid",
            message="Slack access token is missing.",
            error_code="missing_token",
        )

    client = AsyncWebClient(token=access_token, timeout=timeout_s)
    try:
        await client.auth_test()
    except SlackApiError as exc:
        response = getattr(exc, "response", None)
        error_code = ""
        if response is not None:
            try:
                error_code = str((response.data or {}).get("error") or "").strip()
            except Exception:
                error_code = ""
        return SlackValidationOutcome(
            kind="invalid",
            message=f"Slack rejected the token ({error_code or 'unknown_error'}).",
            error_code=error_code or "unknown_error",
        )
    except Exception as exc:
        logger.exception("Unexpected Slack token validation failure")
        return SlackValidationOutcome(
            kind="error",
            message=f"Slack token validation failed: {type(exc).__name__}: {exc}",
        )

    return SlackValidationOutcome(kind="valid", message="Slack credentials are valid.")


__all__ = [
    "SlackRefreshOutcome",
    "SlackValidationOutcome",
    "is_slack_connection",
    "refresh_slack_token",
    "validate_slack_access_token",
]
