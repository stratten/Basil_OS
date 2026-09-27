"""HTTP endpoints for Slack OAuth PKCE connection setup.

Kept separate from ``routes.py`` so the Slack-specific PKCE flow can
grow (refresh, rotation diagnostics, scope upgrade prompts) without
pushing the main connections router over its modularity budget. The
endpoints are attached to the existing ``router`` via
:func:`register_slack_routes` so they live under the same
``/settings/connections`` prefix as the rest of the connections API.

Boundaries (mirrors ``routes.py``):
  * The route layer persists ``MCPConnectionRecord`` metadata only; it
    never persists Slack tokens.
  * Slack access + refresh tokens are pushed to Swift over the
    ``mcp_token_store`` WebSocket bridge so they land in Keychain.
  * The PKCE pending state lives in process memory on the
    :class:`SlackPKCECoordinator` singleton.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException

from api.core.models.preferences import (
    MCPConnectionRecord,
)
from api.services.mcp_connectors.slack_local_server import (
    LOCAL_SLACK_SENTINEL_URL,
)
from api.services.mcp_connectors.slack_pkce_coordinator import (
    SLACK_DEFAULT_USER_SCOPES,
    SLACK_MCP_SERVER_URL,
    SlackConnectionDescriptor,
    SlackPKCECoordinator,
    SlackPKCEError,
)
from api.services.mcp_connectors.swift_token_bridge import _push_token_to_swift

from .models import (
    ConnectionDTO,
    SlackCompleteOAuthRequest,
    SlackCompleteOAuthResponse,
    SlackStartOAuthRequest,
    SlackStartOAuthResponse,
)
from .connection_route_helpers import (
    connection_to_dto,
    load_connection_preferences,
    save_connection_preferences,
)

logger = logging.getLogger(__name__)


_slack_pkce_coordinator = SlackPKCECoordinator()
"""Process-singleton coordinator. Holds in-memory PKCE state across
the ``start_oauth`` -> Slack browser consent -> Swift custom URI ->
``complete_oauth`` round trip."""

_slack_connection_descriptions: dict[str, Optional[str]] = {}
"""State-keyed pending custom descriptions for Slack OAuth callbacks."""


def _connection_to_dto(record: MCPConnectionRecord) -> ConnectionDTO:
    """Local copy of the ``routes.py`` helper.

    Inlined deliberately so the Slack module does not import from
    ``routes.py`` and create a cycle. The shape mirrors the canonical
    helper exactly; both must continue to match.
    """
    return connection_to_dto(record)


def _persist_slack_connection(
    descriptor: SlackConnectionDescriptor,
    *,
    description: Optional[str] = None,
) -> MCPConnectionRecord:
    """Persist a Slack connection as metadata-only.

    Tokens stay out of preferences. They are pushed to Swift over the
    WebSocket bridge by the caller after this returns.

    The persisted ``server_url`` is the in-process sentinel
    (``basil-local://slack``) rather than the descriptor's hosted MCP
    URL. Until Basil's Slack app is Marketplace-approved, the hosted
    endpoint at ``mcp.slack.com/mcp`` rejects requests from unlisted
    apps with HTTP 400; routing to the embedded ``slack_local_server``
    package keeps the Slack connection functional with the same OAuth
    token. The descriptor's hosted URL is preserved on the descriptor
    itself for future migration when approval lands — flipping back is
    a one-line change here plus an optional startup helper to rewrite
    existing records.
    """
    prefs = load_connection_preferences()
    record = MCPConnectionRecord(
        friendly_name=descriptor.friendly_name,
        description=description,
        server_url=LOCAL_SLACK_SENTINEL_URL,
        oauth_client_id=descriptor.client_id,
        oauth_authorization_server="https://slack.com",
        oauth_token_endpoint="https://slack.com/api/oauth.v2.user.access",
        oauth_scopes=descriptor.scopes,
    )
    prefs.connections.mcp_connections.append(record)
    save_connection_preferences(prefs)
    return record


def _slack_error_status(code: str) -> int:
    """Map Slack PKCE error codes to HTTP status codes."""
    transient = {"unknown_state", "state_expired"}
    bad_request = {
        "invalid_code",
        "bad_redirect_uri",
        "missing_code",
        "invalid_grant",
        "code_already_used",
    }
    config = {"missing_client_id", "invalid_client_id"}
    if code in transient:
        return 410
    if code in config:
        return 500
    if code in bad_request:
        return 400
    if code.startswith("http_"):
        return 502
    return 400


async def slack_start_oauth(
    payload: SlackStartOAuthRequest,
) -> SlackStartOAuthResponse:
    """Begin a Slack PKCE flow and return the authorization URL.

    The Swift client opens ``authorization_url`` in the user's
    browser. Slack redirects back to the registered
    ``basil://mcp/slack_oauth_callback`` custom URI, which Swift then
    forwards to :func:`slack_complete_oauth` with ``code`` and
    ``state``.
    """
    requested_scopes: List[str] = (
        list(payload.requested_scopes)
        if payload.requested_scopes
        else list(SLACK_DEFAULT_USER_SCOPES)
    )
    try:
        result = await _slack_pkce_coordinator.begin_authorization(
            friendly_name=payload.friendly_name,
            server_url=payload.server_url or SLACK_MCP_SERVER_URL,
            scopes=requested_scopes,
        )
        _slack_connection_descriptions[result["state"]] = _normalize_optional_description(
            payload.description
        )
    except SlackPKCEError as exc:
        code = str(exc)
        raise HTTPException(
            status_code=_slack_error_status(code),
            detail={
                "kind": "slack_pkce_error",
                "code": code,
                "message": _slack_error_message(code),
            },
        )
    except Exception as exc:
        logger.exception("Unexpected failure starting Slack PKCE flow")
        raise HTTPException(status_code=500, detail=f"Slack OAuth start failed: {exc}")

    return SlackStartOAuthResponse(
        state=result["state"],
        authorization_url=result["authorization_url"],
        requested_scopes=result.get("scopes") or requested_scopes,
    )


async def slack_complete_oauth(
    payload: SlackCompleteOAuthRequest,
) -> SlackCompleteOAuthResponse:
    """Exchange Slack's ``code`` for tokens, persist, and push to Swift."""
    try:
        descriptor = await _slack_pkce_coordinator.complete_authorization(
            state=payload.state,
            code=payload.code,
        )
    except SlackPKCEError as exc:
        code = str(exc)
        raise HTTPException(
            status_code=_slack_error_status(code),
            detail={
                "kind": "slack_pkce_error",
                "code": code,
                "message": _slack_error_message(code),
            },
        )
    except Exception as exc:
        logger.exception("Unexpected failure completing Slack PKCE flow")
        raise HTTPException(status_code=500, detail=f"Slack OAuth completion failed: {exc}")

    description = _slack_connection_descriptions.pop(payload.state, None)
    record = _persist_slack_connection(descriptor, description=description)
    await _push_token_to_swift(
        connection_id=record.id,
        access_token=descriptor.token.access_token,
        refresh_token=descriptor.token.refresh_token,
        expires_in=descriptor.token.expires_in,
    )

    return SlackCompleteOAuthResponse(
        status="ok",
        connection=_connection_to_dto(record),
    )


def _slack_error_message(code: str) -> str:
    """Map Slack/coordinator error codes to user-facing messages."""
    mapping = {
        "missing_client_id": (
            "Basil's Slack app client ID is not configured. Set "
            "BASIL_SLACK_CLIENT_ID for the local backend and try again."
        ),
        "unknown_state": (
            "This Slack sign-in link expired or didn't match the one Basil "
            "started. Click Connect with Slack again."
        ),
        "state_expired": (
            "Slack sign-in took too long. Click Connect with Slack again."
        ),
        "missing_access_token": (
            "Slack returned a response without a user access token. "
            "Check that the Slack app is configured for user-scope PKCE."
        ),
        "invalid_client_id": (
            "Slack rejected the configured client ID. Verify Basil's Slack "
            "app is published or installed in this workspace."
        ),
        "bad_redirect_uri": (
            "Slack did not recognize the redirect URI. Confirm "
            "basil://mcp/slack_oauth_callback is registered in the Slack app."
        ),
    }
    if code in mapping:
        return mapping[code]
    if code.startswith("http_"):
        return f"Slack returned an unexpected HTTP error ({code})."
    return f"Slack OAuth failed: {code}"


def register_slack_routes(router: APIRouter) -> None:
    """Attach the Slack-specific endpoints to the connections router."""
    router.add_api_route(
        "/slack/start_oauth",
        slack_start_oauth,
        methods=["POST"],
        response_model=SlackStartOAuthResponse,
        name="slack_start_oauth",
    )
    router.add_api_route(
        "/slack/complete_oauth",
        slack_complete_oauth,
        methods=["POST"],
        response_model=SlackCompleteOAuthResponse,
        name="slack_complete_oauth",
    )


def _normalize_optional_description(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


__all__ = [
    "register_slack_routes",
    "slack_complete_oauth",
    "slack_start_oauth",
]
