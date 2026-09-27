"""Model-visible admission surface for bounded Basil-native child agents."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from api.services.agent_processing.lifecycle.delegation import (
    DelegatedAgentAdmissionService,
    DelegatedChildProposal,
    InternalAgentTaskExecutor,
    compile_delegated_agent_brief,
)
from api.services.agent_providers.targeting.delegation_service import ProviderDelegationWaitRequest

_EXISTING_RUN_ACTIONS = {
    "inspect",
    "inspect_evidence",
    "verify_artifact",
    "continue",
    "settle_completed",
    "settle_failed",
    "cancel",
}
_ALL_ACTIONS = {"propose", "admit", *_EXISTING_RUN_ACTIONS}


class DelegatedAgentInput(BaseModel):
    """One independently scoped internal child proposal, or one action against an existing run."""

    model_config = ConfigDict(extra="forbid")

    action: str = Field(pattern="^(propose|admit|inspect|inspect_evidence|verify_artifact|continue|settle_completed|settle_failed|cancel)$")
    objective: str = Field(default="", max_length=4_000)
    mutable_paths: list[str] = Field(default_factory=list, max_length=20)
    read_only: bool = False
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=20)
    rationale: str = Field(default="", max_length=1_000)
    dependency_ids: list[str] = Field(default_factory=list, max_length=20)
    delegated_agent_run_id: str | None = Field(default=None, max_length=200)
    summary: str = Field(default="", max_length=4_000)
    evidence_id: str | None = Field(default=None, max_length=200)
    verification_evidence_id: str | None = Field(default=None, max_length=200)
    after_sequence: int | None = Field(default=None, ge=0)
    evidence_limit: int = Field(default=12, ge=1, le=24)
    inspection_purpose: str = Field(default="", max_length=300)


def _allows_child_delegation(parent: Any) -> bool:
    artifacts = getattr(parent, "accumulated_artifacts", None)
    if not isinstance(artifacts, dict):
        return True
    envelope = artifacts.get("delegated_capability_envelope")
    return not isinstance(envelope, dict) or envelope.get("allows_child_delegation") is not False


async def _handle_existing_run_action(
    *,
    action: str,
    delegated_agent_run_id: str | None,
    parent_agent_task_id: str,
    knowledge: Any,
    instruction: str,
    summary: str,
    submission_service: Any,
    evidence_id: str | None = None,
    verification_evidence_id: str | None = None,
    after_sequence: int | None = None,
    evidence_limit: int = 12,
    inspection_purpose: str = "",
) -> str:
    if not delegated_agent_run_id:
        return json.dumps({"ok": False, "error": "delegated_agent_run_id is required"})
    run = await knowledge.delegated_agent_repository.get_run(delegated_agent_run_id)
    if run is None or run["parent_agent_task_id"] != parent_agent_task_id:
        return json.dumps({"ok": False, "error": "delegated child is not owned by this parent"})
    if action == "inspect":
        return json.dumps(
            {
                "ok": True,
                "run": {
                    "id": run["id"],
                    "status": run["status"],
                    "dependency_run_ids": run["dependency_run_ids"],
                    "executor_kind": run["executor_kind"],
                },
            }
        )
    orchestrator = getattr(submission_service, "_orchestrator", None)
    controller = getattr(orchestrator, "delegated_agent_controller", None) if orchestrator is not None else None
    if controller is None:
        controller = getattr(submission_service, "delegated_agent_controller", None)
    if action == "inspect_evidence":
        if controller is None:
            return json.dumps({"ok": False, "error": "delegated evidence inspection is unavailable"})
        if not inspection_purpose.strip():
            return json.dumps({"ok": False, "error": "inspection_purpose is required"})
        try:
            inspection = await controller.inspect_evidence(
                delegated_agent_run=run,
                evidence_id=evidence_id,
                after_sequence=after_sequence,
                limit=evidence_limit,
            )
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)})
        return json.dumps({"ok": True, "inspection": inspection})
    if action == "verify_artifact":
        if controller is None:
            return json.dumps({"ok": False, "error": "delegated workspace verification is unavailable"})
        if not evidence_id:
            return json.dumps({"ok": False, "error": "evidence_id is required for artifact verification"})
        try:
            verification = await controller.verify_workspace_artifact(
                delegated_agent_run=run,
                artifact_evidence_id=evidence_id,
            )
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)})
        return json.dumps(
            {
                "ok": True,
                "verification": {
                    "evidence_id": verification["id"],
                    "verification_state": verification["verification_state"],
                    "summary": verification["summary"],
                    "structured_data": verification["structured_data"],
                },
            }
        )
    if action == "cancel":
        if run["status"] in {"settled", "failed", "cancelled"}:
            return json.dumps({"ok": True, "status": run["status"]})
        if controller is None:
            return json.dumps({"ok": False, "error": "delegated cancellation is unavailable"})
        if run["executor_kind"] == "acp_provider":
            if run["status"] != "supervision_due":
                return json.dumps(
                    {
                        "ok": False,
                        "error": (
                            "an ACP delegated child can be cancelled by its supervisor "
                            "only while supervision_due"
                        ),
                    }
                )
            try:
                cancelled_run = await controller.cancel_acp_run_for_supervision(
                    delegated_agent_run=run,
                    summary=summary.strip() or "Parent cancelled this delegated ACP run.",
                )
            except Exception as exc:
                return json.dumps({"ok": False, "error": str(exc)})
            return json.dumps({"ok": True, "status": cancelled_run["status"]})
        cancelled = await controller.cancel_parent_runs(parent_agent_task_id=parent_agent_task_id)
        matching = [item for item in cancelled if str(item.get("id")) == delegated_agent_run_id]
        status = matching[0]["status"] if matching else "cancelling"
        return json.dumps({"ok": True, "status": status})
    if action == "continue":
        if run["executor_kind"] != "acp_provider":
            return json.dumps({"ok": False, "error": "only ACP delegated children can receive follow-ups"})
        if run["status"] != "supervision_due":
            return json.dumps({"ok": False, "error": "delegated child is not due for supervision"})
        if controller is None:
            return json.dumps({"ok": False, "error": "ACP continuation is unavailable"})
        if not instruction.strip():
            return json.dumps({"ok": False, "error": "objective is required for ACP continuation"})
        try:
            result = await controller.continue_acp_run(
                delegated_agent_run=run,
                instruction=instruction.strip(),
            )
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)})
        return json.dumps(
            {
                "ok": True,
                "status": result["run"]["status"],
                "terminal_response": result["terminal_response"],
                "session": result["session"],
            }
        )
    if action in {"settle_completed", "settle_failed"}:
        if not summary.strip():
            return json.dumps({"ok": False, "error": "summary is required to settle a delegated child"})
        if controller is None:
            return json.dumps({"ok": False, "error": "delegated settlement is unavailable"})
        try:
            if action == "settle_completed" and run["executor_kind"] == "acp_provider":
                settled = await controller.settle_acp_run_for_supervision(
                    delegated_agent_run=run,
                    summary=summary.strip(),
                    verification_evidence_id=verification_evidence_id,
                )
            else:
                child_status = "completed" if action == "settle_completed" else "failed"
                evidence_state = "provider_reported" if action == "settle_completed" else "unavailable"
                settled = await controller.settle_run(
                    delegated_agent_run=run,
                    child_status=child_status,
                    summary=summary.strip(),
                    evidence_state=evidence_state,
                )
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)})
        return json.dumps({"ok": True, "status": settled["status"]})
    return json.dumps({"ok": False, "error": "unsupported delegated-agent action"})


def create_delegated_agent_tool(
    *,
    agent_task_id: str | None,
    root_task_id: str | None,
    submission_service: Any,
) -> StructuredTool:
    """Create a turn-bound internal-child admission and ACP-supervision tool."""

    async def delegated_agent(
        objective: str = "",
        rationale: str = "",
        mutable_paths: list[str] | None = None,
        read_only: bool = False,
        acceptance_criteria: list[str] | None = None,
        action: str = "propose",
        dependency_ids: list[str] | None = None,
        delegated_agent_run_id: str | None = None,
        summary: str = "",
        evidence_id: str | None = None,
        verification_evidence_id: str | None = None,
        after_sequence: int | None = None,
        evidence_limit: int = 12,
        inspection_purpose: str = "",
    ) -> str:
        if action not in _ALL_ACTIONS:
            return json.dumps({"ok": False, "error": "unsupported delegated-agent action"})
        if not agent_task_id or not root_task_id:
            return json.dumps({"ok": False, "error": "delegated_agent is unavailable for this task"})
        from api.dependencies import get_sqlite_knowledge_service

        knowledge = get_sqlite_knowledge_service()
        parent = await knowledge.agent_task_service.get_agent_task(agent_task_id)
        if parent is None:
            return json.dumps({"ok": False, "error": "current parent task is unavailable"})
        if not _allows_child_delegation(parent):
            return json.dumps({"ok": False, "error": "delegated children cannot create or control child delegations"})
        if action in _EXISTING_RUN_ACTIONS:
            return await _handle_existing_run_action(
                action=action,
                delegated_agent_run_id=delegated_agent_run_id,
                parent_agent_task_id=agent_task_id,
                knowledge=knowledge,
                instruction=objective,
                summary=summary,
                submission_service=submission_service,
                evidence_id=evidence_id,
                verification_evidence_id=verification_evidence_id,
                after_sequence=after_sequence,
                evidence_limit=evidence_limit,
                inspection_purpose=inspection_purpose,
            )
        proposal = DelegatedChildProposal(
            executor_kind="internal_agent",
            objective=objective,
            mutable_paths=tuple(path for path in mutable_paths or [] if isinstance(path, str)),
            read_only=bool(read_only),
            dependency_ids=tuple(dependency_ids or []),
            acceptance_criteria=tuple(acceptance_criteria or []),
            model_id=(parent.accumulated_artifacts or {}).get("model_id")
            if isinstance(parent.accumulated_artifacts, dict)
            else None,
            strategic_assessment={
                "parallelism_reason": rationale,
                "independence_rationale": rationale,
                "expected_benefit": rationale,
                "parent_work_can_continue": True,
                "child_cannot_delegate": True,
            },
        )
        admitted_scope = DelegatedAgentAdmissionService().validate(
            proposal=proposal,
            parent_agent_task_id=agent_task_id,
            root_task_id=root_task_id,
        )
        brief = compile_delegated_agent_brief(
            original_task=objective,
            executor_kind="internal_agent",
            admitted_scope=admitted_scope,
            dependency_ids=proposal.dependency_ids,
            acceptance_criteria=proposal.acceptance_criteria,
            strategic_assessment=admitted_scope["strategic_assessment"],
        )
        if action == "propose":
            return json.dumps(
                {
                    "ok": True,
                    "proposal": {
                        "digest": brief.digest,
                        "objective": brief.objective,
                        "scope": brief.admitted_scope,
                        "strategic_assessment": brief.strategic_assessment,
                    },
                }
            )
        raw_submission_service = getattr(submission_service, "_submission_service", submission_service)
        result = await InternalAgentTaskExecutor(
            submission_service=raw_submission_service,
            delegated_agent_repository=knowledge.delegated_agent_repository,
        ).start(
            parent_agent_task_id=agent_task_id,
            root_task_id=root_task_id,
            parent_chain_sequence_number=int(parent.chain_sequence_number),
            model_id=(parent.accumulated_artifacts or {}).get("model_id")
            if isinstance(parent.accumulated_artifacts, dict)
            else None,
            brief=brief,
            evidence_policy={"required": "provider_reported"},
        )
        if result.get("ready") is False:
            return json.dumps({"ok": True, "blocked": result})
        raise ProviderDelegationWaitRequest(
            delegation_id=str(result["id"]),
            child_agent_task_id=str(result["child_agent_task_id"]),
        )

    return StructuredTool.from_function(
        coroutine=delegated_agent,
        name="delegated_agent",
        description=(
            "Delegate an independent, bounded subtask to a Basil-native child Agent Task, or "
            "supervise an existing delegated child (inspect/inspect_evidence/verify_artifact/"
            "continue/settle_completed/settle_failed/cancel). Use verify_artifact only with an "
            "opaque provider-reported evidence ID; it reads no model-supplied path and runs no command. "
            "Use summary to record a nonblank rationale when settling a child."
        ),
        args_schema=DelegatedAgentInput,
    )
