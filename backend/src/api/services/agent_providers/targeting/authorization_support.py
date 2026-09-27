"""Shared provider-target authorization contracts and live authority validation."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.errors import (
    ProviderRunPersistenceError,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.profile_repository import (
    ProviderProfileRepository,
)
from api.services.agent_processing.tools.external_services.external_catalog.auth import (
    default_external_catalog_policy_for_tool,
    find_external_catalog_connection,
    load_external_catalog_preferences,
)
from api.services.agent_providers.catalog.catalog_service import (
    _bounded_text,
    _safe_optional_description,
)
from api.services.agent_providers.profiles.launch_validation import (
    ProviderLaunchValidationError,
    _contains_symlink_component,
    _require_within_granted_root,
    _resolve_real_workspace_directory,
    validate_profile_structure,
)

MAX_CHECKPOINT_OPTIONS = 4
MAX_CHECKPOINT_TEXT_BYTES = 500
CHOICE_TOKEN_PREFIX = "target-choice:"
CANCEL_TOKEN_PREFIX = "target-cancel:"
CHECKPOINT_PROMPT = (
    "Which provider and authorized workspace should Basil use for this delegation?"
)


class ProviderTargetAuthorizationError(RuntimeError):
    """Raised when authorization input or binding is invalid."""


class ProviderTargetAuthorizationUnavailableError(ProviderTargetAuthorizationError):
    """Raised when durable inventory required for authorization is unavailable."""

    def __init__(self, *, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class _ValidatedSelection:
    provider_profile_id: str
    workspace_grant_id: str
    selected_connection_id: str | None
    selected_tool_name: str | None
    selected_service_policy: str | None
    resolved_workspace_path: str | None
    reference_paths: tuple[str, ...]
    display_label: str
    description: str | None


@dataclass(frozen=True)
class _EvaluationOutcome:
    status: str
    reason_code: str
    selection: _ValidatedSelection | None = None
    options: tuple[_ValidatedSelection, ...] = ()
    cancel_value: str | None = None


@dataclass(frozen=True)
class _SelectionValidation:
    selection: _ValidatedSelection | None = None
    reason_code: str | None = None


def _require_nonblank(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderTargetAuthorizationError(f"{field_name} must be a nonblank string")
    return value.strip()


def _is_absolute_path(value: str) -> bool:
    return Path(value).expanduser().is_absolute()


def _reference_paths_from_task(task: Any) -> set[str]:
    artifacts = getattr(task, "accumulated_artifacts", None)
    if not isinstance(artifacts, Mapping):
        return set()
    paths = artifacts.get("reference_paths")
    if isinstance(paths, (str, bytes, bytearray)) or not isinstance(paths, Sequence):
        return set()
    return {path for path in paths if isinstance(path, str)}


def _strip_sensitive_fields(record: Mapping[str, object]) -> dict[str, object]:
    payload = dict(record)
    payload.pop("resolved_workspace_path", None)
    payload.pop("reference_paths", None)
    payload.pop("choice_snapshot", None)
    payload.pop("response_fingerprint", None)
    payload.pop("parent_authorization_id", None)
    payload.pop("proposal_id", None)
    payload.pop("agent_task_id", None)
    payload.pop("root_task_id", None)
    payload.pop("selected_provider_profile_id", None)
    payload.pop("selected_workspace_grant_id", None)
    payload.pop("selected_connection_id", None)
    payload.pop("selected_tool_name", None)
    payload.pop("selected_service_policy", None)
    payload.pop("expires_at", None)
    payload.pop("created_at", None)
    return payload


class ProviderTargetSelectionValidator:
    """Validate a proposed provider target against current durable authority."""

    def __init__(self, provider_profile_repository: ProviderProfileRepository) -> None:
        self._profiles = provider_profile_repository

    async def validate(
        self,
        *,
        provider_profile_id: str,
        workspace_grant_id: str,
        connection_id: object,
        tool_name: object,
        proposal: Mapping[str, object],
        task: Any,
    ) -> _SelectionValidation:
        try:
            profile = await self._profiles.get_profile(provider_profile_id)
        except ProviderRunPersistenceError:
            return _SelectionValidation(reason_code="invalid_provider_candidate")
        if not isinstance(profile, Mapping) or profile.get("status") != "enabled":
            return _SelectionValidation(reason_code="invalid_provider_candidate")
        try:
            validated = validate_profile_structure(profile, profile_id=provider_profile_id)
        except (KeyError, TypeError, ProviderLaunchValidationError):
            return _SelectionValidation(reason_code="invalid_provider_candidate")
        try:
            grant = await self._profiles.get_workspace_grant(workspace_grant_id)
        except ProviderRunPersistenceError:
            return _SelectionValidation(reason_code="invalid_workspace_claim")
        if (
            not isinstance(grant, Mapping)
            or grant.get("provider_profile_id") != provider_profile_id
            or grant.get("status") != "active"
        ):
            return _SelectionValidation(reason_code="invalid_workspace_claim")
        try:
            granted_root = _resolve_real_workspace_directory(
                grant["canonical_workspace_root"],
                field_name="canonical_workspace_root",
            )
        except ProviderLaunchValidationError:
            return _SelectionValidation(reason_code="invalid_workspace_claim")
        reference_paths = await self._resolve_reference_paths(
            proposal=proposal,
            task=task,
            granted_root=granted_root,
        )
        if reference_paths is None:
            return _SelectionValidation(reason_code="invalid_workspace_claim")
        resolved_workspace_path = str(granted_root)
        clean_connection_id = (
            str(connection_id).strip() if isinstance(connection_id, str) and connection_id.strip() else None
        )
        clean_tool_name = (
            str(tool_name).strip() if isinstance(tool_name, str) and tool_name.strip() else None
        )
        selected_service_policy: str | None = None
        if clean_connection_id is not None:
            service_policy, service_reason_code = self._validate_service_state(
                connection_id=clean_connection_id,
                tool_name=clean_tool_name,
            )
            if service_reason_code is not None:
                return _SelectionValidation(reason_code=service_reason_code)
            selected_service_policy = service_policy
        workspace_label = grant.get("workspace_label")
        label = _bounded_text(
            f"{validated.display_name} — {workspace_label or 'Authorized workspace'}",
            maximum_bytes=120,
        )
        clean_description = _safe_optional_description(grant.get("description"))
        return _SelectionValidation(
            selection=_ValidatedSelection(
                provider_profile_id=provider_profile_id,
                workspace_grant_id=workspace_grant_id,
                selected_connection_id=clean_connection_id,
                selected_tool_name=clean_tool_name,
                selected_service_policy=selected_service_policy,
                resolved_workspace_path=resolved_workspace_path,
                reference_paths=reference_paths,
                display_label=label,
                description=clean_description,
            )
        )

    async def _resolve_reference_paths(
        self,
        *,
        proposal: Mapping[str, object],
        task: Any,
        granted_root: Path,
    ) -> tuple[str, ...] | None:
        evidence = proposal.get("evidence")
        exact_constraints = proposal.get("exact_user_constraints")
        if not isinstance(evidence, list) or not isinstance(exact_constraints, Mapping):
            return None
        task_paths = _reference_paths_from_task(task)
        resolved_paths: list[str] = []
        for item in evidence:
            if not isinstance(item, Mapping) or item.get("source") != "reference_path":
                continue
            reference = item.get("reference")
            if not isinstance(reference, str) or reference not in task_paths:
                return None
            if _is_absolute_path(reference):
                resolved = self._resolve_contained_path(reference, granted_root)
                if resolved is None:
                    return None
                resolved_paths.append(resolved)
        workspace_constraint = exact_constraints.get("workspace")
        if isinstance(workspace_constraint, str) and workspace_constraint.strip():
            if _is_absolute_path(workspace_constraint):
                resolved = self._resolve_contained_path(workspace_constraint, granted_root)
                if resolved is None:
                    return None
                resolved_paths.append(resolved)
        return tuple(dict.fromkeys(resolved_paths))

    @staticmethod
    def _resolve_contained_path(raw_path: str, granted_root: Path) -> str | None:
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            return None
        if _contains_symlink_component(candidate):
            return None
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            return None
        if not resolved.exists():
            return None
        try:
            _require_within_granted_root(resolved, granted_root)
        except ProviderLaunchValidationError:
            return None
        return str(resolved)

    @staticmethod
    def _validate_service_state(
        *,
        connection_id: str,
        tool_name: str | None,
    ) -> tuple[str | None, str | None]:
        preferences = load_external_catalog_preferences()
        connection = find_external_catalog_connection(preferences, connection_id)
        if connection is None or connection.enabled is not True:
            return None, "invalid_service_candidate"
        if tool_name is not None and not any(
            cached_tool.name == tool_name for cached_tool in connection.cached_tools
        ):
            return None, "invalid_service_candidate"
        if tool_name is None:
            return None, None
        policy = connection.tool_policies.get(
            tool_name,
            default_external_catalog_policy_for_tool(connection, tool_name),
        )
        if policy == "never_allow":
            return None, "service_never_allow"
        return policy, None

    @staticmethod
    def _exact_target_is_verifiable(
        proposal: Mapping[str, object],
        task: Any,
        selection: _ValidatedSelection,
    ) -> bool:
        exact_constraints = proposal.get("exact_user_constraints")
        if not isinstance(exact_constraints, Mapping):
            return False
        for field_name in ("provider", "service", "tool"):
            value = exact_constraints.get(field_name)
            if isinstance(value, str) and value.strip():
                return False
        workspace_constraint = exact_constraints.get("workspace")
        if isinstance(workspace_constraint, str) and workspace_constraint.strip():
            if not _is_absolute_path(workspace_constraint):
                return False
            if not selection.reference_paths:
                return False
        evidence = proposal.get("evidence")
        if isinstance(evidence, list):
            for item in evidence:
                if (
                    isinstance(item, Mapping)
                    and item.get("source") == "reference_path"
                    and isinstance(item.get("reference"), str)
                    and _is_absolute_path(str(item["reference"]))
                    and str(item["reference"]) not in selection.reference_paths
                ):
                    return False
        return True
