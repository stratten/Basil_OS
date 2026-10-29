"""Validate a pasted MCP server URL and decide which connection flow it belongs to.

Both the setup agent and the core agent call this before they propose or start a connection, so a server address typed or pasted by the user is classified by the same deterministic rules everywhere. The model never chooses the flow: the flow is derived from the validated URL, because a wrong flow (for example GitHub's device flow aimed at an unrelated server) would send a credential to the wrong place.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Literal, Optional
from urllib.parse import urlsplit, urlunsplit

ConnectionFlow = Literal["github_device", "slack_pkce", "oauth"]

MAX_SERVER_URL_LENGTH = 2048
MAX_FRIENDLY_NAME_LENGTH = 80

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_LOCAL_HOST_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa")
_GENERIC_HOST_LABELS = frozenset({"www", "mcp", "api", "app", "server", "remote"})


class ConnectionSetupError(ValueError):
    """The pasted address cannot be used to set up a connection; the message is safe to show the user."""


@dataclass(frozen=True)
class ConnectionSetupPlan:
    """What Basil will do for one pasted server address."""

    server_url: str
    friendly_name: str
    flow: ConnectionFlow
    connector_id: str
    existing_connection_id: Optional[str] = None
    existing_friendly_name: Optional[str] = None

    @property
    def already_connected(self) -> bool:
        return self.existing_connection_id is not None


def normalize_server_url(raw_url: str) -> str:
    """Return the canonical https form of a pasted address, or raise ConnectionSetupError with the reason."""
    if not isinstance(raw_url, str):
        raise ConnectionSetupError("The server address must be text.")
    candidate = raw_url.strip()
    if not candidate:
        raise ConnectionSetupError("The server address is empty.")
    if len(candidate) > MAX_SERVER_URL_LENGTH:
        raise ConnectionSetupError("The server address is too long.")
    if _CONTROL_CHARACTERS.search(candidate) or re.search(r"\s", candidate):
        raise ConnectionSetupError("The server address contains spaces or hidden characters.")
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parts = urlsplit(candidate)
    if parts.scheme.lower() != "https":
        raise ConnectionSetupError("Only secure https:// server addresses can be connected.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise ConnectionSetupError("The server address has no host name.")
    if parts.username or parts.password:
        raise ConnectionSetupError("The server address must not contain a user name or password.")
    _reject_non_public_host(host)
    try:
        port = parts.port
    except ValueError as exc:
        raise ConnectionSetupError("The server address has an invalid port.") from exc

    netloc = host if port in (None, 443) else f"{host}:{port}"
    path = parts.path or "/"
    return urlunsplit(("https", netloc, path, parts.query, ""))


def _reject_non_public_host(host: str) -> None:
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        address = None
    if address is not None:
        if not address.is_global:
            raise ConnectionSetupError("That address points at this computer or a private network, not a public MCP server.")
        return
    if "." not in host or host == "localhost" or host.endswith(_LOCAL_HOST_SUFFIXES):
        raise ConnectionSetupError("That address points at this computer or a private network, not a public MCP server.")


def comparable_server_url(url: str) -> str:
    """Form used to compare two addresses for equality: scheme and host case-folded, trailing slash and fragment ignored."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def derive_friendly_name(server_url: str) -> str:
    """A readable default name from the host, such as 'Notion' for https://mcp.notion.com/mcp."""
    host = (urlsplit(server_url).hostname or "").lower()
    labels = [label for label in host.split(".") if label]
    meaningful = [label for label in labels[:-1] if label not in _GENERIC_HOST_LABELS]
    chosen = meaningful[-1] if meaningful else (labels[0] if labels else "MCP server")
    return chosen.replace("-", " ").replace("_", " ").title()


def clean_friendly_name(raw_name: Optional[str], server_url: str) -> str:
    """Use the supplied name when it is usable, otherwise derive one from the address."""
    cleaned = _CONTROL_CHARACTERS.sub(" ", raw_name or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)[:MAX_FRIENDLY_NAME_LENGTH].strip()
    return cleaned or derive_friendly_name(server_url)


def plan_connection_setup(
    raw_server_url: str,
    friendly_name: Optional[str] = None,
    *,
    registered_connections: Optional[list] = None,
) -> ConnectionSetupPlan:
    """Validate the pasted address and return the flow it belongs to.

    `registered_connections` is the list of existing MCPConnectionRecord entries; it is loaded from preferences when omitted so a caller cannot forget the duplicate check.
    """
    from api.routes.connections.models import STARTER_SERVERS
    from api.services.mcp_connectors.slack_local_server import LOCAL_SLACK_SENTINEL_URL

    server_url = normalize_server_url(raw_server_url)
    comparable = comparable_server_url(server_url)

    starter = next(
        (entry for entry in STARTER_SERVERS if comparable_server_url(entry.server_url) == comparable),
        None,
    )
    if starter is not None:
        flow: ConnectionFlow = {"github": "github_device", "slack": "slack_pkce"}.get(starter.id, "oauth")
        resolved_url = starter.server_url
        connector_id = starter.id
        resolved_name = clean_friendly_name(friendly_name, resolved_url) if friendly_name else starter.friendly_name
    else:
        flow = "oauth"
        resolved_url = server_url
        connector_id = "custom"
        resolved_name = clean_friendly_name(friendly_name, resolved_url)

    if registered_connections is None:
        from api.core.preferences.preferences_io import load_preferences

        registered_connections = list(load_preferences().connections.mcp_connections)

    existing = None
    for record in registered_connections:
        record_url = comparable_server_url(record.server_url)
        if record_url == comparable_server_url(resolved_url) or (
            flow == "slack_pkce" and record_url == comparable_server_url(LOCAL_SLACK_SENTINEL_URL)
        ):
            existing = record
            break

    return ConnectionSetupPlan(
        server_url=resolved_url,
        friendly_name=resolved_name,
        flow=flow,
        connector_id=connector_id,
        existing_connection_id=existing.id if existing else None,
        existing_friendly_name=existing.friendly_name if existing else None,
    )
