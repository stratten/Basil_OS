"""Durable orchestration for provider-target authorization."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
import uuid
from typing import Any

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.service import (
    AgentTaskService,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.discovery_proposal_repository import (
    ProviderDiscoveryProposalPersistenceError,
    ProviderDiscoveryProposalRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.profile_repository import (
    ProviderProfileRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.target_authorization_repository import (
    ProviderTargetAuthorizationConflictError,
    ProviderTargetAuthorizationPersistenceError,
    ProviderTargetAuthorizationRepository,
)

from .authorization_support import (
    CANCEL_TOKEN_PREFIX,
    MAX_CHECKPOINT_OPTIONS,
    MAX_CHECKPOINT_TEXT_BYTES,
    ProviderTargetSelectionValidator,
    ProviderTargetAuthorizationError,
    ProviderTargetAuthorizationUnavailableError,
    _EvaluationOutcome,
    _ValidatedSelection,
    _require_nonblank,
)
from .checkpoint_payloads import ProviderTargetAuthorizationCheckpointFactory


class ProviderTargetAuthorizationService:
    """Authorize one proposal against current durable authority without activation."""

    def __init__(
        self,
        *,
        proposal_repository: ProviderDiscoveryProposalRepository,
        authorization_repository: ProviderTargetAuthorizationRepository,
        provider_profile_repository: ProviderProfileRepository,
        agent_task_service: AgentTaskService,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._proposals = proposal_repository
        self._authorizations = authorization_repository
        self._profiles = provider_profile_repository
        self._agent_tasks = agent_task_service
        self._now = now or datetime.utcnow
        self._selection_validator = ProviderTargetSelectionValidator(provider_profile_repository)
        self._checkpoint_factory = ProviderTargetAuthorizationCheckpointFactory()

    async def authorize_proposal(
        self,
        *,
        agent_task_id: str,
        root_task_id: str,
        proposal_id: str,
    ) -> dict[str, object]:
        task_id = _require_nonblank(agent_task_id, "agent_task_id")
        root_id = _require_nonblank(root_task_id, "root_task_id")
        clean_proposal_id = _require_nonblank(proposal_id, "proposal_id")
        try:
            proposal = await self._proposals.get_proposal(clean_proposal_id)
        except ProviderDiscoveryProposalPersistenceError:
            return await self._persist_initial(
                proposal_id=clean_proposal_id, agent_task_id=task_id, root_task_id=root_id,
                status="rejected", reason_code="proposal_malformed", selection=None,
                options=(), cancel_value=None, expires_at=self._now().isoformat(),
            )
        if proposal is None:
            raise ProviderTargetAuthorizationUnavailableError(
                reason_code="proposal_malformed", message="The target proposal is not available."
            )
        if proposal.get("agent_task_id") != task_id or proposal.get("root_task_id") != root_id:
            raise ProviderTargetAuthorizationError(
                "The target proposal is not bound to the current Agent Task."
            )
        try:
            expires_at = datetime.fromisoformat(str(proposal["expires_at"]))
        except ValueError as exc:
            raise ProviderTargetAuthorizationError("proposal expires_at is malformed") from exc
        if expires_at <= self._now():
            return await self._persist_initial(
                proposal_id=clean_proposal_id, agent_task_id=task_id, root_task_id=root_id,
                status="rejected", reason_code="proposal_expired", selection=None,
                options=(), cancel_value=None, expires_at=str(proposal["expires_at"]),
            )
        task = await self._agent_tasks.get_agent_task(task_id)
        actual_root_id = getattr(task, "root_task_id", None) or getattr(task, "id", None)
        if task is None or actual_root_id != root_id:
            raise ProviderTargetAuthorizationUnavailableError(
                reason_code="proposal_not_current_task", message="The current Agent Task is unavailable."
            )
        outcome = await self._evaluate_proposal(proposal, task)
        return await self._persist_initial(
            proposal_id=clean_proposal_id, agent_task_id=task_id, root_task_id=root_id,
            status=outcome.status, reason_code=outcome.reason_code, selection=outcome.selection,
            options=outcome.options, cancel_value=outcome.cancel_value,
            expires_at=str(proposal["expires_at"]),
        )

    async def resolve_checkpoint_response(
        self,
        *,
        agent_task_id: str,
        root_task_id: str,
        authorization_id: str,
        response: str,
    ) -> dict[str, object]:
        task_id = _require_nonblank(agent_task_id, "agent_task_id")
        root_id = _require_nonblank(root_task_id, "root_task_id")
        parent_id = _require_nonblank(authorization_id, "authorization_id")
        response_value = _require_nonblank(response, "response")
        if len(response_value.encode("utf-8")) > MAX_CHECKPOINT_TEXT_BYTES:
            raise ProviderTargetAuthorizationError(
                f"checkpoint response must not exceed {MAX_CHECKPOINT_TEXT_BYTES} UTF-8 bytes"
            )
        try:
            parent = await self._authorizations.get_authorization(parent_id)
        except ProviderTargetAuthorizationPersistenceError as exc:
            raise ProviderTargetAuthorizationUnavailableError(
                reason_code="proposal_malformed", message="The target checkpoint record is malformed."
            ) from exc
        if (
            parent is None or parent["agent_task_id"] != task_id
            or parent["root_task_id"] != root_id or parent["status"] != "needs_user"
        ):
            raise ProviderTargetAuthorizationUnavailableError(
                reason_code="proposal_not_current_task",
                message="The target checkpoint is not pending for this Agent Task.",
            )
        try:
            expires_at = datetime.fromisoformat(str(parent["expires_at"]))
        except ValueError as exc:
            raise ProviderTargetAuthorizationError("authorization expires_at is malformed") from exc
        if expires_at <= self._now():
            raise ProviderTargetAuthorizationUnavailableError(
                reason_code="proposal_expired", message="The target checkpoint has expired."
            )
        proposal = await self._proposals.get_proposal(str(parent["proposal_id"]))
        if proposal is None:
            raise ProviderTargetAuthorizationUnavailableError(
                reason_code="proposal_malformed", message="The target proposal is no longer available."
            )
        choice_snapshot = parent.get("choice_snapshot")
        if not isinstance(choice_snapshot, list):
            raise ProviderTargetAuthorizationError("choice_snapshot is malformed")
        cancel_value = self._checkpoint_factory.cancel_value_from_snapshot(choice_snapshot)
        if response_value == cancel_value:
            return await self._persist_response(
                parent=parent, proposal=proposal, status="canceled",
                reason_code="user_canceled_delegation", selection=None, response_value=response_value,
            )
        matched = self._checkpoint_factory.match_choice_token(choice_snapshot, response_value)
        if matched is None:
            return await self._persist_response(
                parent=parent, proposal=proposal, status="clarification_received",
                reason_code="user_clarification_required", selection=None, response_value=response_value,
            )
        provider_profile_id = matched.get("provider_profile_id")
        workspace_grant_id = matched.get("workspace_grant_id")
        if not isinstance(provider_profile_id, str) or not isinstance(workspace_grant_id, str):
            raise ProviderTargetAuthorizationUnavailableError(
                reason_code="proposal_malformed", message="The target checkpoint record is malformed."
            )
        task = await self._agent_tasks.get_agent_task(task_id)
        actual_root_id = getattr(task, "root_task_id", None) or getattr(task, "id", None)
        if task is None or actual_root_id != root_id:
            raise ProviderTargetAuthorizationUnavailableError(
                reason_code="proposal_not_current_task", message="The current Agent Task is unavailable."
            )
        validation = await self._selection_validator.validate(
            provider_profile_id=provider_profile_id, workspace_grant_id=workspace_grant_id,
            connection_id=matched.get("connection_id"), tool_name=matched.get("tool_name"),
            proposal=proposal, task=task,
        )
        if validation.selection is None:
            return await self._persist_response(
                parent=parent, proposal=proposal, status="rejected",
                reason_code="selected_target_no_longer_authorized", selection=None,
                response_value=response_value,
            )
        return await self._persist_response(
            parent=parent, proposal=proposal, status="authorized",
            reason_code="user_selected_verified_target", selection=validation.selection,
            response_value=response_value,
        )

    async def _evaluate_proposal(self, proposal: Mapping[str, object], task: Any) -> _EvaluationOutcome:
        status = proposal.get("status")
        confidence = proposal.get("confidence")
        grounding_tier = proposal.get("grounding_tier")
        provider_candidates = proposal.get("provider_candidates")
        service_candidates = proposal.get("service_candidates")
        exact_constraints = proposal.get("exact_user_constraints")
        if not all(isinstance(value, str) for value in (status, confidence, grounding_tier)):
            return _EvaluationOutcome("rejected", "proposal_malformed")
        if status not in {"proposed", "ambiguous", "unavailable", "conflicts_with_user_target"} or confidence not in {"high", "medium", "low"}:
            return _EvaluationOutcome("rejected", "proposal_malformed")
        if not isinstance(provider_candidates, list) or not isinstance(service_candidates, list) or not isinstance(exact_constraints, Mapping):
            return _EvaluationOutcome("rejected", "proposal_malformed")
        if len(service_candidates) > 1:
            return await self._needs_user_outcome(proposal, task, reason_code="multiple_service_candidates", include_options=False)
        if status in {"ambiguous", "unavailable", "conflicts_with_user_target"}:
            return await self._needs_user_outcome(proposal, task, reason_code="proposal_requires_user_choice")
        if confidence == "low" or len(provider_candidates) > 1:
            return await self._needs_user_outcome(proposal, task, reason_code="low_confidence" if confidence == "low" else "proposal_requires_user_choice")
        if status != "proposed" or len(provider_candidates) != 1:
            return await self._needs_user_outcome(proposal, task, reason_code="proposal_requires_user_choice")
        candidate = provider_candidates[0]
        if not isinstance(candidate, Mapping) or not isinstance(candidate.get("provider_profile_id"), str) or not isinstance(candidate.get("workspace_grant_id"), str):
            return _EvaluationOutcome("rejected", "proposal_malformed")
        service_candidate = service_candidates[0] if service_candidates else None
        if service_candidate is not None and (not isinstance(service_candidate, Mapping) or not isinstance(service_candidate.get("connection_id"), str)):
            return _EvaluationOutcome("rejected", "proposal_malformed")
        validation = await self._selection_validator.validate(
            provider_profile_id=candidate["provider_profile_id"],
            workspace_grant_id=candidate["workspace_grant_id"],
            connection_id=service_candidate["connection_id"] if isinstance(service_candidate, Mapping) else None,
            tool_name=service_candidate.get("tool_name") if isinstance(service_candidate, Mapping) else None,
            proposal=proposal, task=task,
        )
        if validation.selection is None:
            return _EvaluationOutcome("rejected", validation.reason_code or "invalid_provider_candidate")
        if grounding_tier == "exact_user_target" and not self._selection_validator._exact_target_is_verifiable(proposal, task, validation.selection):
            return await self._needs_user_outcome(proposal, task, reason_code="proposal_requires_user_choice")
        return _EvaluationOutcome("authorized", "verified_current_authority", selection=validation.selection)

    async def _needs_user_outcome(
        self, proposal: Mapping[str, object], task: Any, *, reason_code: str, include_options: bool = True
    ) -> _EvaluationOutcome:
        provider_candidates = proposal.get("provider_candidates")
        service_candidates = proposal.get("service_candidates")
        if not isinstance(provider_candidates, list):
            return _EvaluationOutcome("rejected", "proposal_malformed")
        service = service_candidates[0] if isinstance(service_candidates, list) and len(service_candidates) == 1 and isinstance(service_candidates[0], Mapping) else None
        options: list[_ValidatedSelection] = []
        for candidate in provider_candidates[:MAX_CHECKPOINT_OPTIONS] if include_options else []:
            if not isinstance(candidate, Mapping) or not isinstance(candidate.get("provider_profile_id"), str) or not isinstance(candidate.get("workspace_grant_id"), str):
                continue
            validation = await self._selection_validator.validate(
                provider_profile_id=str(candidate["provider_profile_id"]), workspace_grant_id=str(candidate["workspace_grant_id"]),
                connection_id=service.get("connection_id") if service else None,
                tool_name=service.get("tool_name") if service else None, proposal=proposal, task=task,
            )
            if validation.selection is not None:
                options.append(validation.selection)
        return _EvaluationOutcome(
            "needs_user", reason_code, options=tuple(options),
            cancel_value=f"{CANCEL_TOKEN_PREFIX}{uuid.uuid4()}",
        )

    async def _persist_initial(
        self, *, proposal_id: str, agent_task_id: str, root_task_id: str, status: str,
        reason_code: str, selection: _ValidatedSelection | None, options: Sequence[_ValidatedSelection],
        cancel_value: str | None, expires_at: str,
    ) -> dict[str, object]:
        record = await self._authorizations.create_initial_authorization(
            proposal_id=proposal_id, agent_task_id=agent_task_id, root_task_id=root_task_id,
            status=status, reason_code=reason_code,
            selected_provider_profile_id=selection.provider_profile_id if selection else None,
            selected_workspace_grant_id=selection.workspace_grant_id if selection else None,
            selected_connection_id=selection.selected_connection_id if selection else None,
            selected_tool_name=selection.selected_tool_name if selection else None,
            selected_service_policy=selection.selected_service_policy if selection else None,
            resolved_workspace_path=selection.resolved_workspace_path if selection else None,
            reference_paths=list(selection.reference_paths) if selection else [],
            choice_snapshot=self._checkpoint_factory.build_choice_snapshot(options=options, cancel_value=cancel_value),
            expires_at=expires_at,
        )
        return self._checkpoint_factory.public_result(record)

    async def _persist_response(
        self, *, parent: Mapping[str, object], proposal: Mapping[str, object], status: str,
        reason_code: str, selection: _ValidatedSelection | None, response_value: str,
    ) -> dict[str, object]:
        choice_snapshot = parent.get("choice_snapshot")
        if not isinstance(choice_snapshot, list):
            raise ProviderTargetAuthorizationError("choice_snapshot is malformed")
        try:
            record = await self._authorizations.create_response_authorization(
                parent_authorization_id=str(parent["id"]), proposal_id=str(parent["proposal_id"]),
                agent_task_id=str(parent["agent_task_id"]), root_task_id=str(parent["root_task_id"]),
                status=status, reason_code=reason_code,
                selected_provider_profile_id=selection.provider_profile_id if selection else None,
                selected_workspace_grant_id=selection.workspace_grant_id if selection else None,
                selected_connection_id=selection.selected_connection_id if selection else None,
                selected_tool_name=selection.selected_tool_name if selection else None,
                selected_service_policy=selection.selected_service_policy if selection else None,
                resolved_workspace_path=selection.resolved_workspace_path if selection else None,
                reference_paths=list(selection.reference_paths) if selection else [],
                choice_snapshot=[dict(item) for item in choice_snapshot if isinstance(item, Mapping)],
                response_value=response_value, expires_at=str(parent["expires_at"]),
            )
        except ProviderTargetAuthorizationConflictError as exc:
            raise ProviderTargetAuthorizationUnavailableError(
                reason_code="proposal_not_current_task", message=str(exc)
            ) from exc
        return self._checkpoint_factory.public_result(record)
