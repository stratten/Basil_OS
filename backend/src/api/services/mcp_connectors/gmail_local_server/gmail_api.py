"""Thin async client for the Gmail REST API, used by the embedded Gmail server.

The client owns one concern: sending an authenticated request to
``gmail.googleapis.com`` and turning any non-success response into a
:class:`GmailApiError` that carries Google's status, machine-readable reason,
and message. Mapping those errors onto Basil's standard envelopes is
:mod:`error_mapping`'s job, and shaping the JSON for the agent is
:mod:`message_shaping`'s.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
"""Every Gmail call is made for the signed-in user (``me``); the connector never addresses another mailbox."""

GMAIL_API_TIMEOUT_SECONDS = 25.0
"""Per-request deadline. Below the 30s budget ``MCPClientService`` gives a whole tool call, so a slow request reports its own timeout first."""


class ToolArgumentError(ValueError):
    """The arguments cannot be acted on; the text is written for the agent and is safe to show it."""


class GmailApiError(Exception):
    """A non-success response from the Gmail API."""

    def __init__(
        self,
        status_code: int,
        reason: str,
        message: str,
        payload: Optional[Dict[str, Any]] = None,
        retry_after: Optional[str] = None,
    ) -> None:
        super().__init__(f"Gmail API {status_code} {reason}: {message}")
        self.status_code = status_code
        self.reason = reason
        self.message = message
        self.payload = payload or {}
        self.retry_after = retry_after


def new_http_client() -> httpx.AsyncClient:
    """Build the HTTP client for one tool call. Tests replace this to inject a mock transport."""
    return httpx.AsyncClient(timeout=GMAIL_API_TIMEOUT_SECONDS)


def _error_reason(error_body: Dict[str, Any]) -> str:
    """Pick the most specific machine-readable reason Google supplied."""
    for detail in error_body.get("details") or []:
        reason = detail.get("reason") if isinstance(detail, dict) else None
        if reason:
            return str(reason)
    for entry in error_body.get("errors") or []:
        reason = entry.get("reason") if isinstance(entry, dict) else None
        if reason:
            return str(reason)
    return str(error_body.get("status") or "unknown")


class GmailApiClient:
    """One tool call's worth of Gmail API access. Use as an async context manager."""

    def __init__(self, access_token: str) -> None:
        self._access_token = access_token
        self._http: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "GmailApiClient":
        self._http = new_http_client()
        return self

    async def __aexit__(self, *_exc_info: Any) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send one request and return the decoded JSON object (``{}`` for an empty body)."""
        if self._http is None:
            raise RuntimeError("GmailApiClient must be used as an async context manager.")
        response = await self._http.request(
            method,
            f"{GMAIL_API_BASE_URL}{path}",
            params={key: value for key, value in (params or {}).items() if value is not None},
            json=json_body,
            headers={"Authorization": f"Bearer {self._access_token}", "Accept": "application/json"},
        )
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {}
            error_body = body.get("error") if isinstance(body, dict) else None
            if not isinstance(error_body, dict):
                error_body = {"message": response.text[:500]}
            raise GmailApiError(
                status_code=response.status_code,
                reason=_error_reason(error_body),
                message=str(error_body.get("message") or "Gmail API request failed."),
                payload=error_body,
                retry_after=response.headers.get("retry-after"),
            )
        if not response.content:
            return {}
        decoded = response.json()
        return decoded if isinstance(decoded, dict) else {"value": decoded}
