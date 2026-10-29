"""The `connect_with_token` action: lets the core agent connect a service that gives out a bearer token or API key instead of a browser sign-in.

The agent only supplies the service address, a suggested name and an optional description. The address is validated by the same planner `connect_server` uses. The token itself is typed by the user into Paprika's overlay, the same kind used for command approval, which shows the destination host and lets the user edit the connection's name and description, so it never enters the chat, the model's context, the transcript or the logs. The Basil app saves the token in its Keychain vault and checks it by fetching the service's tool list, so a `connected` result means the service accepted the token. The overlay is the user's explicit approval: nothing is sent anywhere until they press Connect.

A second connection to an address that is already connected is allowed, because one service can hold several accounts or workspaces. The overlay then asks for a name that is not already used.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from api.services.mcp_connectors.connection_secret_bridge import request_token_entry
from api.services.mcp_connectors.connection_setup_plan import (
    ConnectionSetupError,
    plan_connection_setup,
)

from .envelopes import make_external_catalog_invalid_arguments


def _existing_connection_names() -> List[str]:
    """Names of every saved connection, so the overlay can refuse a duplicate name."""
    from api.core.preferences.preferences_io import load_preferences

    return [record.friendly_name for record in load_preferences().connections.mcp_connections]


async def connect_external_catalog_server_with_token(
    server_url: Optional[str],
    friendly_name: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate the address, show the token form in Paprika, and report what the user did."""
    if not server_url or not server_url.strip():
        return make_external_catalog_invalid_arguments(
            "connect_with_token requires server_url: the exact MCP server address the service gave the user. "
            "Ask the user to paste it; never guess an address."
        )
    try:
        plan = plan_connection_setup(server_url, friendly_name)
    except ConnectionSetupError as exc:
        return make_external_catalog_invalid_arguments(f"That server address cannot be connected: {exc}")

    if plan.flow == "slack_pkce":
        return make_external_catalog_invalid_arguments(
            "Slack signs in through the browser and does not use a pasted token. Use action='connect_server' for it."
        )

    outcome = await request_token_entry(
        server_url=plan.server_url,
        friendly_name=plan.friendly_name,
        description=(description or "").strip() or None,
        existing_names=_existing_connection_names(),
        already_connected_as=(plan.existing_friendly_name or plan.friendly_name) if plan.already_connected else None,
    )
    status = outcome["status"]
    if status == "connected":
        service = outcome.get("friendly_name") or plan.friendly_name
        return {
            "ok": True,
            "result": {
                "status": "connected",
                "connection_id": outcome.get("connection_id"),
                "service": service,
                "description": outcome.get("description"),
                "server_url": plan.server_url,
                "tool_count": outcome.get("tool_count"),
                "message": (
                    f"{service} is connected and the service accepted the token. "
                    "Use action='describe_server' with this connection_id to see what it can do."
                ),
            },
        }
    if status == "canceled":
        return {
            "ok": True,
            "result": {
                "status": "canceled",
                "service": plan.friendly_name,
                "message": "The user canceled the token form without connecting. Nothing was saved. Ask whether they want to try again.",
            },
        }
    return {
        "ok": False,
        "error": {
            "kind": "connection_setup_failed",
            "message": outcome.get("message") or "The connection could not be completed.",
            "retryable": True,
            "user_action_required": "Check the token and the address with the service, then ask the agent to try again.",
            "raw": {},
        },
    }
