"""Slack OAuth PKCE coordinator for Slack's hosted MCP server.

Slack's hosted MCP endpoint (``https://mcp.slack.com/mcp``) does not
expose Dynamic Client Registration. Instead, Slack documents a public
PKCE flow for desktop clients with a pre-registered ``client_id`` and
a custom URI redirect that the desktop app handles. This coordinator
owns that Slack-specific protocol surface and no storage.

Authorization:
  * GET ``https://slack.com/oauth/v2_user/authorize`` with
    ``client_id``, ``user_scope``, ``redirect_uri``, ``state``,
    ``code_challenge`` and ``code_challenge_method=S256``.
  * Slack redirects back to the registered URI with ``code`` and
    ``state``. The Swift client receives that custom URI and forwards
    both fields to the local Python ``complete_oauth`` route.

Token exchange:
  * POST ``https://slack.com/api/oauth.v2.user.access`` with
    ``client_id``, ``code``, ``code_verifier``, ``redirect_uri``,
    ``grant_type=authorization_code``.
  * Slack PKCE desktop flows issue rotating user tokens. Refresh
    tokens expire after 30 days from issuance.

This module owns the protocol surface only. Persisting the connection
record into preferences, pushing tokens to Swift over the WebSocket
bridge, and routing browser opens are all the route handler's
responsibility.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)


SLACK_MCP_SERVER_URL = "https://mcp.slack.com/mcp"
SLACK_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.user.access"
"""The Slack MCP integration uses a *hybrid* of Slack's two OAuth flows.

  * Authorize at the general endpoint (``oauth/v2/authorize``). Slack's
    workspace install page only knows how to render consent for
    requests that arrive there with a granular-bot-scope ``scope=`` /
    ``user_scope=`` shape. ``oauth/v2_user/authorize`` is documented in
    the MCP overview but in practice forwards through the same install
    page with ``user_scope`` dropped, producing "No scopes requested".
  * Token-exchange at the MCP-flavored endpoint
    (``oauth.v2.user.access``). Tokens minted by the general
    ``oauth.v2.access`` endpoint authenticate elsewhere in Slack's API
    but produce HTTP 400 from ``mcp.slack.com/mcp`` on the first
    JSON-RPC POST. The user-only redemption endpoint mints a token
    flavor the hosted MCP server accepts. Slack's own error reference
    for ``oauth.v2.user.access`` confirms this pairing: the
    ``oauth_authorization_url_mismatch`` error explicitly says the flow
    must be initiated via ``/oauth/v2/authorize``."""

SLACK_REDIRECT_URI = "basil://mcp/slack_oauth_callback"
"""Fixed custom URI scheme the Swift client handles. Slack requires
redirect URIs to be pre-registered, so a dynamic local Python port
cannot be a stable redirect target."""

SLACK_CLIENT_ID_ENV_VAR = "BASIL_SLACK_CLIENT_ID"
"""Optional environment-variable override for the Slack app
``client_id``. The client ID is not a secret (PKCE is the public-client
flow), so callers can flip the env var at runtime to point Basil at a
different Slack app without rebuilding. When unset, the bundled
default :data:`SLACK_DEFAULT_CLIENT_ID` is used."""

SLACK_DEFAULT_CLIENT_ID = "10368344410674.11170867141478"
"""Bundled Slack app client ID for the Basil-owned Slack app.

This mirrors how :mod:`github_device_flow_coordinator` ships
``GITHUB_OAUTH_CLIENT_ID`` as a module constant: PKCE/public-client
``client_id`` values are non-secret, the bundled default is what makes
the Connect with Slack flow work out of the box, and the env var
override remains available for testing."""

SLACK_DEFAULT_USER_SCOPES: List[str] = [
    # Search — hosted MCP advertises granular search scopes, but Slack Web API
    # search.messages/search.files still require the broad ``search:read`` scope.
    "search:read",
    "search:read.public",
    "search:read.private",
    "search:read.mpim",
    "search:read.im",
    "search:read.files",
    "search:read.users",
    # History — needed for ``slack_read_channel_history`` / ``slack_read_thread`` across
    # public channels, private channels, DMs, and group DMs.
    "channels:history",
    "groups:history",
    "im:history",
    "mpim:history",
    # Conversation metadata reads — list/info on the same four conversation types.
    "channels:read",
    "groups:read",
    "im:read",
    "mpim:read",
    # Conversation creation — required by ``slack_create_channel`` for both public
    # (``channels:write``) and private (``groups:write``) variants. ``im:write`` and
    # ``mpim:write`` cover the case of opening DMs / group DMs programmatically.
    "channels:write",
    "groups:write",
    "im:write",
    "mpim:write",
    # Messaging — sending and reacting.
    "chat:write",
    "reactions:write",
    "reactions:read",
    # Canvases — create + read of standalone and channel-attached canvases.
    "canvases:read",
    "canvases:write",
    # People & assets that the read tools surface alongside messages.
    "users:read",
    "users:read.email",
    "files:read",
    "emoji:read",
    "team:read",
]
"""Full-parity scope set matching the ``scopes_supported`` advertised
by ``https://mcp.slack.com/.well-known/oauth-authorization-server``.

Why request the full set even though we currently dispatch through
the embedded ``slack_local_server`` rather than Slack's hosted MCP:

  * The twelve embedded tools collectively need every scope listed
    here to function (e.g. ``slack_create_channel`` requires
    ``channels:write`` / ``groups:write``; ``slack_create_canvas``
    requires ``canvases:write``; ``slack_get_user_profile`` returns
    email only when ``users:read.email`` is granted).
  * When we eventually flip ``server_url`` back to the hosted endpoint
    after Marketplace approval, the consent UX should not need to
    re-prompt the user for additional scopes; tokens minted today must
    be valid against either dispatch path.

Slack's PKCE flow requires the user to approve every requested scope.
For workspaces where some of these scopes are restricted, the install
will fail during consent rather than partially succeeding. A future
"degraded scope" mode (request all, accept whichever subset the
workspace allows) is tracked separately and not part of this change."""

DEFAULT_HTTP_TIMEOUT_SECONDS = 15.0
PENDING_STATE_TTL_SECONDS = 600
"""Authorization codes live for a short window; the pending record
needs to outlive the slowest plausible browser round-trip, no more."""


class SlackPKCEError(Exception):
    """Raised when the Slack PKCE flow cannot proceed.

    The error code mirrors Slack's ``error`` field when available, or
    one of the local short codes used by the coordinator
    (``unknown_state``, ``state_expired``, ``missing_client_id``,
    ``missing_access_token``, ``http_error``).
    """


@dataclass
class SlackPendingAuthorization:
    """In-memory record bridging begin and complete steps.

    Lives only in this process; if the backend restarts mid-flow the
    user will get a clean ``unknown_state`` error and be prompted to
    start over. That is the right tradeoff: persisting half-open OAuth
    flows to disk is a security smell.
    """

    state: str
    code_verifier: str
    code_challenge: str
    redirect_uri: str
    server_url: str
    friendly_name: str
    client_id: str
    scopes: List[str]
    created_at: float = field(default_factory=time.time)


@dataclass
class SlackTokenPayload:
    """Parsed Slack ``oauth.v2.user.access`` response."""

    access_token: str
    refresh_token: Optional[str]
    expires_in: Optional[int]
    token_type: str
    scope: Optional[str]
    user_id: Optional[str]
    team_id: Optional[str]
    team_name: Optional[str]
    raw: Dict[str, Any]


@dataclass
class SlackConnectionDescriptor:
    """Everything the route handler needs to persist a Slack connection."""

    server_url: str
    friendly_name: str
    client_id: str
    scopes: List[str]
    token: SlackTokenPayload


def resolve_slack_client_id(explicit: Optional[str] = None) -> str:
    """Return the Slack app ``client_id`` for this Basil install.

    Order of resolution:
      1. ``explicit`` argument (used by tests or future per-user override).
      2. ``BASIL_SLACK_CLIENT_ID`` environment variable.
      3. :data:`SLACK_DEFAULT_CLIENT_ID` bundled with the app.

    Raises ``SlackPKCEError('missing_client_id')`` only if all three
    sources are empty/blank, which should never happen in a normal
    build. The client ID is not a secret; it identifies which Slack
    app a user is authorizing, not which user.
    """
    value = (
        explicit
        or os.environ.get(SLACK_CLIENT_ID_ENV_VAR, "")
        or SLACK_DEFAULT_CLIENT_ID
    ).strip()
    if not value:
        raise SlackPKCEError("missing_client_id")
    return value


class SlackPKCECoordinator:
    """Drives the Slack OAuth PKCE flow for the hosted Slack MCP server."""

    def __init__(self, http_timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS):
        self._http_timeout = http_timeout_seconds
        self._pending: Dict[str, SlackPendingAuthorization] = {}
        self._lock = asyncio.Lock()

    async def begin_authorization(
        self,
        *,
        friendly_name: str = "Slack",
        server_url: str = SLACK_MCP_SERVER_URL,
        redirect_uri: str = SLACK_REDIRECT_URI,
        scopes: Optional[List[str]] = None,
        client_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a Slack authorization URL and cache pending PKCE state.

        Returns ``{"authorization_url": str, "state": str,
        "scopes": List[str]}``. The caller is responsible for opening
        the URL in the user's default browser.
        """
        await self._evict_expired()

        resolved_client_id = resolve_slack_client_id(client_id)
        resolved_scopes = list(scopes) if scopes else list(SLACK_DEFAULT_USER_SCOPES)
        verifier, challenge = _generate_pkce_pair()
        state = secrets.token_urlsafe(32)

        pending = SlackPendingAuthorization(
            state=state,
            code_verifier=verifier,
            code_challenge=challenge,
            redirect_uri=redirect_uri,
            server_url=server_url,
            friendly_name=friendly_name,
            client_id=resolved_client_id,
            scopes=resolved_scopes,
        )
        async with self._lock:
            self._pending[state] = pending

        url = self._build_authorization_url(pending)
        logger.info(
            "Slack PKCE authorization started (state=%s, scopes=%d)",
            state[:8] + "...",
            len(resolved_scopes),
        )
        return {
            "authorization_url": url,
            "state": state,
            "scopes": resolved_scopes,
        }

    async def complete_authorization(
        self,
        *,
        state: str,
        code: str,
    ) -> SlackConnectionDescriptor:
        """Exchange the Slack ``code`` for a user access token bundle."""
        async with self._lock:
            pending = self._pending.pop(state, None)
        if pending is None:
            raise SlackPKCEError("unknown_state")
        if time.time() - pending.created_at > PENDING_STATE_TTL_SECONDS:
            raise SlackPKCEError("state_expired")

        async with httpx.AsyncClient(timeout=self._http_timeout) as http:
            token = await self._exchange_code_for_token(http, pending=pending, code=code)

        return SlackConnectionDescriptor(
            server_url=pending.server_url,
            friendly_name=pending.friendly_name,
            client_id=pending.client_id,
            scopes=pending.scopes,
            token=token,
        )

    async def refresh(
        self,
        *,
        client_id: str,
        refresh_token: str,
    ) -> SlackTokenPayload:
        """Rotate a Slack user token using its refresh token."""
        async with httpx.AsyncClient(timeout=self._http_timeout) as http:
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            }
            try:
                resp = await http.post(SLACK_TOKEN_URL, data=data)
            except httpx.HTTPError as exc:
                raise SlackPKCEError("http_error") from exc
            return self._parse_token_response(resp)

    async def get_pending_authorization(
        self, state: str
    ) -> Optional[SlackPendingAuthorization]:
        async with self._lock:
            return self._pending.get(state)

    async def _exchange_code_for_token(
        self,
        http: httpx.AsyncClient,
        *,
        pending: SlackPendingAuthorization,
        code: str,
    ) -> SlackTokenPayload:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": pending.redirect_uri,
            "client_id": pending.client_id,
            "code_verifier": pending.code_verifier,
        }
        try:
            resp = await http.post(SLACK_TOKEN_URL, data=data)
        except httpx.HTTPError as exc:
            raise SlackPKCEError("http_error") from exc
        return self._parse_token_response(resp)

    @staticmethod
    def _build_authorization_url(pending: SlackPendingAuthorization) -> str:
        # Slack's general ``oauth/v2/authorize`` endpoint requires both
        # ``scope`` (bot scopes) and ``user_scope`` (user scopes) to be
        # present. Desktop / public-client redirects can't request bot
        # scopes, so ``scope`` must be present-but-empty. Omitting it
        # entirely is what produces the "Invalid permissions requested /
        # No scopes requested" install rejection. The MCP-flavored token
        # is determined at redemption time by ``SLACK_TOKEN_URL``, not
        # by the authorize URL or the scope-parameter shape here.
        params = {
            "client_id": pending.client_id,
            "scope": "",
            "user_scope": ",".join(pending.scopes) if pending.scopes else "",
            "redirect_uri": pending.redirect_uri,
            "code_challenge": pending.code_challenge,
            "code_challenge_method": "S256",
            "state": pending.state,
        }
        return f"{SLACK_AUTHORIZE_URL}?{urlencode(params)}"

    @staticmethod
    def _parse_token_response(resp: httpx.Response) -> SlackTokenPayload:
        """Parse Slack's ``oauth.v2.user.access`` response.

        Slack returns HTTP 200 with ``{"ok": false, "error": "..."}``
        on failure rather than a 4xx code, so the ``ok`` field must
        be inspected explicitly.
        """
        try:
            payload: Dict[str, Any] = resp.json()
        except ValueError as exc:
            raise SlackPKCEError("http_error") from exc

        if resp.status_code >= 400:
            raise SlackPKCEError(f"http_{resp.status_code}")

        if not payload.get("ok"):
            error_code = str(payload.get("error") or "unknown_error")
            raise SlackPKCEError(error_code)

        authed_user = payload.get("authed_user") or {}
        access_token = authed_user.get("access_token") or payload.get("access_token")
        if not access_token:
            raise SlackPKCEError("missing_access_token")

        refresh_token = authed_user.get("refresh_token") or payload.get("refresh_token")
        expires_in_raw = authed_user.get("expires_in") or payload.get("expires_in")
        try:
            expires_in = int(expires_in_raw) if expires_in_raw is not None else None
        except (TypeError, ValueError):
            expires_in = None

        team = payload.get("team") or {}
        return SlackTokenPayload(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            token_type=authed_user.get("token_type") or payload.get("token_type", "user"),
            scope=authed_user.get("scope") or payload.get("scope"),
            user_id=authed_user.get("id"),
            team_id=team.get("id") or payload.get("team_id"),
            team_name=team.get("name") or payload.get("team_name"),
            raw=payload,
        )

    async def _evict_expired(self) -> None:
        cutoff = time.time() - PENDING_STATE_TTL_SECONDS
        async with self._lock:
            stale = [s for s, p in self._pending.items() if p.created_at < cutoff]
            for s in stale:
                self._pending.pop(s, None)


def _generate_pkce_pair() -> tuple:
    """Return ``(code_verifier, code_challenge)`` using S256."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


__all__ = [
    "SLACK_AUTHORIZE_URL",
    "SLACK_CLIENT_ID_ENV_VAR",
    "SLACK_DEFAULT_CLIENT_ID",
    "SLACK_DEFAULT_USER_SCOPES",
    "SLACK_MCP_SERVER_URL",
    "SLACK_REDIRECT_URI",
    "SLACK_TOKEN_URL",
    "SlackConnectionDescriptor",
    "SlackPKCECoordinator",
    "SlackPKCEError",
    "SlackPendingAuthorization",
    "SlackTokenPayload",
    "resolve_slack_client_id",
]
