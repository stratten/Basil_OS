"""Starts a connection sign-in from inside the backend, for agents that have no Settings screen to click in.

The Settings screen drives each sign-in method through the Basil client. An agent running in the backend has no client round trip of its own, so this module starts the same flows through the same route functions, hands the sign-in page to the client to open in the user's browser, and (for GitHub, which has no browser redirect) polls in the background until the user approves.

Tokens never pass through here: each flow's existing completion path stores credentials in the macOS Keychain through the client.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Set

from fastapi import HTTPException

from api.services.mcp_connectors.backend_origin import get_backend_origin
from api.services.mcp_connectors.connection_setup_plan import (
    ConnectionSetupError,
    ConnectionSetupPlan,
)
from api.services.mcp_connectors.external_url_bridge import open_external_url_in_client

logger = logging.getLogger(__name__)

_MIN_POLL_INTERVAL_SECONDS = 2
_MAX_POLL_WINDOW_SECONDS = 900

_background_polls: Set["asyncio.Task[None]"] = set()


def _detail_message(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("kind") or "The sign-in could not start.")
    return str(detail)


async def run_connection_setup(plan: ConnectionSetupPlan) -> Dict[str, Any]:
    """Start the sign-in for an approved plan and describe what the user must do next.

    Returns a dictionary with `status` set to `sign_in_started` or `needs_manual_token`. Raises ConnectionSetupError with a user-safe message when the sign-in cannot start at all.
    """
    if plan.already_connected:
        raise ConnectionSetupError(
            f"{plan.existing_friendly_name or plan.friendly_name} is already connected."
        )
    if plan.flow == "github_device":
        return await _start_github_device_flow(plan)
    if plan.flow == "slack_pkce":
        return await _start_slack_flow(plan)
    return await _start_generic_oauth_flow(plan)


async def _start_generic_oauth_flow(plan: ConnectionSetupPlan) -> Dict[str, Any]:
    from api.routes.connections.models import StartOAuthRequest
    from api.routes.connections.routes import begin_oauth_sign_in, oauth_redirect_uri_for

    origin = get_backend_origin()
    if origin is None:
        raise ConnectionSetupError(
            "Basil has not finished starting its local connection service yet. Try again in a moment."
        )
    try:
        started = await begin_oauth_sign_in(
            StartOAuthRequest(server_url=plan.server_url, friendly_name=plan.friendly_name),
            oauth_redirect_uri_for(origin),
        )
    except HTTPException as exc:
        if exc.status_code == 400:
            return {
                "status": "needs_manual_token",
                "service": plan.friendly_name,
                "server_url": plan.server_url,
                "message": (
                    f"{plan.friendly_name} does not offer browser sign-in that Basil can start automatically ({_detail_message(exc)}). "
                    "If the service gives out a bearer token, the user can add it in the Connections section of Settings "
                    "under Manual Bearer Token Server. The token must be typed there, never into the chat."
                ),
            }
        raise ConnectionSetupError(_detail_message(exc)) from exc
    return await _describe_browser_sign_in(plan, started.authorization_url)


async def _start_slack_flow(plan: ConnectionSetupPlan) -> Dict[str, Any]:
    from api.routes.connections.models import SlackStartOAuthRequest
    from api.routes.connections.slack_routes import slack_start_oauth

    try:
        started = await slack_start_oauth(
            SlackStartOAuthRequest(friendly_name=plan.friendly_name, server_url=plan.server_url)
        )
    except HTTPException as exc:
        raise ConnectionSetupError(_detail_message(exc)) from exc
    return await _describe_browser_sign_in(plan, started.authorization_url)


async def _describe_browser_sign_in(plan: ConnectionSetupPlan, authorization_url: str) -> Dict[str, Any]:
    opened = await open_external_url_in_client(authorization_url, purpose="connection_sign_in")
    result: Dict[str, Any] = {
        "status": "sign_in_started",
        "flow": plan.flow,
        "service": plan.friendly_name,
        "server_url": plan.server_url,
        "browser_opened": opened,
        "message": (
            f"The {plan.friendly_name} sign-in page opened in the user's browser. Ask them to finish signing in there and tell you when they are done."
            if opened
            else f"The {plan.friendly_name} sign-in page could not be opened automatically. Give the user the link to open themselves."
        ),
    }
    if not opened:
        result["authorization_url"] = authorization_url
    return result


async def _start_github_device_flow(plan: ConnectionSetupPlan) -> Dict[str, Any]:
    from api.routes.connections.models import GitHubDeviceFlowStartRequest
    from api.routes.connections.routes import start_github_device_flow

    try:
        started = await start_github_device_flow(
            GitHubDeviceFlowStartRequest(friendly_name=plan.friendly_name, server_url=plan.server_url)
        )
    except HTTPException as exc:
        raise ConnectionSetupError(_detail_message(exc)) from exc

    opened = await open_external_url_in_client(started.verification_uri, purpose="connection_sign_in")
    _track_background_poll(
        asyncio.create_task(
            _poll_github_device_flow(started.device_code, started.interval, started.expires_in),
            name=f"github-device-flow-{started.device_code[:6]}",
        )
    )
    return {
        "status": "sign_in_started",
        "flow": plan.flow,
        "service": plan.friendly_name,
        "server_url": plan.server_url,
        "browser_opened": opened,
        "user_code": started.user_code,
        "verification_uri": started.verification_uri,
        "message": (
            f"GitHub needs this one-time code entered on its device page: {started.user_code}. "
            + (
                "The page opened in the user's browser. "
                if opened
                else f"The page could not be opened automatically, so give the user this link: {started.verification_uri}. "
            )
            + "Basil finishes the connection by itself once they approve; ask them to tell you when they are done."
        ),
    }


def _track_background_poll(task: "asyncio.Task[None]") -> None:
    _background_polls.add(task)
    task.add_done_callback(_background_polls.discard)


async def _poll_github_device_flow(device_code: str, interval: int, expires_in: int) -> None:
    from api.routes.connections.models import GitHubDeviceFlowPollRequest
    from api.routes.connections.routes import poll_github_device_flow

    waited = 0
    delay = max(int(interval or 0), _MIN_POLL_INTERVAL_SECONDS)
    window = min(max(int(expires_in or 0), delay), _MAX_POLL_WINDOW_SECONDS)
    while waited < window:
        await asyncio.sleep(delay)
        waited += delay
        try:
            response = await poll_github_device_flow(GitHubDeviceFlowPollRequest(device_code=device_code))
        except HTTPException as exc:
            logger.info("GitHub device sign-in ended without a connection: %s", _detail_message(exc))
            return
        except Exception:
            logger.exception("Unexpected failure while polling the GitHub device sign-in")
            return
        if response.status == "ok":
            logger.info("GitHub device sign-in completed for an agent-started connection")
            return
        delay = max(int(response.interval or delay), _MIN_POLL_INTERVAL_SECONDS)
    logger.info("GitHub device sign-in expired before the user approved it")


def pending_background_poll_count() -> int:
    """Number of agent-started GitHub sign-ins still waiting for approval (used by tests)."""
    return len(_background_polls)


__all__ = [
    "pending_background_poll_count",
    "run_connection_setup",
]
