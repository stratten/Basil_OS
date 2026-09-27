"""GitHub OAuth App device flow for the hosted GitHub MCP server.

GitHub's hosted MCP endpoint (``https://api.githubcopilot.com/mcp/``)
accepts tokens minted through a GitHub OAuth App device flow, but it does
not support the MCP OAuth Dynamic Client Registration path that Linear
uses. This coordinator owns that GitHub-specific protocol surface and no
storage.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx


GITHUB_MCP_SERVER_URL = "https://api.githubcopilot.com/mcp/"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_OAUTH_CLIENT_ID = "Ov23ligPHPeUPWYwWNjD"

GITHUB_MCP_SCOPES = [
    "repo",
    "read:org",
    "read:user",
    "user:email",
    "read:project",
    "project",
    "gist",
    "notifications",
    "workflow",
]

DEFAULT_HTTP_TIMEOUT_SECONDS = 15.0


class GitHubDeviceFlowError(Exception):
    """Raised when GitHub device flow cannot proceed."""


@dataclass
class GitHubDeviceAuthorization:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int
    friendly_name: str
    server_url: str = GITHUB_MCP_SERVER_URL
    scopes: List[str] = field(default_factory=lambda: list(GITHUB_MCP_SCOPES))
    created_at: float = field(default_factory=time.time)


@dataclass
class GitHubDeviceToken:
    access_token: str
    token_type: str
    scope: Optional[str]
    raw: Dict[str, Any]


class GitHubDeviceFlowCoordinator:
    """Small stateful coordinator for GitHub device authorization."""

    def __init__(self, http_timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS):
        self._http_timeout = http_timeout_seconds
        self._pending: Dict[str, GitHubDeviceAuthorization] = {}
        self._lock = asyncio.Lock()

    async def begin_authorization(
        self,
        *,
        friendly_name: str = "GitHub",
        server_url: str = GITHUB_MCP_SERVER_URL,
        scopes: Optional[List[str]] = None,
        client_id: str = GITHUB_OAUTH_CLIENT_ID,
    ) -> GitHubDeviceAuthorization:
        """Start a GitHub OAuth device flow and cache the pending device code."""
        requested_scopes = scopes or list(GITHUB_MCP_SCOPES)
        async with httpx.AsyncClient(timeout=self._http_timeout) as http:
            response = await http.post(
                GITHUB_DEVICE_CODE_URL,
                data={
                    "client_id": client_id,
                    "scope": " ".join(requested_scopes),
                },
                headers={"Accept": "application/json"},
            )
        if response.status_code >= 400:
            raise GitHubDeviceFlowError(
                f"GitHub device-code request failed (HTTP {response.status_code}): {response.text[:300]}"
            )
        payload = response.json()
        try:
            auth = GitHubDeviceAuthorization(
                device_code=payload["device_code"],
                user_code=payload["user_code"],
                verification_uri=payload.get("verification_uri") or "https://github.com/login/device",
                expires_in=int(payload.get("expires_in", 900)),
                interval=max(int(payload.get("interval", 5)), 5),
                friendly_name=friendly_name,
                server_url=server_url,
                scopes=requested_scopes,
            )
        except KeyError as exc:
            raise GitHubDeviceFlowError(f"GitHub device-code response missing {exc}") from exc

        async with self._lock:
            self._pending[auth.device_code] = auth
        return auth

    async def poll_token(
        self,
        *,
        device_code: str,
        client_id: str = GITHUB_OAUTH_CLIENT_ID,
    ) -> GitHubDeviceToken:
        """Poll GitHub for the access token.

        Raises ``GitHubDeviceFlowError('authorization_pending')`` while the
        user has not approved yet. The route layer maps that to a 202-style
        response for Swift polling.
        """
        async with self._lock:
            auth = self._pending.get(device_code)
        if auth is None:
            raise GitHubDeviceFlowError("unknown_device_code")
        if time.time() - auth.created_at > auth.expires_in:
            async with self._lock:
                self._pending.pop(device_code, None)
            raise GitHubDeviceFlowError("expired_token")

        async with httpx.AsyncClient(timeout=self._http_timeout) as http:
            response = await http.post(
                GITHUB_ACCESS_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
            )
        if response.status_code >= 400:
            raise GitHubDeviceFlowError(
                f"GitHub token polling failed (HTTP {response.status_code}): {response.text[:300]}"
            )
        payload = response.json()
        error = payload.get("error")
        if error:
            if error == "slow_down":
                auth.interval += 5
            raise GitHubDeviceFlowError(error)

        access_token = payload.get("access_token")
        if not access_token:
            raise GitHubDeviceFlowError(f"GitHub token response missing access_token: {payload}")

        async with self._lock:
            self._pending.pop(device_code, None)

        return GitHubDeviceToken(
            access_token=access_token,
            token_type=payload.get("token_type", "bearer"),
            scope=payload.get("scope"),
            raw=payload,
        )

    async def get_pending_authorization(self, device_code: str) -> Optional[GitHubDeviceAuthorization]:
        """Return pending metadata for route persistence after token success."""
        async with self._lock:
            return self._pending.get(device_code)
