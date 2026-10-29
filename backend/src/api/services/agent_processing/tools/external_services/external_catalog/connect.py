"""The `connect_server` action: lets the core agent set up a remote MCP connection the user asked for.

The pasted address is validated and classified by the same deterministic plan the setup assistant uses. The user always approves through the execution approval card, which cannot be skipped by "always approve", read-only auto-approval, or a remembered pattern, and cannot itself be remembered. After approval the sign-in opens in the user's own browser; credentials are never typed into the chat and never seen by the agent.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from api.services.mcp_connectors.connection_setup_plan import (
    ConnectionSetupError,
    ConnectionSetupPlan,
    plan_connection_setup,
)
from api.services.mcp_connectors.connection_setup_runner import run_connection_setup

from .envelopes import (
    make_external_catalog_invalid_arguments,
    make_external_catalog_permission_denied,
)

logger = logging.getLogger(__name__)

CONNECT_APPROVAL_SOURCE = "external_catalog_connect"
CONNECT_EXECUTION_TYPE = "mcp_connection_setup"

_FLOW_DESCRIPTIONS = {
    "github_device": "GitHub's one-time device code, entered on github.com in your browser",
    "slack_pkce": "Slack's sign-in page in your browser",
    "oauth": "the service's own sign-in page in your browser",
}


def describe_connection_approval(plan: ConnectionSetupPlan) -> str:
    """The sentence shown on the approval card, naming the exact address and how sign-in will happen."""
    return (
        f"Connect {plan.friendly_name} at {plan.server_url}. "
        f"You will sign in through {_FLOW_DESCRIPTIONS[plan.flow]}; Basil never sees your password."
    )


async def request_connection_setup_approval(plan: ConnectionSetupPlan) -> bool:
    """Ask the user to approve connecting this service; any failure to ask counts as a denial."""
    try:
        from api.services.agent_processing.tools.safety.execution_approval_service import (
            ExecutionApprovalService,
        )
    except Exception as exc:
        logger.warning("ExecutionApprovalService unavailable; connection setup denied (%s)", exc)
        return False

    runtime_context: Dict[str, Any] = {}
    try:
        from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context

        current_context = get_current_agent_context()
        if isinstance(current_context, dict):
            runtime_context = current_context
    except Exception as exc:
        logger.debug("Could not read agent runtime context for connection approval: %s", exc)

    approval_context: Dict[str, Any] = {
        "source": CONNECT_APPROVAL_SOURCE,
        "execution_type": CONNECT_EXECUTION_TYPE,
        "require_explicit_approval": True,
        "purpose": describe_connection_approval(plan),
        "description": "Connecting a service needs your explicit approval every time",
        "friendly_name": plan.friendly_name,
        "server_url": plan.server_url,
    }
    agent_task_id = runtime_context.get("agent_task_id")
    if agent_task_id:
        approval_context["agent_task_id"] = agent_task_id

    approval_service = ExecutionApprovalService(websocket_manager=runtime_context.get("websocket_manager"))
    command = f'connect-mcp-server "{plan.friendly_name}" {plan.server_url}'
    try:
        approved, _remember, _pattern_type = await approval_service.request_approval(command, context=approval_context)
        return bool(approved)
    except Exception as exc:
        logger.warning("Connection approval flow raised; treating as denied: %s", exc)
        return False


async def connect_external_catalog_server(
    server_url: Optional[str],
    friendly_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate the pasted address, get the user's approval, and start the sign-in."""
    if not server_url or not server_url.strip():
        return make_external_catalog_invalid_arguments(
            "connect_server requires server_url: the exact MCP server address the user gave you. "
            "Ask the user to paste it; never guess an address."
        )
    try:
        plan = plan_connection_setup(server_url, friendly_name)
    except ConnectionSetupError as exc:
        return make_external_catalog_invalid_arguments(f"That server address cannot be connected: {exc}")

    if plan.already_connected:
        return {
            "ok": True,
            "result": {
                "status": "already_connected",
                "connection_id": plan.existing_connection_id,
                "service": plan.existing_friendly_name or plan.friendly_name,
                "message": "This server is already connected. Use action='describe_server' with this connection_id.",
            },
        }

    if not await request_connection_setup_approval(plan):
        return make_external_catalog_permission_denied(
            "connect_server",
            "the user did not approve connecting this service",
        )

    try:
        started = await run_connection_setup(plan)
    except ConnectionSetupError as exc:
        return {
            "ok": False,
            "error": {
                "kind": "connection_setup_failed",
                "message": str(exc),
                "retryable": False,
                "user_action_required": "Add the connection in Settings → Connections instead.",
                "raw": {},
            },
        }
    if started.get("status") == "needs_manual_token":
        started = {
            **started,
            "message": (
                f"{plan.friendly_name} does not offer browser sign-in that Basil can start automatically. "
                "If the service gives out a bearer token or API key, call action='connect_with_token' with the same server_url: "
                "Basil shows an overlay in Paprika for the user to type the token, so it never enters the chat."
            ),
        }
    return {"ok": True, "result": started}
