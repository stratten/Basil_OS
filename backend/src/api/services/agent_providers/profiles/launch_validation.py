"""Structural and workspace-grant validation for attended generic ACP provider launches.

This module turns an already-persisted provider profile and workspace grant (Package 1A) plus a caller-supplied candidate filesystem path into a `ValidatedProviderLaunchRequest`. It performs no persistence, no process launch, and no network I/O. It only reads through `ProviderRunRepository` and inspects the local filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Mapping

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.profile_repository import ProviderProfileRepository
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.run_repository import ProviderRunRepository
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.errors import (
    ProviderRunPersistenceError,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.validation import (
    _validate_optional_authentication_method_id,
)


_SECRET_ARG_FLAGS = (
    "--api-key",
    "--apikey",
    "--token",
    "--secret",
    "--password",
    "--credential",
    "--authorization",
)

_SECRET_ARG_PREFIXES = ("sk-", "sk_", "ghp_", "github_pat_")


class ProviderLaunchValidationError(RuntimeError):
    """A provider profile, workspace grant, or candidate path fails validation."""


@dataclass(frozen=True)
class ValidatedProviderLaunchRequest:
    """A launchable-but-not-yet-launched provider request.

    This value object carries everything a later package needs to actually launch a provider, but this package never constructs a process from it.
    """

    provider_profile_id: str
    display_name: str
    launch_argv: tuple[str, ...]
    environment_allowlist: tuple[str, ...]
    authentication_method_id: str | None
    workspace_grant_id: str
    resolved_workspace_root: str
    capability_state: str


@dataclass(frozen=True)
class ValidatedProviderProfileFields:
    """The subset of a provider profile's own fields that are structurally valid.

    Package 5C.1 uses this independently of any workspace grant or candidate path to
    present validation state in a read-only inventory.
    """

    display_name: str
    launch_argv: tuple[str, ...]
    environment_allowlist: tuple[str, ...]
    authentication_method_id: str | None
    capability_state: str


@dataclass(frozen=True)
class WorkspaceGrantSummary:
    id: str
    canonical_workspace_root: str
    status: str
    workspace_label: str
    description: str | None
    routing_hints: tuple[str, ...]
    revision: int


@dataclass(frozen=True)
class ProviderProfileSummary:
    id: str
    display_name: str
    status: str
    capability_state: str
    description: str | None
    routing_hints: tuple[str, ...]
    revision: int
    observed_capabilities: dict[str, Any] | None
    active_workspace_grants: tuple[WorkspaceGrantSummary, ...]
    is_structurally_valid: bool
    validation_error: str | None
    created_at: str
    updated_at: str


def validate_profile_structure(
    profile: Mapping[str, object], *, profile_id: str
) -> ValidatedProviderProfileFields:
    """Validate a provider profile's own structural fields.

    Does not check `profile["status"]` — enablement is a separate, independently
    displayed signal from structural validity, so callers that require an enabled
    profile must check `profile["status"]` themselves. Every error message and
    condition here is byte-for-byte identical to what `validate_launch_request`
    previously raised inline, so existing callers observe no behavior change.
    """
    if profile["transport"] != "acp_stdio":
        raise ProviderLaunchValidationError(
            f"provider profile {profile_id!r} has unsupported transport "
            f"{profile['transport']!r}"
        )
    launch_argv_value = profile["launch_argv"]
    if isinstance(launch_argv_value, tuple) and not launch_argv_value:
        raise ProviderLaunchValidationError(
            f"provider profile {profile_id!r} has no launch_argv"
        )
    launch_argv = _require_nonempty_string_tuple(launch_argv_value, "launch_argv")
    for segment in launch_argv:
        _reject_secret_bearing_argv(segment)
    display_name = _require_nonblank(profile["display_name"], "display_name")
    environment_allowlist = _require_string_tuple(
        profile["environment_allowlist"],
        "environment_allowlist",
    )
    try:
        authentication_method_id = _validate_optional_authentication_method_id(
            profile.get("authentication_method_id")
        )
    except ProviderRunPersistenceError as exc:
        raise ProviderLaunchValidationError(str(exc)) from exc
    capability_state = _require_nonblank(
        profile["capability_state"],
        "capability_state",
    )
    return ValidatedProviderProfileFields(
        display_name=display_name,
        launch_argv=launch_argv,
        environment_allowlist=environment_allowlist,
        authentication_method_id=authentication_method_id,
        capability_state=capability_state,
    )


async def list_provider_profile_summaries(
    provider_profile_repository: ProviderProfileRepository,
    provider_run_repository: ProviderRunRepository,
) -> list[ProviderProfileSummary]:
    """Return a read-only inventory summary for every non-removed provider profile."""
    profiles = await provider_profile_repository.list_profiles()
    summaries: list[ProviderProfileSummary] = []
    for profile in profiles:
        profile_id = str(profile["id"])

        validation_error: str | None = None
        try:
            validate_profile_structure(profile, profile_id=profile_id)
        except ProviderLaunchValidationError as exc:
            validation_error = str(exc)

        grants = await provider_profile_repository.list_workspace_grants_for_profile(
            profile_id, include_revoked=False
        )
        grant_summaries = tuple(
            WorkspaceGrantSummary(
                id=str(grant["id"]),
                canonical_workspace_root=str(grant["canonical_workspace_root"]),
                status=str(grant["status"]),
                workspace_label=str(
                    grant.get("workspace_label")
                    or grant["canonical_workspace_root"]
                ),
                description=grant.get("description")
                if isinstance(grant.get("description"), str)
                else None,
                routing_hints=tuple(
                    str(hint) for hint in grant.get("routing_hints", ())
                ),
                revision=int(grant.get("revision", 0)),
            )
            for grant in grants
        )

        latest_run = await provider_run_repository.get_latest_run_for_profile(profile_id)
        observed_capabilities = (
            latest_run["capabilities"] if latest_run is not None else None
        )

        summaries.append(
            ProviderProfileSummary(
                id=profile_id,
                display_name=str(profile["display_name"]),
                status=str(profile["status"]),
                capability_state=str(profile["capability_state"]),
                description=profile.get("description")
                if isinstance(profile.get("description"), str)
                else None,
                routing_hints=tuple(
                    str(hint) for hint in profile.get("routing_hints", ())
                ),
                revision=int(profile.get("revision", 0)),
                observed_capabilities=observed_capabilities,
                active_workspace_grants=grant_summaries,
                is_structurally_valid=validation_error is None,
                validation_error=validation_error,
                created_at=str(profile["created_at"]),
                updated_at=str(profile["updated_at"]),
            )
        )
    return summaries


def _require_nonblank(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderLaunchValidationError(f"{field_name} must be a nonblank string")
    return value


def _require_nonempty_string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        raise ProviderLaunchValidationError(
            f"{field_name} must be a non-empty tuple of nonblank strings"
        )
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ProviderLaunchValidationError(
            f"{field_name} must be a non-empty tuple of nonblank strings"
        )
    return value


def _require_string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ProviderLaunchValidationError(
            f"{field_name} must be a tuple of nonblank strings"
        )
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ProviderLaunchValidationError(
            f"{field_name} must be a tuple of nonblank strings"
        )
    return value


def _reject_secret_bearing_argv(segment: str) -> None:
    lowered = segment.lower()
    for flag in _SECRET_ARG_FLAGS:
        if flag in lowered:
            raise ProviderLaunchValidationError(
                f"launch_argv must not contain secret-bearing flag {flag!r}"
            )
    for prefix in _SECRET_ARG_PREFIXES:
        if lowered.startswith(prefix):
            raise ProviderLaunchValidationError(
                f"launch_argv must not contain secret-like value prefix {prefix!r}"
            )


def _contains_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.exists() and current.is_symlink():
            return True
    return False


def _resolve_real_workspace_directory(raw_path: object, *, field_name: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ProviderLaunchValidationError(f"{field_name} must be a nonblank string")
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        raise ProviderLaunchValidationError(f"{field_name} must be an absolute path")
    if _contains_symlink_component(candidate):
        raise ProviderLaunchValidationError(
            f"{field_name} cannot traverse a symbolic link"
        )
    resolved = candidate.resolve(strict=False)
    if not resolved.exists():
        raise ProviderLaunchValidationError(f"{field_name} does not exist: {resolved}")
    if not resolved.is_dir():
        raise ProviderLaunchValidationError(f"{field_name} is not a directory: {resolved}")
    if not os.access(resolved, os.R_OK | os.X_OK):
        raise ProviderLaunchValidationError(f"{field_name} is not accessible: {resolved}")
    return resolved


def _require_within_granted_root(candidate: Path, granted_root: Path) -> None:
    if candidate != granted_root and not candidate.is_relative_to(granted_root):
        raise ProviderLaunchValidationError(
            f"workspace path {candidate} is outside the granted root {granted_root}"
        )


class ProviderLaunchValidationService:
    """Validate an attended provider profile and workspace grant for launch."""

    def __init__(self, provider_profile_repository: ProviderProfileRepository) -> None:
        self._provider_profile_repository = provider_profile_repository

    async def validate_launch_request(
        self,
        *,
        provider_profile_id: str,
        workspace_grant_id: str,
        candidate_workspace_path: str,
    ) -> ValidatedProviderLaunchRequest:
        profile_id = _require_nonblank(provider_profile_id, "provider_profile_id")
        grant_id = _require_nonblank(workspace_grant_id, "workspace_grant_id")

        profile = await self._provider_profile_repository.get_profile(profile_id)
        if profile is None:
            raise ProviderLaunchValidationError(
                f"provider profile {profile_id!r} does not exist"
            )
        if profile["status"] != "enabled":
            raise ProviderLaunchValidationError(
                f"provider profile {profile_id!r} is not enabled"
            )
        profile_fields = validate_profile_structure(profile, profile_id=profile_id)
        launch_argv = profile_fields.launch_argv
        display_name = profile_fields.display_name
        environment_allowlist = profile_fields.environment_allowlist
        authentication_method_id = profile_fields.authentication_method_id
        capability_state = profile_fields.capability_state

        grant = await self._provider_profile_repository.get_workspace_grant(grant_id)
        if grant is None:
            raise ProviderLaunchValidationError(
                f"workspace grant {grant_id!r} does not exist"
            )
        if grant["provider_profile_id"] != profile_id:
            raise ProviderLaunchValidationError(
                f"workspace grant {grant_id!r} does not belong to profile {profile_id!r}"
            )
        if grant["status"] != "active":
            raise ProviderLaunchValidationError(
                f"workspace grant {grant_id!r} is not active"
            )

        granted_root = _resolve_real_workspace_directory(
            grant["canonical_workspace_root"],
            field_name="canonical_workspace_root",
        )
        candidate_root = _resolve_real_workspace_directory(
            candidate_workspace_path, field_name="candidate_workspace_path"
        )
        _require_within_granted_root(candidate_root, granted_root)

        return ValidatedProviderLaunchRequest(
            provider_profile_id=profile_id,
            display_name=display_name,
            launch_argv=launch_argv,
            environment_allowlist=environment_allowlist,
            authentication_method_id=authentication_method_id,
            workspace_grant_id=grant_id,
            resolved_workspace_root=str(candidate_root),
            capability_state=capability_state,
        )
