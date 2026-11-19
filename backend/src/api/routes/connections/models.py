"""Request and response models for connection routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_serializer, field_validator

from api.core.models.preferences import MCPToolPolicy
from api.services.conversation.conversation_timestamps import utc_iso_timestamp
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
    StarterServer(
        id="gmail",
        friendly_name="Gmail",
        server_url="https://gmailmcp.googleapis.com/mcp/v1",
        description=(
            "Search, read, draft, label, trash, and send email. Sign in "
            "with your Google account; Basil requests Gmail modify access "
            "(no permanent delete). Moving to Trash and sending always ask "
            "for your approval first."
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


class CompanionStatusDTO(BaseModel):
    """A local server's background program, as the Connections tab shows it."""

    command_summary: str
    start_with_basil: bool
    fixed_port: Optional[int] = None
    secret_env: List[str] = Field(default_factory=list)
    status: str = "stopped"
    port: Optional[int] = None
    last_error: Optional[str] = None
    log_tail: str = ""
    restart_count: int = 0
    has_probe: bool = False
    health_phase: Optional[str] = Field(default=None, description="starting, ready, needs_action or failed, from the program's own status page; absent when it has no probe or is not running")
    health_message: Optional[str] = None
    action_kind: Optional[str] = Field(default=None, description="qr when the person must scan a code")
    action_value: Optional[str] = Field(default=None, description="The code to scan. Held in memory only and never stored.")
    action_expires_at: Optional[str] = None


class RequirementStatusDTO(BaseModel):
    """A program a local server's recipe needs installed."""

    name: str
    reason: str
    for_method: str
    install_command: Optional[str] = Field(default=None, description="The exact command Basil runs when the person chooses Install; absent when they must install it themselves")


class ArtifactStatusDTO(BaseModel):
    """One file a local server's recipe puts in place, with every address and command that may produce it."""

    name: str
    expects: str
    ready: bool
    sources: List[str] = Field(default_factory=list, description="One plain-language line per way of obtaining it, including every address, hash, commit and build command")


class InstallStatusDTO(BaseModel):
    """A local server's recipe and how far its preparation has got."""

    phase: str
    message: str = ""
    ready: bool
    active: bool
    artifact: Optional[str] = None
    requirement: Optional[str] = None
    can_install: bool = False
    detail: Optional[str] = None
    requirements: List[RequirementStatusDTO] = Field(default_factory=list)
    artifacts: List[ArtifactStatusDTO] = Field(default_factory=list)


class LocalServerDTO(BaseModel):
    """What the Connections tab needs about a local server beyond the shared connection fields. Secret names only; a value never leaves the Keychain."""

    command_summary: str
    source_url: Optional[str] = None
    secret_env: List[str] = Field(default_factory=list)
    companion: Optional[CompanionStatusDTO] = None
    install: Optional[InstallStatusDTO] = None


ConnectionAuthKind = Literal["oauth", "slack", "github_device", "manual_token", "local"]


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
    last_successful_use_at: Optional[datetime] = None
    last_connection_status: Optional[str] = None
    last_connection_status_message: Optional[str] = None
    server_name: Optional[str] = None
    server_instructions: Optional[str] = None
    server_icon_data_url: Optional[str] = None
    auth_kind: ConnectionAuthKind = "manual_token"
    tools: List[CachedToolDTO] = Field(default_factory=list)
    local_server: Optional[LocalServerDTO] = None

    @field_serializer("last_connection_check_at", "last_successful_use_at")
    def _serialize_utc_instant(self, value: Optional[datetime]) -> Optional[str]:
        """These two are stored as naive UTC, so they are sent with an explicit UTC marker that clients convert to local time."""
        return utc_iso_timestamp(value)


class CompanionSpecRequest(BaseModel):
    """A background program that must run beside a local server."""

    command: str
    args: List[str] = Field(default_factory=list)
    cwd: Optional[str] = None
    env: Dict[str, str] = Field(default_factory=dict, description="Non-secret environment variables only.")
    secret_env: List[str] = Field(default_factory=list, description="Names only. The person types each value into Settings and it is kept in the Keychain.")
    start_with_basil: bool = True
    fixed_port: Optional[int] = None
    probe: Optional[Dict[str, Any]] = Field(default=None, description="How Basil reads the program's own status page. Checked by the backend; see the local server recipe reference.")


class RegisterLocalServerRequest(BaseModel):
    """A local MCP server Basil launches itself over standard input and output."""

    friendly_name: str
    command: str
    args: List[str] = Field(default_factory=list)
    cwd: Optional[str] = None
    env: Dict[str, str] = Field(default_factory=dict, description="Non-secret environment variables only.")
    description: Optional[str] = None
    source_url: Optional[str] = None
    secret_env: List[str] = Field(default_factory=list, description="Names only. Values are saved in the Keychain by the Settings app before this call.")
    companion: Optional[CompanionSpecRequest] = None
    install: Optional[Dict[str, Any]] = Field(default=None, description="A recipe of programs the server needs and files Basil downloads or builds for it. Checked by the backend; see the local server recipe reference.")
    connection_id: Optional[str] = Field(default=None, description="A UUID chosen by the caller so secret values can be saved under it first.")


class InstallRequirementRequest(BaseModel):
    """The person's choice to run one requirement's install command."""

    name: str
    command: str = Field(..., description="The exact install command the person was shown. The request is refused if it no longer matches the recipe.")


class ConnectionsListResponse(BaseModel):
    connections: List[ConnectionDTO]


class StartOAuthRequest(BaseModel):
    server_url: str
    friendly_name: str
    description: Optional[str] = None
    requested_scopes: Optional[List[str]] = None
    connection_id: Optional[str] = None


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
    connection_id: Optional[str] = None


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
    connection_id: Optional[str] = None


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

    @field_validator("started_at", "completed_at", mode="before")
    @classmethod
    def _mark_utc(cls, value: Any) -> Any:
        """Call-log times are stored as naive UTC, so they are sent with an explicit UTC marker that clients convert to local time."""
        return utc_iso_timestamp(value)


class CallLogResponse(BaseModel):
    entries: List[CallLogEntry]


__all__ = [
    "STARTER_SERVERS",
    "CallLogEntry",
    "CallLogResponse",
    "CachedToolDTO",
    "ConnectionAuthKind",
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
