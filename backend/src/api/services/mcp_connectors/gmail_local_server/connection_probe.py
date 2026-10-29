"""Ask Google what a Gmail sign-in actually grants, so a connection check proves more than "the tool list loaded".

The direct Gmail connector's tool catalog is built in-process, so listing it never contacts Google. Without this probe a connection whose token has been revoked, expired, or issued without the Gmail permission Basil needs would still report healthy. The probe makes two read-only requests: Google's token-info endpoint, which returns the scopes the token really carries, and the Gmail profile endpoint, which names the signed-in mailbox and proves the Gmail API is reachable. It reads no mail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from . import gmail_api
from .gmail_api import GmailApiClient, GmailApiError

TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
"""Called with POST so the access token travels in the request body, never in a URL that an HTTP client could log."""

MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
FULL_ACCESS_SCOPE = "https://mail.google.com/"
"""Google's full-access Gmail scope. It includes everything ``gmail.modify`` allows."""

_SCOPE_PREFIX = "https://www.googleapis.com/auth/"


@dataclass(frozen=True)
class ConnectionDetails:
    """What Google reports for one Gmail access token."""

    account: Optional[str]
    granted_scopes: List[str]

    @property
    def has_required_access(self) -> bool:
        return MODIFY_SCOPE in self.granted_scopes or FULL_ACCESS_SCOPE in self.granted_scopes

    @property
    def scope_labels(self) -> List[str]:
        """Short names (``gmail.modify``) for display; the full scope URL is not useful to a person."""
        return [scope[len(_SCOPE_PREFIX) :] if scope.startswith(_SCOPE_PREFIX) else scope for scope in self.granted_scopes]


async def fetch_granted_scopes(access_token: str) -> List[str]:
    """Return the scopes Google says the token carries, or raise :class:`GmailApiError` when Google rejects the token."""
    async with gmail_api.new_http_client() as http:
        response = await http.post(TOKENINFO_URL, data={"access_token": access_token})
    if response.status_code in (400, 401):
        raise GmailApiError(401, "invalid_token", "Google does not recognize this access token.")
    if response.status_code >= 400:
        raise GmailApiError(response.status_code, "tokeninfo_failed", response.text[:200])
    body = response.json()
    scope_text = body.get("scope") if isinstance(body, dict) else None
    return sorted(set(str(scope_text or "").split()))


async def describe_connection(access_token: str) -> ConnectionDetails:
    """Return the granted scopes and signed-in mailbox, checking the scopes before spending a Gmail request."""
    scopes = await fetch_granted_scopes(access_token)
    details = ConnectionDetails(account=None, granted_scopes=scopes)
    if not details.has_required_access:
        return details
    async with GmailApiClient(access_token) as api:
        profile = await api.request("GET", "/profile")
    account = profile.get("emailAddress")
    return ConnectionDetails(account=str(account) if account else None, granted_scopes=scopes)
