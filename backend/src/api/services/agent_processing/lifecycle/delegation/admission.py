"""Deterministic validation for model-proposed delegated child work."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DelegatedChildProposal:
    """Bounded child-work declaration before executor-specific submission."""

    executor_kind: str
    objective: str
    mutable_paths: tuple[str, ...]
    read_only: bool
    dependency_ids: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    model_id: str | None = None
    strategic_assessment: Mapping[str, Any] | None = None


class DelegatedAgentAdmissionService:
    """Reject malformed, cyclic, or unsafe parallel child declarations."""

    def validate(
        self,
        *,
        proposal: DelegatedChildProposal,
        parent_agent_task_id: str,
        root_task_id: str,
    ) -> dict[str, Any]:
        if not parent_agent_task_id or not root_task_id:
            raise ValueError("delegated child requires parent and root task identity")
        if proposal.executor_kind not in {"acp_provider", "internal_agent"}:
            raise ValueError("delegated child executor_kind is unsupported")
        if not proposal.objective.strip():
            raise ValueError("delegated child objective is required")
        if proposal.model_id is not None and not proposal.model_id.strip():
            raise ValueError("delegated child model_id must be nonblank when provided")
        if len(proposal.mutable_paths) > 20:
            raise ValueError("delegated child exceeds the mutable-path bound")
        if not proposal.acceptance_criteria or any(
            not isinstance(criterion, str) or not criterion.strip()
            for criterion in proposal.acceptance_criteria
        ):
            raise ValueError("delegated child requires measurable acceptance criteria")
        if proposal.read_only and proposal.mutable_paths:
            raise ValueError("read-only delegated child cannot declare mutable paths")
        if len(set(proposal.dependency_ids)) != len(proposal.dependency_ids):
            raise ValueError("delegated child has duplicate dependency IDs")
        if any(not dependency_id.strip() for dependency_id in proposal.dependency_ids):
            raise ValueError("delegated child dependency IDs must be nonblank")
        if len(proposal.objective.encode("utf-8")) > 8_000:
            raise ValueError("delegated child objective exceeds the bounded size")
        if any(len(path.encode("utf-8")) > 1_024 or not path.strip() for path in proposal.mutable_paths):
            raise ValueError("delegated child mutable paths must be bounded nonblank strings")
        assessment = proposal.strategic_assessment
        if not isinstance(assessment, Mapping):
            raise ValueError("delegated child requires a strategic assessment")
        parallelism_reason = assessment.get("parallelism_reason")
        independence_rationale = assessment.get("independence_rationale")
        expected_benefit = assessment.get("expected_benefit")
        if not all(isinstance(value, str) and value.strip() for value in (
            parallelism_reason,
            independence_rationale,
            expected_benefit,
        )):
            raise ValueError("delegated strategic assessment requires nonblank reason, independence rationale, and benefit")
        if assessment.get("parent_work_can_continue") not in {True, False}:
            raise ValueError("delegated strategic assessment requires parent_work_can_continue")
        if assessment.get("child_cannot_delegate") is not True:
            raise ValueError("delegated child must be prohibited from nested delegation")
        return {
            "read_only": proposal.read_only,
            "mutable_paths": list(proposal.mutable_paths),
            "dependency_ids": sorted(set(proposal.dependency_ids)),
            "strategic_assessment": {
                "parallelism_reason": str(parallelism_reason).strip(),
                "independence_rationale": str(independence_rationale).strip(),
                "expected_benefit": str(expected_benefit).strip(),
                "parent_work_can_continue": bool(assessment["parent_work_can_continue"]),
                "child_cannot_delegate": True,
            },
            "delegated_capability_envelope": {
                "allows_canonical_tools": True,
                "allows_approval_decisions": False,
                "allows_provider_credentials": False,
                "allows_provider_selection": False,
                "allows_ambient_parent_context": False,
            },
        }
