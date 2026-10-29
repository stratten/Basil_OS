"""Which transport serves a Gmail connection."""

from __future__ import annotations

import logging
import os
from typing import Literal

GMAIL_TRANSPORT_ENV = "BASIL_GMAIL_TRANSPORT"
"""Set to ``mcp`` or ``direct`` to override the saved setting, for example to pin a transport on a development machine."""

GmailTransport = Literal["direct", "mcp"]

logger = logging.getLogger(__name__)


def gmail_transport() -> GmailTransport:
    """The transport Gmail calls use: the environment override if set, otherwise the saved Settings choice, otherwise ``direct``.

    ``direct`` calls the Gmail API, which serves every Google Cloud project that has turned it on. ``mcp`` calls Google's hosted Gmail MCP server, which only answers projects enrolled in the Google Workspace Developer Preview Program. The connection record, sign-in scopes, tokens, and tool names are identical on both paths, so switching never requires signing in again.
    """
    override = os.environ.get(GMAIL_TRANSPORT_ENV, "").strip().lower()
    if override in ("direct", "mcp"):
        return override  # type: ignore[return-value]
    try:
        from api.core.preferences.preferences_io import load_preferences

        return load_preferences().connections.gmail_transport
    except Exception:
        logger.warning("Could not read the saved Gmail transport; using the direct Gmail API.", exc_info=True)
        return "direct"


def gmail_uses_direct_api() -> bool:
    """True when Gmail tools run against the Gmail API."""
    return gmail_transport() == "direct"
