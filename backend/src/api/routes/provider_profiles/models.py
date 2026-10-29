"""Request and response models for attended provider-profile registry configuration."""

from __future__ import annotations

from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

LaunchArgument = Annotated[str, Field(min_length=1, max_length=1024)]
EnvironmentVariableName = Annotated[str, Field(min_length=1, max_length=128)]
AuthenticationMethodID = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[\x21-\x39\x3B-\x7E]+$"),
]
RoutingHint = Annotated[str, Field(min_length=1, max_length=160)]


class WorkspaceGrantSummaryDTO(BaseModel):
    id: str
    canonical_workspace_root: str
    status: Literal["active", "revoked"]
    workspace_label: str
    description: Optional[str] = None
    routing_hints: List[RoutingHint] = Field(default_factory=list)
    revision: int = Field(ge=0)


class ProviderProfileSummaryDTO(BaseModel):
    """Outbound shape for the SwiftUI Connections tab's Provider Profiles sub-tab."""

    id: str
    display_name: str
    status: Literal["enabled", "disabled", "removed"]
    capability_state: Literal["unverified"]
    description: Optional[str] = None
    routing_hints: List[RoutingHint] = Field(default_factory=list)
    revision: int = Field(ge=0)
    has_observed_capabilities: bool
    active_workspace_grants: List[WorkspaceGrantSummaryDTO] = Field(default_factory=list)
    is_structurally_valid: bool
    validation_error: Optional[str] = None
    created_at: str
    updated_at: str


class ProviderProfilesListResponse(BaseModel):
    profiles: List[ProviderProfileSummaryDTO]


class ProviderProfileConfigurationDTO(ProviderProfileSummaryDTO):
    launch_argv: List[LaunchArgument]
    environment_allowlist: List[EnvironmentVariableName]
    authentication_method_id: Optional[AuthenticationMethodID] = None


class ProviderProfileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=120)
    launch_argv: List[LaunchArgument] = Field(min_length=1, max_length=32)
    environment_allowlist: List[EnvironmentVariableName] = Field(default_factory=list, max_length=32)
    authentication_method_id: Optional[AuthenticationMethodID] = None
    description: Optional[str] = Field(default=None, max_length=1000)
    routing_hints: List[RoutingHint] = Field(default_factory=list, max_length=8)


class ProviderProfileUpdateRequest(ProviderProfileCreateRequest):
    expected_revision: int = Field(ge=0)


class ProfileRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)


class WorkspaceGrantCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_workspace_root: str = Field(min_length=1, max_length=1024)
    workspace_label: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)
    routing_hints: List[RoutingHint] = Field(default_factory=list, max_length=8)


class WorkspaceGrantUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    workspace_label: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)
    routing_hints: List[RoutingHint] = Field(default_factory=list, max_length=8)


__all__ = [
    "ProviderProfileSummaryDTO",
    "ProviderProfileConfigurationDTO",
    "ProviderProfileCreateRequest",
    "ProviderProfileUpdateRequest",
    "ProfileRevisionRequest",
    "ProviderProfilesListResponse",
    "WorkspaceGrantCreateRequest",
    "WorkspaceGrantUpdateRequest",
    "WorkspaceGrantSummaryDTO",
]
