"""Request and response models for connection routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from api.core.models.preferences import MCPToolPolicy
from api.services.mcp_connectors.github_device_flow_coordinator import (
    GITHUB_MCP_SCOPES,
    GITHUB_MCP_SERVER_URL,
)
from api.services.mcp_connectors.slack_pkce_coordinator import (
    SLACK_DEFAULT_USER_SCOPES,
    SLACK_MCP_SERVER_URL,
)


class StarterServer(BaseModel):
    """One entry in the curated starter-server list shown in the UI."""

    id: str
    friendly_name: str
    server_url: str
    description: str


STARTER_SERVERS: List[StarterServer] = [
    StarterServer(
        id="github",
        friendly_name="GitHub",
        server_url="https://api.githubcopilot.com/mcp/",
        description=(
            "Official remote GitHub MCP server (issues, PRs, repo content). "
            "Uses GitHub OAuth device authorization."
        ),
    ),
    StarterServer(
        id="linear",
        friendly_name="Linear",
        server_url="https://mcp.linear.app/mcp",
        description="Official remote Linear MCP server (issues, projects, comments).",
    ),
    StarterServer(
        id="slack",
        friendly_name="Slack",
        server_url=SLACK_MCP_SERVER_URL,
        description=(
            "Slack tooling (search, channels, messages, canvases) via an "
            "in-process MCP server bundled with Basil. Uses Slack OAuth "
            "with PKCE; no Basil account or shared secret is required. "
            "Will switch to Slack's hosted MCP server once the Basil "
            "Slack app is approved by the Slack Marketplace; no user "
            "action required at that point."
        ),
    ),
]


class StarterServersResponse(BaseModel):
    starter_servers: List[StarterServer]


class CachedToolDTO(BaseModel):
    name: str
    description: Optional[str] = None
    is_read_only_hint: bool = False
    policy: MCPToolPolicy = "always_ask"


class ConnectionDTO(BaseModel):
    """Outbound shape for the SwiftUI Connections tab."""

    id: str
    friendly_name: str
    description: Optional[str] = None
    server_url: str
    enabled: bool
    registered_at: datetime
    last_tool_refresh_at: Optional[datetime] = None
    last_connection_check_at: Optional[datetime] = None
    last_connection_status: Optional[str] = None
    last_connection_status_message: Optional[str] = None
    server_name: Optional[str] = None
    server_instructions: Optional[str] = None
    tools: List[CachedToolDTO] = Field(default_factory=list)


class ConnectionsListResponse(BaseModel):
    connections: List[ConnectionDTO]


class StartOAuthRequest(BaseModel):
    server_url: str
    friendly_name: str
    description: Optional[str] = None
    requested_scopes: Optional[List[str]] = None


class StartOAuthResponse(BaseModel):
    state: str
    authorization_url: str


class RegisterManualTokenConnectionRequest(BaseModel):
    server_url: str
    friendly_name: str
    description: Optional[str] = None


class GitHubDeviceFlowStartRequest(BaseModel):
    friendly_name: str = "GitHub"
    server_url: str = GITHUB_MCP_SERVER_URL
    description: Optional[str] = None
    requested_scopes: Optional[List[str]] = None


class GitHubDeviceFlowStartResponse(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int
    requested_scopes: List[str]


class GitHubDeviceFlowPollRequest(BaseModel):
    device_code: str


class GitHubDeviceFlowPollResponse(BaseModel):
    status: str
    interval: Optional[int] = None
    connection: Optional[ConnectionDTO] = None
    message: Optional[str] = None


class SlackStartOAuthRequest(BaseModel):
    """Begin Slack PKCE flow from Settings/Setup Assistant."""

    friendly_name: str = "Slack"
    server_url: str = SLACK_MCP_SERVER_URL
    description: Optional[str] = None
    requested_scopes: Optional[List[str]] = None


class SlackStartOAuthResponse(BaseModel):
    """Result of beginning the Slack PKCE flow.

    The Swift client opens ``authorization_url`` in the user's browser
    and later forwards the ``code`` + ``state`` it receives via the
    ``basil://mcp/slack_oauth_callback`` custom URI to
    ``/settings/connections/slack/complete_oauth``.
    """

    state: str
    authorization_url: str
    requested_scopes: List[str] = Field(default_factory=lambda: list(SLACK_DEFAULT_USER_SCOPES))


class SlackCompleteOAuthRequest(BaseModel):
    """Slack OAuth callback payload forwarded from Swift."""

    state: str
    code: str


class SlackCompleteOAuthResponse(BaseModel):
    status: str
    connection: Optional[ConnectionDTO] = None
    message: Optional[str] = None


class ToolPolicyUpdate(BaseModel):
    tool_name: str
    policy: MCPToolPolicy


class ToolPolicyBulkUpdate(BaseModel):
    policies: List[ToolPolicyUpdate]


class ConnectionMetadataUpdateRequest(BaseModel):
    friendly_name: str
    description: Optional[str] = None


ConnectionStatusValue = Literal["healthy", "needs_reconnect", "token_unavailable", "error"]


class ConnectionStatusResponse(BaseModel):
    connection: ConnectionDTO
    status: ConnectionStatusValue
    message: str
    checked_at: datetime
    refreshed_credentials: bool = False
    user_action_required: Optional[str] = None


class CallLogEntry(BaseModel):
    id: str
    connection_id: str
    server_url: str
    tool_name: str
    arguments: Optional[Dict[str, Any]] = None
    result_classification: str
    error_kind: Optional[str] = None
    error_message: Optional[str] = None
    content_preview: Optional[str] = None
    started_at: str
    completed_at: Optional[str] = None
    agent_task_id: Optional[str] = None


class CallLogResponse(BaseModel):
    entries: List[CallLogEntry]


__all__ = [
    "STARTER_SERVERS",
    "CallLogEntry",
    "CallLogResponse",
    "CachedToolDTO",
    "ConnectionDTO",
    "ConnectionMetadataUpdateRequest",
    "ConnectionStatusResponse",
    "ConnectionsListResponse",
    "GitHubDeviceFlowPollRequest",
    "GitHubDeviceFlowPollResponse",
    "GitHubDeviceFlowStartRequest",
    "GitHubDeviceFlowStartResponse",
    "RegisterManualTokenConnectionRequest",
    "SlackCompleteOAuthRequest",
    "SlackCompleteOAuthResponse",
    "SlackStartOAuthRequest",
    "SlackStartOAuthResponse",
    "StartOAuthRequest",
    "StartOAuthResponse",
    "StarterServer",
    "StarterServersResponse",
    "ToolPolicyBulkUpdate",
    "ToolPolicyUpdate",
]
