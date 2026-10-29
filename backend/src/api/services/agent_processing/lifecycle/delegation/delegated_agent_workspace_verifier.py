"""Read-only verification of one provider-reported workspace artifact."""

from __future__ import annotations

import hashlib
import stat
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from api.services.agent_providers.profiles.launch_validation import (
    ProviderLaunchValidationError,
    ProviderLaunchValidationService,
    _contains_symlink_component,
    _require_within_granted_root,
)

MAX_VERIFY_FILE_BYTES = 8 * 1024 * 1024
VERIFY_CHUNK_BYTES = 64 * 1024
_VERIFY_SOURCE_KEY_VERSION = "v1"


class DelegatedAgentWorkspaceVerificationError(RuntimeError):
    """Raised when verification authority or evidence is unavailable."""


def _verification_source_event_key(artifact_evidence_id: str) -> str:
    return f"parent-verification:artifact:{artifact_evidence_id}:{_VERIFY_SOURCE_KEY_VERSION}"


def _relative_workspace_path(locator: object) -> PurePosixPath:
    if not isinstance(locator, str) or not locator.strip():
        raise DelegatedAgentWorkspaceVerificationError("artifact evidence has no workspace-relative locator")
    value = locator.strip()
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        value.casefold().startswith("file://")
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or ".." in posix_path.parts
        or ".." in windows_path.parts
    ):
        raise DelegatedAgentWorkspaceVerificationError("artifact locator is not workspace-relative")
    return posix_path


def _contains_broken_symlink_component(path: Path) -> bool:
    """Cover a broken link, which `Path.exists()` intentionally treats as absent."""

    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink() and not current.exists():
            return True
    return False


class DelegatedAgentWorkspaceVerifier:
    """Verify a single owned evidence locator without exposing file content."""

    def __init__(
        self,
        *,
        delegated_agent_repository: Any,
        evidence_repository: Any,
        provider_target_delegation_repository: Any,
        provider_profile_repository: Any,
    ) -> None:
        self._runs = delegated_agent_repository
        self._evidence = evidence_repository
        self._relations = provider_target_delegation_repository
        self._profiles = provider_profile_repository

    async def verify_artifact(
        self,
        *,
        parent_agent_task_id: str,
        delegated_agent_run_id: str,
        artifact_evidence_id: str,
    ) -> dict[str, Any]:
        source_event_key = _verification_source_event_key(artifact_evidence_id)
        replay = await self._evidence.get_evidence_for_parent_by_source_event_key(
            parent_agent_task_id=parent_agent_task_id,
            delegated_agent_run_id=delegated_agent_run_id,
            source_event_key=source_event_key,
        )
        if replay is not None:
            return replay
        run = await self._runs.get_run(delegated_agent_run_id)
        if run is None or run["parent_agent_task_id"] != parent_agent_task_id:
            raise DelegatedAgentWorkspaceVerificationError("delegated child is not owned by this parent")
        if run["executor_kind"] != "acp_provider" or run["status"] != "supervision_due":
            raise DelegatedAgentWorkspaceVerificationError(
                "only an ACP delegated child due for supervision can verify an artifact"
            )
        artifact = await self._evidence.get_evidence_for_parent(
            parent_agent_task_id=parent_agent_task_id,
            delegated_agent_run_id=delegated_agent_run_id,
            evidence_id=artifact_evidence_id,
        )
        if (
            artifact is None
            or artifact["source"] != "provider_activity"
            or artifact["kind"] != "artifact_locator"
            or artifact["provenance"] != "provider_reported"
        ):
            raise DelegatedAgentWorkspaceVerificationError(
                "evidence is not a provider-reported artifact locator"
            )
        relative_path = _relative_workspace_path(artifact["artifact_locator"])
        relation = await self._relations.get_relation_by_delegated_agent_run(delegated_agent_run_id)
        if (
            relation is None
            or relation["child_agent_task_id"] != run["child_agent_task_id"]
            or relation["parent_agent_task_id"] != parent_agent_task_id
        ):
            raise DelegatedAgentWorkspaceVerificationError("delegated provider authority relation is unavailable")
        profile_id = str(relation["provider_profile_id"])
        grant_id = str(relation["workspace_grant_id"])
        profile = await self._profiles.get_profile(profile_id)
        grant = await self._profiles.get_workspace_grant(grant_id)
        if (
            not isinstance(profile, Mapping)
            or profile.get("status") != "enabled"
            or not isinstance(grant, Mapping)
            or grant.get("status") != "active"
            or grant.get("provider_profile_id") != profile_id
        ):
            raise DelegatedAgentWorkspaceVerificationError("provider profile or workspace grant is no longer active")
        try:
            validated = await ProviderLaunchValidationService(self._profiles).validate_launch_request(
                provider_profile_id=profile_id,
                workspace_grant_id=grant_id,
                candidate_workspace_path=str(grant["canonical_workspace_root"]),
            )
        except ProviderLaunchValidationError as exc:
            raise DelegatedAgentWorkspaceVerificationError(str(exc)) from exc
        workspace_root = Path(validated.resolved_workspace_root)
        candidate = workspace_root.joinpath(*relative_path.parts)
        return await self._verify_candidate(
            delegated_agent_run_id=delegated_agent_run_id,
            artifact_evidence_id=artifact_evidence_id,
            source_event_key=source_event_key,
            candidate=candidate,
            workspace_root=workspace_root,
        )

    async def get_verification_for_settlement(
        self,
        *,
        parent_agent_task_id: str,
        delegated_agent_run_id: str,
        verification_evidence_id: str,
    ) -> dict[str, Any]:
        evidence = await self._evidence.get_evidence_for_parent(
            parent_agent_task_id=parent_agent_task_id,
            delegated_agent_run_id=delegated_agent_run_id,
            evidence_id=verification_evidence_id,
        )
        if (
            evidence is None
            or evidence["source"] != "parent_verification"
            or evidence["kind"] != "workspace_artifact_verification"
            or evidence["provenance"] != "basil_observed"
            or evidence["verification_state"] not in {"verified", "verification_mismatch"}
        ):
            raise DelegatedAgentWorkspaceVerificationError(
                "verification evidence is not admissible for settlement"
            )
        return evidence

    async def _verify_candidate(
        self,
        *,
        delegated_agent_run_id: str,
        artifact_evidence_id: str,
        source_event_key: str,
        candidate: Path,
        workspace_root: Path,
    ) -> dict[str, Any]:
        try:
            if _contains_symlink_component(candidate) or _contains_broken_symlink_component(candidate):
                return await self._record_result(
                    delegated_agent_run_id=delegated_agent_run_id,
                    artifact_evidence_id=artifact_evidence_id,
                    source_event_key=source_event_key,
                    verification_state="verification_mismatch",
                    reason="symlink_not_allowed",
                    byte_count=None,
                    digest=None,
                )
            resolved = candidate.resolve(strict=True)
            _require_within_granted_root(resolved, workspace_root)
            before = resolved.stat()
        except FileNotFoundError:
            return await self._record_result(
                delegated_agent_run_id=delegated_agent_run_id,
                artifact_evidence_id=artifact_evidence_id,
                source_event_key=source_event_key,
                verification_state="verification_mismatch",
                reason="missing",
                byte_count=None,
                digest=None,
            )
        except (OSError, ProviderLaunchValidationError):
            return await self._record_result(
                delegated_agent_run_id=delegated_agent_run_id,
                artifact_evidence_id=artifact_evidence_id,
                source_event_key=source_event_key,
                verification_state="verification_mismatch",
                reason="outside_grant_or_unreadable",
                byte_count=None,
                digest=None,
            )
        if not stat.S_ISREG(before.st_mode):
            return await self._record_result(
                delegated_agent_run_id=delegated_agent_run_id,
                artifact_evidence_id=artifact_evidence_id,
                source_event_key=source_event_key,
                verification_state="verification_mismatch",
                reason="not_regular_file",
                byte_count=None,
                digest=None,
            )
        if before.st_size > MAX_VERIFY_FILE_BYTES:
            return await self._record_result(
                delegated_agent_run_id=delegated_agent_run_id,
                artifact_evidence_id=artifact_evidence_id,
                source_event_key=source_event_key,
                verification_state="verification_mismatch",
                reason="too_large",
                byte_count=before.st_size,
                digest=None,
            )
        try:
            digest = hashlib.sha256()
            with resolved.open("rb") as handle:
                for chunk in iter(lambda: handle.read(VERIFY_CHUNK_BYTES), b""):
                    digest.update(chunk)
            after = resolved.stat()
        except OSError:
            return await self._record_result(
                delegated_agent_run_id=delegated_agent_run_id,
                artifact_evidence_id=artifact_evidence_id,
                source_event_key=source_event_key,
                verification_state="verification_mismatch",
                reason="unreadable",
                byte_count=None,
                digest=None,
            )
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            return await self._record_result(
                delegated_agent_run_id=delegated_agent_run_id,
                artifact_evidence_id=artifact_evidence_id,
                source_event_key=source_event_key,
                verification_state="verification_mismatch",
                reason="changed_during_verification",
                byte_count=after.st_size,
                digest=None,
            )
        return await self._record_result(
            delegated_agent_run_id=delegated_agent_run_id,
            artifact_evidence_id=artifact_evidence_id,
            source_event_key=source_event_key,
            verification_state="verified",
            reason="regular_file",
            byte_count=after.st_size,
            digest=digest.hexdigest(),
        )

    async def _record_result(
        self,
        *,
        delegated_agent_run_id: str,
        artifact_evidence_id: str,
        source_event_key: str,
        verification_state: str,
        reason: str,
        byte_count: int | None,
        digest: str | None,
    ) -> dict[str, Any]:
        summary = (
            "Basil verified one provider-reported workspace artifact."
            if verification_state == "verified"
            else "Basil could not verify one provider-reported workspace artifact."
        )
        return await self._evidence.append_evidence(
            delegated_agent_run_id=delegated_agent_run_id,
            delegated_agent_turn_id=None,
            source_event_key=source_event_key,
            source="parent_verification",
            kind="workspace_artifact_verification",
            provenance="basil_observed",
            verification_state=verification_state,
            summary=summary,
            structured_data={
                "artifact_evidence_id": artifact_evidence_id,
                "reason": reason,
                "byte_count": byte_count,
                "sha256": digest,
            },
        )
