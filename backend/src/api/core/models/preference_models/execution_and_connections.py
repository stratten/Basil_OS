"""Execution approval, auth, connection, behavior, and memory preference models."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
import uuid

from pydantic import BaseModel, Field


class ExecutionApprovalMode(str, Enum):
    """How to handle command execution approval."""
    ALWAYS_APPROVE = "always_approve"  # No prompts, trust everything (risky but convenient)
    WHITELIST_ONLY = "whitelist_only"  # Only prompt for non-whitelisted (recommended)
    ALWAYS_PROMPT = "always_prompt"    # Always prompt before execution (safest but tedious)


class ApprovalTimeoutBehavior(str, Enum):
    """What happens when a command approval request times out."""
    WAIT_FOREVER = "wait_forever"            # No timeout; pause until the user responds
    DENY_ON_TIMEOUT = "deny_on_timeout"      # Deny execution after the timeout elapses
    RETRY_ALTERNATIVE = "retry_alternative"  # Deny + agent autonomously attempts an alternative approach


class CommandPattern(BaseModel):
    """A whitelisted command pattern."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique identifier")
    pattern: str = Field(..., description="Command pattern (can include wildcards)")
    pattern_type: str = Field(default="exact", description="Pattern matching type: 'exact', 'prefix', or 'regex'")
    description: str = Field(default="", description="Human-readable description of what this command does")
    added_date: datetime = Field(default_factory=datetime.now, description="When this pattern was added")
    last_used: Optional[datetime] = Field(default=None, description="Last time this pattern was used")
    use_count: int = Field(default=0, description="Number of times this pattern has been used")
    risk_level: str = Field(default="low", description="Risk assessment: 'low', 'medium', or 'high'")


class ToolExecutionSettings(BaseModel):
    """Settings for command execution approval and whitelisting."""
    approval_mode: ExecutionApprovalMode = Field(
        default=ExecutionApprovalMode.WHITELIST_ONLY,
        description="How to handle command execution approval"
    )
    whitelisted_commands: List[CommandPattern] = Field(
        default_factory=list,
        description="List of approved command patterns"
    )
    show_full_command_in_prompt: bool = Field(
        default=True,
        description="Show the full command in approval prompts (disable for privacy)"
    )
    remember_choice_option: bool = Field(
        default=True,
        description="Show 'Remember this choice' checkbox in approval dialogs"
    )
    auto_approve_read_only: bool = Field(
        default=False,
        description="Automatically approve read-only commands (grep, cat, ls, etc.)"
    )
    block_dangerous_patterns: bool = Field(
        default=True,
        description="Block commands that match dangerous patterns (rm -rf, sudo, etc.)"
    )
    dangerous_patterns: List[str] = Field(
        default_factory=lambda: [
            "rm -rf /",
            "sudo rm",
            "dd if=",
            "mkfs",
            "format",
            ":(){ :|:& };:",  # Fork bomb
        ],
        description="Patterns that are always blocked for safety"
    )
    safe_execution_mode: bool = Field(
        default=False,
        description="When enabled, ALL script and command execution requires explicit user approval regardless of other settings"
    )
    approval_timeout_seconds: int = Field(
        default=120,
        description="Seconds to wait for user approval before the timeout behavior applies"
    )
    timeout_behavior: ApprovalTimeoutBehavior = Field(
        default=ApprovalTimeoutBehavior.WAIT_FOREVER,
        description="What happens when a command approval request times out"
    )


class BehaviorSettings(BaseModel):
    """Behavior settings for the application."""
    start_on_startup: bool = Field(default=False, description="Launch application on system startup")
    show_notifications: bool = Field(default=True, description="Show system notifications")
    minimize_to_tray: bool = Field(default=True, description="Minimize to system tray instead of closing")
    transcription_language: str = Field(default="en", description="Default language for transcription")
    hold_enabled: bool = Field(default=True, description="Enable hold-to-record functionality")
    hold_duration: float = Field(default=0.5, description="Duration in seconds to trigger hold mode")
    enable_monitoring_at_startup: bool = Field(default=True, description="Automatically enable hotkeys monitoring when application starts")
    enable_voice_listener_at_startup: bool = Field(default=False, description="Automatically enable voice listener when application starts")
    allow_mac_contacts_for_generation: bool = Field(
        default=False,
        description="Allow backend Contacts lookup to enrich email-related generation with local macOS contact identity"
    )


class APIKeyPreference(str, Enum):
    """User preference for how to access API models."""
    BASIL_CLOUD = "basil_cloud"  # Account-backed Basil Cloud routing
    APP_KEYS = "app_keys"        # Legacy alias normalized to Basil Cloud on save
    TRIAL = "trial"              # Legacy alias normalized to Basil Cloud on save
    OWN_KEYS = "own_keys"        # User provides their own API keys
    LOCAL_ONLY = "local"         # Only use local models


class AuthSettings(BaseModel):
    """Authentication and billing settings.

    Note: Tokens and has_payment_method are stored in macOS Keychain for security.
    These fields are cached here for UI display only. The backend verifies auth
    status with the auth service before routing any billable requests.
    """
    api_key_preference: APIKeyPreference = Field(
        default=APIKeyPreference.LOCAL_ONLY,
        description="How to access API models: basil_cloud (account-backed routing), own_keys (user's keys), or local (local models only). app_keys and trial are accepted legacy aliases."
    )
    # Cached for UI display - backend verifies with auth service for actual routing decisions
    is_authenticated: bool = Field(default=False, description="Cached auth state for UI display")
    user_email: Optional[str] = Field(default=None, description="Cached user email for UI display")


MCPToolPolicy = Literal["always_allow", "always_ask", "never_allow"]


class MCPCachedTool(BaseModel):
    """A cached snapshot of a tool exposed by a registered MCP server.

    The cache is refreshed each time the user opens the connection in
    Settings or whenever ``GET /settings/connections/{id}/tools`` is hit.
    Treated as a hint for UI display + policy authoring; the agent always
    re-fetches the live tool list before dispatch.
    """
    name: str = Field(..., description="Tool name as exposed by the MCP server")
    description: Optional[str] = Field(default=None, description="Tool description from the server")
    is_read_only_hint: bool = Field(
        default=False,
        description="Server-declared hint that this tool does not mutate state (drives default policy)"
    )
    input_schema: Dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema of the tool's parameters as advertised by the server; empty when the server exposes none"
    )


class MCPConnectionRecord(BaseModel):
    """Persisted record of one registered remote MCP server.

    Tokens are NEVER stored here. They live in the macOS Keychain on the
    Swift client under account ``com.basil.mcpToken.{id}``. This record
    holds only the metadata needed to (a) re-establish the connection,
    (b) drive the Connections settings UI, and (c) evaluate per-tool
    approval policy at dispatch time.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Stable connection identifier")
    friendly_name: str = Field(..., description="Display name shown in Settings (e.g. 'Linear', 'GitHub')")
    description: Optional[str] = Field(
        default=None,
        description=(
            "User-authored description of what this connection is for "
            "(for example, which workspace/account it serves). Secret-free; "
            "surfaced to Settings and agent routing prompts."
        )
    )
    server_url: str = Field(..., description="Streamable-HTTP MCP endpoint URL")
    oauth_client_id: Optional[str] = Field(
        default=None,
        description="Client ID returned by RFC 7591 dynamic client registration"
    )
    oauth_authorization_server: Optional[str] = Field(
        default=None,
        description="Discovered authorization server base URL (RFC 8414)"
    )
    oauth_token_endpoint: Optional[str] = Field(
        default=None,
        description="Cached token endpoint URL (used for refresh)"
    )
    oauth_scopes: List[str] = Field(default_factory=list, description="Scopes granted at consent time")
    registered_at: datetime = Field(default_factory=datetime.now, description="When the connection was first registered")
    enabled: bool = Field(default=True, description="If false, the agent treats this server as unavailable")
    tool_policies: Dict[str, MCPToolPolicy] = Field(
        default_factory=dict,
        description="Per-tool approval policy keyed by tool name; missing keys fall back to defaults"
    )
    cached_tools: List[MCPCachedTool] = Field(
        default_factory=list,
        description="Last observed tool list, used by Settings UI without a live round-trip"
    )
    last_tool_refresh_at: Optional[datetime] = Field(
        default=None,
        description="When cached_tools was last populated"
    )
    last_connection_check_at: Optional[datetime] = Field(
        default=None,
        description="When Basil last evaluated whether the connection credentials worked"
    )
    last_connection_status: Optional[str] = Field(
        default=None,
        description=(
            "Last evaluated connection status. Expected values are "
            "'healthy', 'needs_reconnect', 'token_unavailable', and 'error'."
        )
    )
    last_connection_status_message: Optional[str] = Field(
        default=None,
        description="Human-readable summary from the last connection status check"
    )
    server_name: Optional[str] = Field(
        default=None,
        description=(
            "Server-advertised name from the MCP initialize handshake "
            "(serverInfo.name). Secret-free; used to identify which system this "
            "connection actually serves (e.g. a Salesforce-backed server) for "
            "agent routing. Populated on tool refresh."
        )
    )
    server_instructions: Optional[str] = Field(
        default=None,
        description=(
            "Optional server-provided usage guidance from the MCP initialize "
            "handshake (the `instructions` field). Secret-free; surfaced to the "
            "agent so it can identify when this connection is the right tool. "
            "Populated on tool refresh."
        )
    )


class ConnectionsSettings(BaseModel):
    """User-managed remote MCP connections.

    Holds the full registry of remote MCP servers the user has connected.
    The ``external_catalog`` agent tool reads from this on every
    ``list_servers`` / ``describe_server`` / ``call_tool`` invocation.
    """
    mcp_connections: List[MCPConnectionRecord] = Field(
        default_factory=list,
        description="Registered remote MCP servers"
    )


class MemoryIntelligenceSettings(BaseModel):
    """Opt-in settings for model-driven memory and skill proposal generation."""
    memory_after_task_enabled: bool = Field(default=False, description="Evaluate completed tasks for memory proposals after task completion")
    memory_daily_enabled: bool = Field(default=False, description="Run daily memory proposal evaluation")
    memory_daily_time_local: str = Field(default="03:00", description="Local HH:MM time for daily memory evaluation")
    memory_processing_model: Optional[str] = Field(default=None, description="Reasoning model id for memory evaluation; falls back to reasoning_model")
    skill_after_task_enabled: bool = Field(default=False, description="Evaluate completed tasks for reusable skill candidates after task completion")
    skill_daily_enabled: bool = Field(default=False, description="Run daily skill candidate evaluation")
    skill_daily_time_local: str = Field(default="03:00", description="Local HH:MM time for daily skill evaluation")
    skill_processing_model: Optional[str] = Field(default=None, description="Reasoning model id for skill evaluation; falls back to reasoning_model")
    skill_reconciliation_min_instances: int = Field(default=2, ge=1, description="Minimum observation_count for a pending skill candidate to be eligible for reconciliation review; below this it is treated as a single sighting")


ZETTEL_SOURCE_CATALOG_VERSION = 1

ZETTEL_SOURCE_KINDS = [
    "agent_task",
    "transcription",
    "assistant_output",
    "scheduled_run",
    "conversation",
    "screen_block",
    "meeting",
]


class ZettelSettings(BaseModel):
    """Settings for the unified event stream (zettel)."""
    # Incremented when a newly introduced source should be enabled for existing
    # preference files. It is intentionally persisted rather than inferred from
    # enabled_sources: after migration, a user must be able to disable a source
    # without the next startup adding it back.
    source_catalog_version: int = Field(default=ZETTEL_SOURCE_CATALOG_VERSION, ge=1)
    enabled_sources: List[str] = Field(
        default_factory=lambda: list(ZETTEL_SOURCE_KINDS),
        description="Which source kinds are carded into the unified event stream",
    )
    history_days: int = Field(default=30, ge=0, le=3650, description="Only card records this many days back; 0 means all history")
    # Carding: the cheap, model-free pass that creates thin cards.
    carding_enabled: bool = Field(default=True, description="Continuously card existing records into the unified event stream")
    carding_interval_minutes: int = Field(default=15, ge=1, le=1440, description="Minutes between carding passes")
    limit_per_source_per_pass: int = Field(default=500, ge=50, le=5000, description="Maximum records carded per source per pass")
    # Narrative: the model-driven pass that finalizes cards into narratives.
    narrative_enabled: bool = Field(default=True, description="Run the model finalizing pass over non-final cards")
    narrative_model: str = Field(default="", description="Model id for narrative synthesis; empty uses the default reasoning model")
    narrative_mode: str = Field(default="scheduled", description="'scheduled' for a daily run or 'continuous' for an interval")
    narrative_scheduled_time: str = Field(default="02:00", description="Local HH:MM time for the daily narrative pass in scheduled mode")
    narrative_interval_minutes: int = Field(default=30, ge=1, le=1440, description="Minutes between narrative passes in continuous mode")
    narrative_batch_size: int = Field(default=50, ge=1, le=1000, description="Cards processed per narrative pass")
    narrative_max_attempts: int = Field(default=3, ge=1, le=10, description="Failed swings before a card is marked failed")
    narrative_max_records: int = Field(default=0, ge=0, le=100000, description="Maximum cards resolved per narrative pass; 0 means no limit")
