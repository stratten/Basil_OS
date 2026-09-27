"""Submit validated provider delegations through canonical Agent Task routing."""

from __future__ import annotations

from typing import Any, Dict


def _require_nonblank_strings(**values: object) -> None:
    for field_name, value in values.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} is required")


class AuthorizedProviderDelegationSubmissionService:
    """Own the internal submission boundary for authorized provider children."""

    def __init__(
        self,
        submission_service: Any,
        *,
        delegated_agent_controller: Any | None = None,
    ) -> None:
        self._submission_service = submission_service
        self.delegated_agent_controller = delegated_agent_controller

    async def reserve_authorized_provider_delegation(
        self,
        *,
        agent_task: str,
        child_agent_task_id: str,
        root_task_id: str,
        parent_agent_task_id: str,
        chain_sequence_number: int,
        delegation_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist one authorized provider child without dispatching its routing work."""
        _require_nonblank_strings(
            agent_task=agent_task,
            child_agent_task_id=child_agent_task_id,
            root_task_id=root_task_id,
            parent_agent_task_id=parent_agent_task_id,
        )
        if not isinstance(chain_sequence_number, int) or chain_sequence_number < 1:
            raise ValueError("chain_sequence_number must be a positive integer")
        if not isinstance(delegation_context, dict):
            raise ValueError("delegation_context must be an object")
        provider_target = delegation_context.get("provider_target")
        if not isinstance(provider_target, dict):
            raise ValueError("delegation_context requires an authorized provider_target")
        _require_nonblank_strings(
            provider_profile_id=provider_target.get("provider_profile_id"),
            workspace_grant_id=provider_target.get("workspace_grant_id"),
        )
        reserve = getattr(self._submission_service, "reserve_delegated_agent_task", None)
        if not callable(reserve):
            raise RuntimeError("delegated child reservation is unavailable")
        return await reserve(
            agent_task=agent_task,
            child_agent_task_id=child_agent_task_id,
            root_task_id=root_task_id,
            parent_agent_task_id=parent_agent_task_id,
            chain_sequence_number=chain_sequence_number,
            session_type="provider_delegation",
            accumulated_artifacts={**delegation_context, "provider_target": provider_target},
        )

    async def dispatch_reserved_authorized_provider_delegation(
        self,
        *,
        child_agent_task_id: str,
        root_task_id: str,
        parent_agent_task_id: str,
    ) -> Dict[str, Any]:
        dispatch = getattr(self._submission_service, "dispatch_reserved_delegated_agent_task", None)
        if not callable(dispatch):
            raise RuntimeError("delegated child dispatch is unavailable")
        return await dispatch(
            child_agent_task_id=child_agent_task_id,
            root_task_id=root_task_id,
            parent_agent_task_id=parent_agent_task_id,
        )

    async def submit_authorized_provider_delegation(self, **kwargs: Any) -> Dict[str, Any]:
        """Compatibility wrapper; new callers must reserve, admit, then dispatch."""

        return await self.reserve_authorized_provider_delegation(**kwargs)
