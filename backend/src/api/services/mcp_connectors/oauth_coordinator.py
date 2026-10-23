"""OAuth 2.1 + dynamic client registration for remote MCP servers.

Implements the subset of OAuth necessary to authenticate against a
remote MCP server that follows the MCP authorization spec (which
itself piggybacks on RFC 8414 metadata discovery and RFC 7591 dynamic
client registration). The flow is:

  1. ``begin_registration(server_url)``
       * Probe the MCP server for a 401 + ``WWW-Authenticate`` header
         pointing at its ``resource_metadata`` URL (RFC 9728-style),
         falling back to the spec's well-known location if absent.
       * Fetch the protected-resource metadata to learn which
         authorization server(s) it trusts.
       * Fetch each authorization server's metadata (RFC 8414) and
         pick one that supports both ``authorization_code`` grant +
         PKCE (S256).
       * If the server supports RFC 7591 dynamic client registration,
         POST to its ``registration_endpoint`` and capture the
         returned client_id (no client_secret for public clients).
       * Generate a PKCE pair, persist a transient ``state`` record
         keyed by random ``state`` token, and return an authorization
         URL the user's browser should open.

  2. ``complete_registration(state, code)``
       * Look up the transient record (which carries server metadata,
         code_verifier, redirect_uri, etc.).
       * Exchange ``code`` for an access token at the token endpoint.
       * Return the parsed token payload (access_token, refresh_token,
         expires_in, scope) plus the connection metadata that the
         caller (FastAPI route handler) will persist into preferences
         and forward to the Swift Keychain bridge.

  3. ``refresh(connection_record, refresh_token)``
       * POST to the cached token endpoint with the refresh token.
       * Return the new token payload.

This module owns the protocol; it owns NO storage. Persisting the
client_id into ``MCPConnectionRecord``, persisting the access_token
to the Swift Keychain, and routing the user's browser open are all
the responsibility of the FastAPI route handler that drives this
coordinator.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)


WELL_KNOWN_PROTECTED_RESOURCE = "/.well-known/oauth-protected-resource"
WELL_KNOWN_AUTHORIZATION_SERVER = "/.well-known/oauth-authorization-server"
WELL_KNOWN_OPENID = "/.well-known/openid-configuration"

DEFAULT_HTTP_TIMEOUT_SECONDS = 15.0
"""Per-HTTP-request deadline for discovery / registration / token
exchange. Token endpoints can be slow on first contact; 15s leaves
slack without making the user sit through long hangs."""

PENDING_STATE_TTL_SECONDS = 600
"""Authorization codes are short-lived (typically 60-300s); the
transient record we cache in-process needs to outlive the slowest
plausible round-trip-through-browser-and-back, but no longer."""


@dataclass
class PendingAuthorization:
    """In-memory record cached between begin_registration and
    complete_registration.

    Lives only in this process; if the backend restarts mid-flow the
    user will get a clean error and be prompted to start over. That's
    the right tradeoff: persisting half-open OAuth flows to disk is a
    security smell.
    """
    state: str
    code_verifier: str
    code_challenge: str
    redirect_uri: str
    server_url: str
    friendly_name: str
    authorization_server: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: Optional[str]
    scopes: List[str]
    client_id: str
    created_at: float = field(default_factory=time.time)


@dataclass
class TokenPayload:
    """Parsed RFC 6749 token-endpoint response."""
    access_token: str
    refresh_token: Optional[str]
    expires_in: Optional[int]
    token_type: str
    scope: Optional[str]
    raw: Dict[str, Any]


@dataclass
class ConnectionDescriptor:
    """Everything the route handler needs to persist a new connection.

    Returned from ``complete_registration`` so the caller can build
    an ``MCPConnectionRecord`` without reaching back into the
    coordinator's transient state.
    """
    server_url: str
    friendly_name: str
    authorization_server: str
    token_endpoint: str
    client_id: str
    scopes: List[str]
    token: TokenPayload


class OAuthCoordinatorError(Exception):
    """Raised for any failure during MCP OAuth that the route handler
    should surface to the user."""


class OAuthCoordinator:
    """Drives the OAuth flow for remote MCP servers."""

    def __init__(self, http_timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS):
        self._http_timeout = http_timeout_seconds
        self._pending: Dict[str, PendingAuthorization] = {}
        self._lock = asyncio.Lock()

    async def begin_registration(
        self,
        *,
        server_url: str,
        friendly_name: str,
        redirect_uri: str,
        client_name: str = "Basil",
        requested_scopes: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """Prepare an OAuth flow and return the URL the browser must open.

        Returns a dict with two keys: ``authorization_url`` (the
        external URL the user is sent to) and ``state`` (the opaque
        identifier the caller will hand back when the redirect fires).
        """
        await self._evict_expired()

        async with httpx.AsyncClient(timeout=self._http_timeout, follow_redirects=True) as http:
            resource_metadata = await self._discover_protected_resource(http, server_url)
            authorization_server_url = self._pick_authorization_server(resource_metadata)
            as_metadata = await self._fetch_authorization_server_metadata(
                http, authorization_server_url
            )

            self._validate_pkce_support(as_metadata)

            registration_endpoint = as_metadata.get("registration_endpoint")
            client_id = await self._dynamic_client_registration(
                http,
                registration_endpoint=registration_endpoint,
                redirect_uri=redirect_uri,
                client_name=client_name,
                resource=server_url,
            )

            scopes = self._resolve_scopes(requested_scopes, as_metadata, resource_metadata)

            code_verifier, code_challenge = self._generate_pkce_pair()
            state = secrets.token_urlsafe(32)

            pending = PendingAuthorization(
                state=state,
                code_verifier=code_verifier,
                code_challenge=code_challenge,
                redirect_uri=redirect_uri,
                server_url=server_url,
                friendly_name=friendly_name,
                authorization_server=authorization_server_url,
                authorization_endpoint=as_metadata["authorization_endpoint"],
                token_endpoint=as_metadata["token_endpoint"],
                registration_endpoint=registration_endpoint,
                scopes=scopes,
                client_id=client_id,
            )
            async with self._lock:
                self._pending[state] = pending

            authorization_url = self._build_authorization_url(pending)
            return {"authorization_url": authorization_url, "state": state}

    async def complete_registration(
        self,
        *,
        state: str,
        code: str,
    ) -> ConnectionDescriptor:
        """Exchange the OAuth ``code`` for tokens and finalize the connection."""
        async with self._lock:
            pending = self._pending.pop(state, None)
        if pending is None:
            raise OAuthCoordinatorError(
                "Unknown or expired OAuth state. Start the connection flow again."
            )
        if time.time() - pending.created_at > PENDING_STATE_TTL_SECONDS:
            raise OAuthCoordinatorError(
                "OAuth flow timed out. Start the connection flow again."
            )

        async with httpx.AsyncClient(timeout=self._http_timeout) as http:
            token = await self._exchange_code_for_token(http, pending=pending, code=code)

        return ConnectionDescriptor(
            server_url=pending.server_url,
            friendly_name=pending.friendly_name,
            authorization_server=pending.authorization_server,
            token_endpoint=pending.token_endpoint,
            client_id=pending.client_id,
            scopes=pending.scopes,
            token=token,
        )

    async def refresh(
        self,
        *,
        token_endpoint: str,
        client_id: str,
        refresh_token: str,
    ) -> TokenPayload:
        """Use a refresh token to obtain a new access token."""
        async with httpx.AsyncClient(timeout=self._http_timeout) as http:
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            }
            resp = await http.post(token_endpoint, data=data)
            if resp.status_code >= 400:
                raise OAuthCoordinatorError(
                    f"Token refresh failed (HTTP {resp.status_code}): {resp.text[:200]}"
                )
            return self._parse_token_response(resp.json())

    async def _discover_protected_resource(
        self, http: httpx.AsyncClient, server_url: str
    ) -> Dict[str, Any]:
        """Fetch protected-resource metadata for an MCP server.

        The MCP authorization spec instructs servers to either return
        a 401 with a ``WWW-Authenticate: Bearer resource_metadata=...``
        header on unauthenticated requests, OR host the metadata at
        the well-known path. We attempt the well-known path first
        (cheaper) and fall back to inspecting a 401 response.
        """
        well_known_url = self._build_well_known(server_url, WELL_KNOWN_PROTECTED_RESOURCE)
        try:
            resp = await http.get(well_known_url)
            if resp.status_code == 200:
                return resp.json()
        except httpx.HTTPError:
            pass

        try:
            probe = await http.get(server_url)
            challenge = probe.headers.get("WWW-Authenticate") or probe.headers.get("www-authenticate")
            if probe.status_code in (401, 403) and challenge:
                metadata_url = self._extract_resource_metadata_url(challenge)
                if metadata_url:
                    resp = await http.get(metadata_url)
                    if resp.status_code == 200:
                        return resp.json()
        except httpx.HTTPError:
            pass

        # Final fallback: the MCP spec also allows servers to expose
        # authorization-server metadata directly at the same origin,
        # in which case we synthesize a minimal protected-resource
        # document pointing at that origin.
        return {"authorization_servers": [self._origin_of(server_url)]}

    async def _fetch_authorization_server_metadata(
        self, http: httpx.AsyncClient, authorization_server_url: str
    ) -> Dict[str, Any]:
        """Fetch RFC 8414 metadata, falling back to OpenID Connect discovery."""
        for path in (WELL_KNOWN_AUTHORIZATION_SERVER, WELL_KNOWN_OPENID):
            url = self._build_well_known(authorization_server_url, path)
            try:
                resp = await http.get(url)
                if resp.status_code == 200:
                    metadata = resp.json()
                    if "authorization_endpoint" in metadata and "token_endpoint" in metadata:
                        return metadata
            except httpx.HTTPError:
                continue
        raise OAuthCoordinatorError(
            f"Could not locate authorization server metadata for {authorization_server_url}. "
            "The server may not implement RFC 8414 / OpenID Connect Discovery."
        )

    @staticmethod
    def _validate_pkce_support(as_metadata: Dict[str, Any]) -> None:
        """Refuse to proceed if the server doesn't advertise PKCE-S256.

        Public clients without a secret MUST use PKCE; if the server
        cannot accept S256, we are not in spec-compliant territory and
        should not pretend otherwise.
        """
        methods = as_metadata.get("code_challenge_methods_supported")
        if methods is None:
            logger.info(
                "Authorization server did not advertise code_challenge_methods_supported; "
                "assuming S256 per OAuth 2.1 default."
            )
            return
        if "S256" not in methods:
            raise OAuthCoordinatorError(
                "Authorization server does not support PKCE S256, which is required."
            )

    @staticmethod
    def _pick_authorization_server(resource_metadata: Dict[str, Any]) -> str:
        servers = resource_metadata.get("authorization_servers") or []
        if not servers:
            raise OAuthCoordinatorError(
                "Resource metadata did not list any authorization servers."
            )
        return servers[0]

    async def _dynamic_client_registration(
        self,
        http: httpx.AsyncClient,
        *,
        registration_endpoint: Optional[str],
        redirect_uri: str,
        client_name: str,
        resource: str,
    ) -> str:
        """RFC 7591 dynamic client registration.

        If the server doesn't expose a registration endpoint, the user
        must manually register Basil and supply a client_id out of
        band; we surface a clear error and let the route handler decide
        how to prompt for that.
        """
        if not registration_endpoint:
            raise OAuthCoordinatorError(
                "Authorization server does not support RFC 7591 dynamic client "
                "registration. Manual client registration is not supported by the "
                "MVP; pick a different MCP server or open a follow-up issue."
            )

        body = {
            "client_name": client_name,
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "application_type": "native",
            "software_id": "com.stratten.basil",
        }
        resp = await http.post(registration_endpoint, json=body)
        if resp.status_code not in (200, 201):
            raise OAuthCoordinatorError(
                f"Dynamic client registration failed (HTTP {resp.status_code}): "
                f"{resp.text[:300]}"
            )
        payload = resp.json()
        client_id = payload.get("client_id")
        if not client_id:
            raise OAuthCoordinatorError(
                "Dynamic client registration response missing client_id."
            )
        return client_id

    @staticmethod
    def _resolve_scopes(
        requested: Optional[List[str]],
        as_metadata: Dict[str, Any],
        resource_metadata: Dict[str, Any],
    ) -> List[str]:
        """Pick the scopes to request.

        Preference order:
          1. Caller-supplied scopes (allows the Settings UI to ask
             for the minimum needed).
          2. Scopes the resource metadata says the server requires.
          3. The intersection of "everything the AS supports" and a
             conservative default ('openid', 'offline_access') so we
             always request a refresh token if available.
        """
        if requested:
            return list(requested)
        resource_scopes = resource_metadata.get("scopes_supported")
        if isinstance(resource_scopes, list) and resource_scopes:
            return list(resource_scopes)
        as_scopes = as_metadata.get("scopes_supported") or []
        wanted = ["openid", "offline_access"]
        return [s for s in wanted if s in as_scopes] or as_scopes[:1]

    @staticmethod
    def _generate_pkce_pair() -> tuple:
        """Return ``(code_verifier, code_challenge)`` using S256."""
        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return verifier, challenge

    @staticmethod
    def _build_authorization_url(pending: PendingAuthorization) -> str:
        params = {
            "response_type": "code",
            "client_id": pending.client_id,
            "redirect_uri": pending.redirect_uri,
            "code_challenge": pending.code_challenge,
            "code_challenge_method": "S256",
            "state": pending.state,
        }
        if pending.scopes:
            params["scope"] = " ".join(pending.scopes)
        return f"{pending.authorization_endpoint}?{urlencode(params)}"

    async def _exchange_code_for_token(
        self,
        http: httpx.AsyncClient,
        *,
        pending: PendingAuthorization,
        code: str,
    ) -> TokenPayload:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": pending.redirect_uri,
            "client_id": pending.client_id,
            "code_verifier": pending.code_verifier,
        }
        resp = await http.post(pending.token_endpoint, data=data)
        if resp.status_code >= 400:
            raise OAuthCoordinatorError(
                f"Token exchange failed (HTTP {resp.status_code}): {resp.text[:300]}"
            )
        return self._parse_token_response(resp.json())

    @staticmethod
    def _parse_token_response(payload: Dict[str, Any]) -> TokenPayload:
        access = payload.get("access_token")
        if not access:
            raise OAuthCoordinatorError("Token endpoint response missing access_token.")
        return TokenPayload(
            access_token=access,
            refresh_token=payload.get("refresh_token"),
            expires_in=payload.get("expires_in"),
            token_type=payload.get("token_type", "Bearer"),
            scope=payload.get("scope"),
            raw=payload,
        )

    @staticmethod
    def _build_well_known(base_url: str, path: str) -> str:
        """Compose a ``.well-known`` URL preserving any path prefix.

        RFC 8414 §3 says metadata SHOULD live directly under the
        issuer's origin (``https://issuer/.well-known/...``). Some
        servers tuck their metadata under a path-prefixed issuer; we
        try the origin first, which matches the common case.
        """
        parsed = urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return urljoin(origin + "/", path.lstrip("/"))

    @staticmethod
    def _origin_of(url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @staticmethod
    def _extract_resource_metadata_url(www_authenticate: str) -> Optional[str]:
        """Pull ``resource_metadata="<url>"`` from a WWW-Authenticate header.

        Format per RFC 9728: ``Bearer resource_metadata="https://..."``.
        """
        marker = "resource_metadata="
        idx = www_authenticate.find(marker)
        if idx < 0:
            return None
        rest = www_authenticate[idx + len(marker):].strip()
        if rest.startswith('"'):
            end = rest.find('"', 1)
            if end > 0:
                return rest[1:end]
        end = rest.find(",")
        return rest if end < 0 else rest[:end]

    async def _evict_expired(self) -> None:
        """Drop pending records older than the TTL.

        Cheap; runs at the top of begin_registration so the in-memory
        map can't grow unbounded if the user starts flows but never
        finishes them.
        """
        cutoff = time.time() - PENDING_STATE_TTL_SECONDS
        async with self._lock:
            stale = [s for s, p in self._pending.items() if p.created_at < cutoff]
            for s in stale:
                self._pending.pop(s, None)
