"""Deterministic payload for the setup agent's `start_connection_auth` receipt.

The agent supplies only the address the user pasted (and optionally a display name). The connector, canonical server address, and display name are derived here from that address, because the native bridge picks the sign-in flow from `connector_id` and a model-chosen value could aim one service's sign-in at a different server.
"""

from __future__ import annotations

from typing import Any, Dict

from api.services.mcp_connectors.connection_setup_plan import (
    ConnectionSetupError,
    plan_connection_setup,
)

START_CONNECTION_AUTH_TOOL_NAME = "start_connection_auth"


def normalize_start_connection_auth_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return the safe payload for a `start_connection_auth` receipt, or raise ValueError the agent can act on."""
    raw_url = payload.get("server_url") or payload.get("serverUrl")
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise ValueError(
            "start_connection_auth receipts must include mutation_payload['server_url'] with the exact server address "
            "the user gave you. Ask the user to paste the address (for example the MCP server URL from the service's "
            "documentation) and propose again."
        )
    raw_name = payload.get("friendly_name") or payload.get("friendlyName")
    try:
        plan = plan_connection_setup(raw_url, raw_name if isinstance(raw_name, str) else None)
    except ConnectionSetupError as exc:
        raise ValueError(
            f"That server address cannot be connected: {exc} Tell the user plainly, and ask for a corrected "
            "https:// address if they still want to connect it."
        ) from exc

    if plan.already_connected:
        raise ValueError(
            f"{plan.existing_friendly_name or 'That server'} is already connected. Do not propose it again; "
            "tell the user it is connected and, if sign-in has expired, that they can reconnect it from the "
            "Connections section of Settings."
        )

    return {
        "connector_id": plan.connector_id,
        "server_url": plan.server_url,
        "friendly_name": plan.friendly_name,
    }
