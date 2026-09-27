"""Credential/status evaluation for MCP connections."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from api.core.models.preferences import MCPConnectionRecord
from api.services.agent_processing.tools.external_services.external_connection_capability import (
    apply_server_metadata_to_record,
)
from api.services.mcp_connectors.error_normalizer import ERROR_KIND_AUTH_EXPIRED
from api.services.mcp_connectors.generic_oauth_token_refresh import (
    refresh_generic_oauth_access_token,
)
from api.services.mcp_connectors.mcp_client_service import MCPClientService
from api.services.mcp_connectors.oauth_coordinator import OAuthCoordinator
from api.services.mcp_connectors.slack_pkce_coordinator import SlackPKCECoordinator
from api.services.mcp_connectors.slack_token_service import (
    is_slack_connection,
    refresh_slack_token,
    validate_slack_access_token,
)
from api.services.mcp_connectors.swift_token_bridge import _request_access_token_from_swift

logger = logging.getLogger(__name__)

STATUS_HEALTHY = "healthy"
STATUS_NEEDS_RECONNECT = "needs_reconnect"
STATUS_TOKEN_UNAVAILABLE = "token_unavailable"
STATUS_ERROR = "error"


@dataclass
class ConnectionStatusCheckResult:
    """Secret-free result of evaluating one connection's credentials."""

    status: str
    message: str
    checked_at: datetime
    refreshed_credentials: bool = False
    user_action_required: Optional[str] = None
    server: Optional[dict[str, Any]] = None


async def check_connection_status(
    record: MCPConnectionRecord,
    *,
    mcp_client: Optional[MCPClientService] = None,
    oauth_coordinator: Optional[OAuthCoordinator] = None,
    slack_coordinator: Optional[SlackPKCECoordinator] = None,
) -> ConnectionStatusCheckResult:
    """Evaluate whether a connection can currently authenticate."""
    if is_slack_connection(record):
        return await _check_slack_status(
            record,
            slack_coordinator=slack_coordinator or SlackPKCECoordinator(),
        )
    return await _check_generic_mcp_status(
        record,
        mcp_client=mcp_client or MCPClientService(),
        oauth_coordinator=oauth_coordinator or OAuthCoordinator(),
    )


def apply_status_result_to_record(
    record: MCPConnectionRecord,
    result: ConnectionStatusCheckResult,
) -> None:
    """Persist the secret-free status summary onto the connection record."""
    record.last_connection_check_at = result.checked_at
    record.last_connection_status = result.status
    record.last_connection_status_message = result.message
    apply_server_metadata_to_record(record, result.server)


async def _check_slack_status(
    record: MCPConnectionRecord,
    *,
    slack_coordinator: SlackPKCECoordinator,
) -> ConnectionStatusCheckResult:
    checked_at = datetime.utcnow()
    token_outcome = await _request_access_token_from_swift(record.id)
    if not token_outcome.access_token:
        return ConnectionStatusCheckResult(
            status=STATUS_TOKEN_UNAVAILABLE,
            message=(
                token_outcome.message
                or "Basil could not retrieve a Slack access token for this connection."
            ),
            checked_at=checked_at,
            user_action_required=token_outcome.user_action_required,
        )

    validation = await validate_slack_access_token(token_outcome.access_token)
    if validation.kind == "valid":
        return ConnectionStatusCheckResult(
            status=STATUS_HEALTHY,
            message="Slack credentials are valid.",
            checked_at=checked_at,
        )

    refresh_outcome = await refresh_slack_token(
        connection_id=record.id,
        coordinator=slack_coordinator,
    )
    if refresh_outcome.kind == "refreshed" and refresh_outcome.access_token:
        retry_validation = await validate_slack_access_token(refresh_outcome.access_token)
        if retry_validation.kind == "valid":
            return ConnectionStatusCheckResult(
                status=STATUS_HEALTHY,
                message="Slack credentials were refreshed and validated.",
                checked_at=checked_at,
                refreshed_credentials=True,
            )
        return ConnectionStatusCheckResult(
            status=STATUS_NEEDS_RECONNECT,
            message=(
                retry_validation.message
                or "Slack rejected the refreshed credentials."
            ),
            checked_at=checked_at,
            refreshed_credentials=True,
            user_action_required="Reconnect Slack in Settings -> Connections.",
        )

    return ConnectionStatusCheckResult(
        status=STATUS_NEEDS_RECONNECT,
        message=(
            refresh_outcome.message
            or validation.message
            or "Slack credentials could not be refreshed."
        ),
        checked_at=checked_at,
        user_action_required="Reconnect Slack in Settings -> Connections.",
    )


async def _check_generic_mcp_status(
    record: MCPConnectionRecord,
    *,
    mcp_client: MCPClientService,
    oauth_coordinator: OAuthCoordinator,
) -> ConnectionStatusCheckResult:
    checked_at = datetime.utcnow()
    token_outcome = await _request_access_token_from_swift(record.id)
    if not token_outcome.access_token:
        return ConnectionStatusCheckResult(
            status=STATUS_TOKEN_UNAVAILABLE,
            message=(
                token_outcome.message
                or "Basil could not retrieve an access token for this connection."
            ),
            checked_at=checked_at,
            user_action_required=token_outcome.user_action_required,
        )

    envelope = await mcp_client.list_tools(record.server_url, token_outcome.access_token)
    if envelope.get("ok"):
        return _healthy_from_envelope(envelope, checked_at, refreshed=False)

    error = envelope.get("error") or {}
    if error.get("kind") not in {ERROR_KIND_AUTH_EXPIRED, "auth_unavailable"}:
        return _error_from_envelope(error, checked_at)

    refreshed_token = await refresh_generic_oauth_access_token(
        record,
        oauth_coordinator=oauth_coordinator,
    )
    if not refreshed_token:
        return ConnectionStatusCheckResult(
            status=STATUS_NEEDS_RECONNECT,
            message=(
                error.get("message")
                or "The MCP server rejected the current credentials."
            ),
            checked_at=checked_at,
            user_action_required=(
                error.get("user_action_required")
                or "Reconnect this server in Settings -> Connections."
            ),
        )

    retry_envelope = await mcp_client.list_tools(record.server_url, refreshed_token)
    if retry_envelope.get("ok"):
        return _healthy_from_envelope(retry_envelope, checked_at, refreshed=True)

    retry_error = retry_envelope.get("error") or {}
    if retry_error.get("kind") in {ERROR_KIND_AUTH_EXPIRED, "auth_unavailable"}:
        return ConnectionStatusCheckResult(
            status=STATUS_NEEDS_RECONNECT,
            message=(
                retry_error.get("message")
                or "The MCP server rejected refreshed credentials."
            ),
            checked_at=checked_at,
            refreshed_credentials=True,
            user_action_required=(
                retry_error.get("user_action_required")
                or "Reconnect this server in Settings -> Connections."
            ),
        )
    return _error_from_envelope(retry_error, checked_at, refreshed=True)


def _healthy_from_envelope(
    envelope: dict[str, Any],
    checked_at: datetime,
    *,
    refreshed: bool,
) -> ConnectionStatusCheckResult:
    result = envelope.get("result") or {}
    tools = result.get("tools") or []
    return ConnectionStatusCheckResult(
        status=STATUS_HEALTHY,
        message=f"Connection validated successfully ({len(tools)} tool(s) visible).",
        checked_at=checked_at,
        refreshed_credentials=refreshed,
        server=result.get("server"),
    )


def _error_from_envelope(
    error: dict[str, Any],
    checked_at: datetime,
    *,
    refreshed: bool = False,
) -> ConnectionStatusCheckResult:
    return ConnectionStatusCheckResult(
        status=STATUS_ERROR,
        message=error.get("message") or "Connection status check failed.",
        checked_at=checked_at,
        refreshed_credentials=refreshed,
        user_action_required=error.get("user_action_required"),
    )


__all__ = [
    "ConnectionStatusCheckResult",
    "STATUS_ERROR",
    "STATUS_HEALTHY",
    "STATUS_NEEDS_RECONNECT",
    "STATUS_TOKEN_UNAVAILABLE",
    "apply_status_result_to_record",
    "check_connection_status",
]
