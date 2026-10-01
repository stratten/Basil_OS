"""Activate one current provider target authorization as a child Agent Task."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
import logging
import uuid
from typing import Any

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.delegation_repository import (
    ProviderTargetDelegationConflictError,
    ProviderTargetDelegationPersistenceError,
    ProviderTargetDelegationRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.discovery_proposal_repository import (
    ProviderDiscoveryProposalPersistenceError,
    ProviderDiscoveryProposalRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.profile_repository import (
    ProviderProfileRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.target_authorization_repository import (
    ProviderTargetAuthorizationPersistenceError,
    ProviderTargetAuthorizationRepository,
)
from api.services.agent_providers.profiles.launch_validation import (
    ProviderLaunchValidationError,
    ProviderLaunchValidationService,
)

logger = logging.getLogger(__name__)


class ProviderTargetDelegationError(ValueError):
    """Raised when a delegate request is malformed."""


class ProviderTargetDelegationUnavailableError(RuntimeError):
    """Raised when current authority cannot safely create a delegation."""

    def __init__(self, *, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _require_nonblank(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderTargetDelegationError(f"{field_name} must be a nonblank string")
    return value.strip()


class ProviderDelegationWaitRequest(RuntimeError):
    """Stop the primary workflow after one delegated child is durably routable."""

    def __init__(self, *, delegation_id: str, child_agent_task_id: str) -> None:
        self.delegation_id = _require_nonblank(delegation_id, "delegation_id")
        self.child_agent_task_id = _require_nonblank(
            child_agent_task_id,
            "child_agent_task_id",
        )
        super().__init__("Provider delegation is awaiting its child Agent Task.")


class ProviderTargetDelegationService:
    """Create one child provider task from one verified authorization record."""

    def __init__(
        self,
        *,
        proposal_repository: ProviderDiscoveryProposalRepository,
        authorization_repository: ProviderTargetAuthorizationRepository,
        delegation_repository: ProviderTargetDelegationRepository,
        provider_profile_repository: ProviderProfileRepository,
        agent_task_service: Any,
        submission_service: Any,
        delegated_agent_repository: Any | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._proposals = proposal_repository
        self._authorizations = authorization_repository
        self._delegations = delegation_repository
        self._profiles = provider_profile_repository
        self._agent_tasks = agent_task_service
        self._submission_service = submission_service
        self._delegated_agent_runs = delegated_agent_repository
        self._now = now or datetime.utcnow

    async def delegate_authorization(
        self,
        *,
        agent_task_id: str,
        root_task_id: str,
        authorization_id: str,
    ) -> dict[str, object]:
        parent_id = _require_nonblank(agent_task_id, "agent_task_id")
        root_id = _require_nonblank(root_task_id, "root_task_id")
        clean_authorization_id = _require_nonblank(authorization_id, "authorization_id")
        parent = await self._agent_tasks.get_agent_task(parent_id)
        if parent is None or (getattr(parent, "root_task_id", None) or parent.id) != root_id:
            raise ProviderTargetDelegationUnavailableError(
                reason_code="authorization_not_current_task",
                message="The target authorization is not bound to the current Agent Task.",
            )
        authorization = await self._load_authorization(
            authorization_id=clean_authorization_id,
            parent_id=parent_id,
            root_id=root_id,
        )
        return await self._delegate_authorization_with_generic_control(
            parent=parent,
            authorization=authorization,
            authorization_id=clean_authorization_id,
            parent_id=parent_id,
            root_id=root_id,
        )

    async def _delegate_authorization_with_generic_control(
        self,
        *,
        parent: Any,
        authorization: Mapping[str, object],
        authorization_id: str,
        parent_id: str,
        root_id: str,
    ) -> dict[str, object]:
        """Reserve, atomically admit, then dispatch one authority-bound provider child."""

        if self._delegated_agent_runs is None:
            raise ProviderTargetDelegationUnavailableError(
                reason_code="delegated_agent_repository_unavailable",
                message="Provider delegation requires generic delegated-agent persistence.",
            )
        reserve = getattr(self._submission_service, "reserve_authorized_provider_delegation", None)
        dispatch = getattr(self._submission_service, "dispatch_reserved_authorized_provider_delegation", None)
        if not callable(reserve) or not callable(dispatch):
            raise ProviderTargetDelegationUnavailableError(
                reason_code="delegation_submission_unavailable",
                message="Provider delegation reservation and dispatch are unavailable.",
            )
        existing = await self._delegations.get_delegation_by_authorization(authorization_id)
        if existing is not None:
            run_id = existing.get("delegated_agent_run_id")
            run = await self._delegated_agent_runs.get_run(str(run_id)) if run_id else None
            if run is not None and run["status"] not in {"settled", "failed", "canceled"}:
                raise ProviderDelegationWaitRequest(
                    delegation_id=str(existing["id"]),
                    child_agent_task_id=str(existing["child_agent_task_id"]),
                )
            if run is not None and run["status"] == "failed":
                return {
                    "ok": False,
                    "delegation_id": existing["id"],
                    "delegated_agent_run_id": run_id,
                    "child_agent_task_id": existing["child_agent_task_id"],
                    "status": "launch_failed",
                    "idempotent_replay": True,
                }
            return {
                "ok": run is not None and run["status"] == "settled",
                "delegation_id": existing["id"],
                "delegated_agent_run_id": run_id,
                "child_agent_task_id": existing["child_agent_task_id"],
                "status": run["status"] if run is not None else "unavailable",
                "idempotent_replay": True,
            }
        try:
            validated = await ProviderLaunchValidationService(self._profiles).validate_launch_request(
                provider_profile_id=str(authorization["selected_provider_profile_id"]),
                workspace_grant_id=str(authorization["selected_workspace_grant_id"]),
                candidate_workspace_path=str(authorization["resolved_workspace_path"]),
            )
            proposal = await self._load_proposal(str(authorization["proposal_id"]))
        except ProviderLaunchValidationError as exc:
            return self._failure_without_delegation(
                reason_code="selected_target_no_longer_authorized",
                message="The selected provider target is no longer authorized.",
            )
        except ProviderTargetDelegationUnavailableError as exc:
            if exc.reason_code == "proposal_unavailable":
                return {
                    "ok": False,
                    "status": "launch_failed",
                    "reason_code": "proposal_unavailable",
                    "message": str(exc),
                }
            raise
        child_id = str(uuid.uuid4())
        context = {
            "provider_target": {
                "provider_profile_id": validated.provider_profile_id,
                "workspace_grant_id": validated.workspace_grant_id,
                "candidate_workspace_path": authorization["resolved_workspace_path"],
            },
            "provider_delegation": {
                "authorization_id": authorization_id,
                "selected_connection_id": authorization["selected_connection_id"],
                "selected_tool_name": authorization["selected_tool_name"],
                "selected_service_policy": authorization["selected_service_policy"],
                "exact_user_constraints": proposal["exact_user_constraints"],
                "rationale": proposal["rationale"],
                "reference_paths": authorization["reference_paths"],
            },
        }
        await reserve(
            agent_task=parent.transcribed_prompt,
            child_agent_task_id=child_id,
            root_task_id=root_id,
            parent_agent_task_id=parent_id,
            chain_sequence_number=int(parent.chain_sequence_number) + 1,
            delegation_context=context,
        )
        rationale = str(proposal["rationale"]).strip()
        try:
            await self._delegated_agent_runs.reserve_child_agent_task(
                parent_agent_task_id=parent_id,
                root_task_id=root_id,
                child_agent_task_id=child_id,
                executor_kind="acp_provider",
                strategic_assessment={
                    "parallelism_reason": f"Authorized provider child executes delegated work: {rationale}",
                    "independence_rationale": "Authorized provider target runs in an isolated child agent task.",
                    "expected_benefit": rationale,
                    "parent_work_can_continue": False,
                    "child_cannot_delegate": True,
                },
            )
            run = await self._delegated_agent_runs.create_provider_relation_and_admit_reserved_run(
                authorization_id=authorization_id,
                child_agent_task_id=child_id,
                provider_profile_id=validated.provider_profile_id,
                workspace_grant_id=validated.workspace_grant_id,
                selected_connection_id=authorization["selected_connection_id"],
                selected_tool_name=authorization["selected_tool_name"],
                selected_service_policy=authorization["selected_service_policy"],
                admitted_scope={"read_only": False, "mutable_paths": []},
                evidence_policy={"required": "provider_reported"},
            )
            relation = await self._delegations.get_relation_by_delegated_agent_run(str(run["id"]))
            if relation is None:
                raise ProviderTargetDelegationUnavailableError(
                    reason_code="relation_missing_after_admission",
                    message="Provider delegation authority relation was not persisted.",
                )
            dispatch_result = await dispatch(
                child_agent_task_id=child_id,
                root_task_id=root_id,
                parent_agent_task_id=parent_id,
            )
            if (
                not isinstance(dispatch_result, Mapping)
                or not dispatch_result.get("success")
                or dispatch_result.get("status") != "routing"
            ):
                await self._record_launch_failure(
                    run=run,
                    summary="Provider child dispatch did not enter routing.",
                )
                return {
                    "ok": False,
                    "delegation_id": relation["id"],
                    "delegated_agent_run_id": run["id"],
                    "child_agent_task_id": child_id,
                    "status": "launch_failed",
                    "reason_code": "child_submission_failed",
                }
        except ProviderTargetDelegationUnavailableError:
            raise
        except Exception as exc:
            current = await self._delegated_agent_runs.get_run_for_child(child_id)
            if current is not None and current["status"] not in {"settled", "failed", "canceled"}:
                await self._delegated_agent_runs.record_outcome(
                    delegated_agent_run_id=str(current["id"]),
                    expected_revision=int(current["revision"]),
                    transport_state="dispatch",
                    executor_result_state="failed",
                    evidence_state="unavailable",
                    summary="Provider child dispatch failed before execution began.",
                    receipt_references=[],
                    terminal_status="failed",
                )
            raise ProviderTargetDelegationUnavailableError(
                reason_code="provider_child_dispatch_failed",
                message="The authorized provider child could not be dispatched.",
            ) from exc
        await self._agent_tasks.update_agent_task_status(
            agent_task_id=parent_id,
            status="awaiting_delegated_agents",
            result_data={
                "provider_delegation": {
                    "delegation_id": relation["id"],
                    "delegated_agent_run_id": run["id"],
                    "child_agent_task_id": child_id,
                    "status": "awaiting_child",
                }
            },
        )
        raise ProviderDelegationWaitRequest(
            delegation_id=str(relation["id"]),
            child_agent_task_id=child_id,
        )

    async def _record_launch_failure(self, *, run: Mapping[str, object], summary: str) -> None:
        if self._delegated_agent_runs is None:
            return
        if run["status"] in {"settled", "failed", "canceled"}:
            return
        await self._delegated_agent_runs.record_outcome(
            delegated_agent_run_id=str(run["id"]),
            expected_revision=int(run["revision"]),
            transport_state="dispatch",
            executor_result_state="failed",
            evidence_state="unavailable",
            summary=summary,
            receipt_references=[],
            terminal_status="failed",
        )

    async def _load_authorization(
        self,
        *,
        authorization_id: str,
        parent_id: str,
        root_id: str,
    ) -> Mapping[str, object]:
        try:
            authorization = await self._authorizations.get_authorization(authorization_id)
        except ProviderTargetAuthorizationPersistenceError as exc:
            raise ProviderTargetDelegationUnavailableError(
                reason_code="authorization_malformed",
                message="The target authorization is unavailable.",
            ) from exc
        if (
            authorization is None
            or authorization["agent_task_id"] != parent_id
            or authorization["root_task_id"] != root_id
            or authorization["status"] != "authorized"
        ):
            raise ProviderTargetDelegationUnavailableError(
                reason_code="authorization_not_current_task",
                message="The target authorization is not current delegated authority.",
            )
        try:
            expires_at = datetime.fromisoformat(str(authorization["expires_at"]))
        except ValueError as exc:
            raise ProviderTargetDelegationError("authorization expires_at is malformed") from exc
        if expires_at <= self._now():
            raise ProviderTargetDelegationUnavailableError(
                reason_code="authorization_expired",
                message="The target authorization has expired.",
            )
        required = (
            authorization["selected_provider_profile_id"],
            authorization["selected_workspace_grant_id"],
            authorization["resolved_workspace_path"],
        )
        if not all(isinstance(value, str) and value.strip() for value in required):
            raise ProviderTargetDelegationUnavailableError(
                reason_code="authorization_malformed",
                message="The target authorization has no launchable selection.",
            )
        return authorization

    async def _load_proposal(self, proposal_id: str) -> Mapping[str, object]:
        try:
            proposal = await self._proposals.get_proposal(proposal_id)
        except ProviderDiscoveryProposalPersistenceError as exc:
            raise ProviderTargetDelegationUnavailableError(
                reason_code="proposal_unavailable",
                message="The target proposal is unavailable.",
            ) from exc
        if (
            proposal is None
            or not isinstance(proposal.get("exact_user_constraints"), Mapping)
            or not isinstance(proposal.get("rationale"), str)
        ):
            raise ProviderTargetDelegationUnavailableError(
                reason_code="proposal_unavailable",
                message="The target proposal is unavailable.",
            )
        return proposal

    @staticmethod
    def _failure_without_delegation(
        *,
        reason_code: str,
        message: str,
    ) -> dict[str, object]:
        return {
            "ok": False,
            "status": "unavailable",
            "reason_code": reason_code,
            "message": message,
        }

    @staticmethod
    def _public_result(delegation: Mapping[str, object]) -> dict[str, object]:
        return {
            "ok": delegation["status"] == "submitted",
            "delegation_id": delegation["id"],
            "child_agent_task_id": delegation["child_agent_task_id"],
            "status": delegation["status"],
            "provider_profile_id": delegation["provider_profile_id"],
            "workspace_grant_id": delegation["workspace_grant_id"],
            "selected_connection_id": delegation["selected_connection_id"],
            "selected_tool_name": delegation["selected_tool_name"],
            "reason_code": delegation["failure_reason"],
            "idempotent_replay": delegation["idempotent_replay"],
        }
