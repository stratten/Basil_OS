"""Asks the Basil client to open a web address in the user's default browser.

The backend cannot open a browser on the user's Mac itself, and sign-in pages must open in the browser the user already trusts. Only plain https addresses are ever sent.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

from api.services.mcp_connectors.swift_token_bridge import _broadcast_to_active_connections

logger = logging.getLogger(__name__)


def is_openable_https_url(url: str) -> bool:
    """True for an absolute https address with a host, which is the only kind the client will open."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme == "https" and bool(parts.hostname) and not (parts.username or parts.password)


async def open_external_url_in_client(url: str, *, purpose: str) -> bool:
    """Send an open-in-browser request to the connected client; returns whether any client received it."""
    if not is_openable_https_url(url):
        logger.warning("Refusing to ask the client to open a non-https address (purpose=%s)", purpose)
        return False
    recipients = await _broadcast_to_active_connections(
        {"type": "open_external_url", "url": url, "purpose": purpose}
    )
    return bool(recipients)
