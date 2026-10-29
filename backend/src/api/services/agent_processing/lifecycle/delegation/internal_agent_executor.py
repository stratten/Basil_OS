"""Canonical AgentTask executor for Basil-native delegated child work."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from .briefs import DelegatedAgentBrief


class InternalAgentTaskExecutor:
    """Submit an internal child through the normal AgentTask routing lifecycle."""

    def __init__(self, *, submission_service: Any, delegated_agent_repository: Any) -> None:
        self._submission_service = submission_service
        self._delegated_agent_repository = delegated_agent_repository

    async def start(
        self,
        *,
        parent_agent_task_id: str,
        root_task_id: str,
        parent_chain_sequence_number: int,
        model_id: str | None,
        brief: DelegatedAgentBrief,
        evidence_policy: Mapping[str, Any],
    ) -> dict[str, object]:
        """Create one constrained internal child before atomically admitting it."""

        child_agent_task_id = str(uuid.uuid4())
        reserve = getattr(self._submission_service, "reserve_delegated_agent_task", None)
        dispatch = getattr(self._submission_service, "dispatch_reserved_delegated_agent_task", None)
        if not callable(reserve) or not callable(dispatch):
            raise RuntimeError("internal delegated child reservation and dispatch are unavailable")
        submission = await reserve(
            agent_task=brief.worker_instruction,
            child_agent_task_id=child_agent_task_id,
            root_task_id=root_task_id,
            parent_agent_task_id=parent_agent_task_id,
            chain_sequence_number=parent_chain_sequence_number + 1,
            session_type="internal_delegation",
            accumulated_artifacts={
                "model_id": model_id,
                "delegated_agent": {
                    "executor_kind": "internal_agent",
                    "admitted_scope": brief.admitted_scope,
                    "dependency_run_ids": list(brief.dependency_ids),
                    "acceptance_criteria": list(brief.acceptance_criteria),
                    "brief_digest": brief.digest,
                    "strategic_assessment": brief.strategic_assessment,
                },
                "delegated_capability_envelope": {
                    "allows_canonical_tools": True,
                    "allows_approval_decisions": False,
                    "allows_provider_credentials": False,
                    "allows_provider_selection": False,
                    "allows_ambient_parent_context": False,
                    "allows_child_delegation": False,
                },
            },
        )
        if not isinstance(submission, Mapping) or submission.get("status") != "routing":
            raise RuntimeError("internal delegated child reservation failed")
        await self._delegated_agent_repository.reserve_child_agent_task(
            parent_agent_task_id=parent_agent_task_id,
            root_task_id=root_task_id,
            child_agent_task_id=child_agent_task_id,
            executor_kind="internal_agent",
            dependency_run_ids=list(brief.dependency_ids),
            strategic_assessment=brief.strategic_assessment,
        )
        admission = await self._delegated_agent_repository.admit_reserved_run(
            child_agent_task_id=child_agent_task_id,
            admitted_scope=brief.admitted_scope,
            evidence_policy=evidence_policy,
            dependency_run_ids=list(brief.dependency_ids),
        )
        if admission.get("ready") is False:
            return admission
        await dispatch(
            child_agent_task_id=child_agent_task_id,
            root_task_id=root_task_id,
            parent_agent_task_id=parent_agent_task_id,
        )
        return admission
