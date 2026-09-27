"""Policy-driven lifecycle controller for generic delegated child agents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .acp_executor import AcpDelegatedAgentExecutor


class DelegatedAgentController:
    """Own follow-ups and terminal evidence before parent continuation."""

    def __init__(
        self,
        *,
        delegated_agent_repository: Any,
        workflow_coordinator: Any,
        acp_session_controller: Any | None = None,
        executor_registry: Mapping[str, Any] | None = None,
        delegated_agent_evidence_service: Any | None = None,
        evidence_capture_service: Any | None = None,
        provider_state_publisher: Any | None = None,
        delegated_agent_workspace_verifier: Any | None = None,
    ) -> None:
        self._runs = delegated_agent_repository
        self._workflow_coordinator = workflow_coordinator
        self._acp_sessions = acp_session_controller
        self._executors = dict(executor_registry or {})
        self._evidence_service = delegated_agent_evidence_service
        self._evidence_capture = evidence_capture_service
        self._provider_state_publisher = provider_state_publisher
        self._workspace_verifier = delegated_agent_workspace_verifier

    async def handle_idle_turn(
        self, *, delegated_agent_run: Mapping[str, Any], reason: str = "idle_turn_requires_supervision"
    ) -> dict[str, Any]:
        """Classify an ACP transport return as supervision due, never as success."""

        if delegated_agent_run["status"] != "idle":
            raise RuntimeError("only an idle delegated child may be supervised")
        return await self.require_supervision(delegated_agent_run=delegated_agent_run, reason=reason)

    async def handle_provider_interaction_opened(
        self, *, delegated_agent_run: Mapping[str, Any], interaction_id: str, permission: bool = False
    ) -> dict[str, Any]:
        """Record that an ACP turn is waiting on the provider; do not change generic status."""

        if delegated_agent_run["status"] in {"settled", "failed", "cancelled", "cancelling"}:
            raise RuntimeError("terminal or cancelling delegated child cannot open an interaction")
        if self._acp_sessions is not None:
            self._acp_sessions.interaction_opened(
                delegated_agent_run_id=str(delegated_agent_run["id"]), interaction_id=interaction_id
            )
        return dict(delegated_agent_run)

    async def handle_provider_interaction_resolved(
        self, *, delegated_agent_run: Mapping[str, Any], interaction_id: str
    ) -> dict[str, Any]:
        """Record that an interaction cleared; `AcpDelegatedAgentExecutor._send_turn` remains the
        sole writer that moves `running` to `idle`, and `require_supervision` remains the sole
        writer that moves `idle` to `supervision_due`."""

        if self._acp_sessions is not None:
            self._acp_sessions.interaction_resolved(
                delegated_agent_run_id=str(delegated_agent_run["id"]), interaction_id=interaction_id
            )
        return dict(delegated_agent_run)

    async def handle_dependency_settled(self, *, parent_agent_task_id: str) -> list[dict[str, Any]]:
        """Expose only reservations whose declared dependencies are now terminal."""

        return await self._runs.list_ready_reservations(parent_agent_task_id)

    def get_acp_runtime_identity(
        self, *, delegated_agent_run_id: str
    ) -> Mapping[str, Any] | None:
        """Return the live ACP tuple for diagnostics only; it no longer gates a follow-up."""

        if self._acp_sessions is None:
            return None
        return self._acp_sessions.get_runtime_identity(delegated_agent_run_id)

    async def require_supervision(
        self,
        *,
        delegated_agent_run: Mapping[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        """Mark an idle child for a deterministic next supervisory action."""

        if delegated_agent_run["status"] != "idle":
            raise RuntimeError("only an idle delegated child may require supervision")
        return await self._runs.transition_run(
            delegated_agent_run_id=str(delegated_agent_run["id"]),
            expected_revision=int(delegated_agent_run["revision"]),
            next_status="supervision_due",
        )

    async def continue_acp_run(
        self,
        *,
        delegated_agent_run: Mapping[str, Any],
        instruction: str,
    ) -> dict[str, Any]:
        """Continue an already-authorized, live ACP session without runtime certification."""

        if delegated_agent_run["executor_kind"] != "acp_provider":
            raise RuntimeError("only ACP delegated children can receive ACP follow-ups")
        if delegated_agent_run["status"] != "supervision_due":
            raise RuntimeError("delegated ACP child is not eligible for a follow-up")
        if self._acp_sessions is None:
            raise RuntimeError("ACP follow-up supervision is unavailable")
        executor = AcpDelegatedAgentExecutor(
            delegated_agent_repository=self._runs,
            session_controller=self._acp_sessions,
            evidence_capture_service=self._evidence_capture,
        )
        turn_result = await executor.request_follow_up(
            delegated_agent_run_id=str(delegated_agent_run["id"]),
            instruction=instruction,
        )
        supervised_run = await self.require_supervision(
            delegated_agent_run=turn_result["run"],
            reason="idle_turn_requires_supervision",
        )
        return {
            "run": supervised_run,
            "terminal_response": dict(turn_result["terminal_response"]),
            "session": dict(self._acp_sessions.describe(str(delegated_agent_run["id"]))),
        }

    async def present_acp_turn_to_parent(
        self,
        *,
        delegated_agent_run: Mapping[str, Any],
    ) -> None:
        """Hand one supervision-due ACP turn to its paused parent workflow."""

        if delegated_agent_run["executor_kind"] != "acp_provider":
            raise RuntimeError("only an ACP delegated child can be presented for supervision")
        if delegated_agent_run["status"] != "supervision_due":
            raise RuntimeError("delegated_agent_run must be supervision_due before parent presentation")

        parent_agent_task_id = str(delegated_agent_run["parent_agent_task_id"])
        delegated_agent_run_id = str(delegated_agent_run["id"])
        observed_capture_state = (
            self._evidence_capture.capture_state(delegated_agent_run_id=delegated_agent_run_id)
            if self._evidence_capture is not None
            else "unavailable"
        )
        report_card: dict[str, Any] = {
            "delegated_agent_run_id": delegated_agent_run_id,
            "run_status": delegated_agent_run["status"],
            "run_revision": delegated_agent_run["revision"],
            "capture_state": "unavailable",
            "evidence_count": 0,
            "latest_summary": None,
            "claims": [],
            "artifacts": [],
            "next_after_sequence": None,
        }
        if self._evidence_service is not None:
            try:
                report_card = await self._evidence_service.build_parent_supervision_snapshot(
                    parent_agent_task_id=parent_agent_task_id,
                    delegated_agent_run_id=delegated_agent_run_id,
                    capture_state=observed_capture_state,
                )
            except Exception:
                pass
        if self._provider_state_publisher is not None:
            try:
                root_task_id = str(delegated_agent_run.get("root_task_id") or parent_agent_task_id)
                await self._provider_state_publisher.publish_delegated_provider_state(
                    parent_agent_task_id=parent_agent_task_id,
                    root_task_id=root_task_id,
                    delegation_id=delegated_agent_run_id,
                    state="supervision_due",
                    message=(
                        "Delegated provider turn is ready for parent supervision; "
                        f"evidence capture is {report_card.get('capture_state', 'unavailable')}."
                    ),
                )
            except Exception:
                pass
        await self._workflow_coordinator.resume_workflow_for_delegated_supervision(
            parent_agent_task_id=parent_agent_task_id,
            delegated_agent_run=delegated_agent_run,
            report_card=report_card,
        )

    async def cancel_acp_run_for_supervision(
        self,
        *,
        delegated_agent_run: Mapping[str, Any],
        summary: str,
    ) -> dict[str, Any]:
        """Cancel only the named owned ACP run while it is due for supervision."""

        if delegated_agent_run["executor_kind"] != "acp_provider":
            raise RuntimeError("only an ACP delegated child can be cancelled through this path")
        if delegated_agent_run["status"] != "supervision_due":
            raise RuntimeError("delegated_agent_run must be supervision_due to cancel through supervision")
        if self._acp_sessions is None:
            raise RuntimeError("ACP cancellation is unavailable")
        cancelling = await self._runs.transition_run(
            delegated_agent_run_id=str(delegated_agent_run["id"]),
            expected_revision=int(delegated_agent_run["revision"]),
            next_status="cancelling",
        )
        await self._acp_sessions.cancel(delegated_agent_run_id=str(cancelling["id"]))
        return await self.settle_run(
            delegated_agent_run=cancelling,
            child_status="cancelled",
            summary=summary,
            evidence_state="unavailable",
            receipt_references=(),
        )

    async def inspect_evidence(
        self,
        *,
        delegated_agent_run: Mapping[str, Any],
        evidence_id: str | None,
        after_sequence: int | None,
        limit: int,
    ) -> dict[str, Any]:
        if self._evidence_service is None:
            raise RuntimeError("delegated evidence inspection is unavailable")
        return await self._evidence_service.inspect_parent_evidence(
            parent_agent_task_id=str(delegated_agent_run["parent_agent_task_id"]),
            delegated_agent_run_id=str(delegated_agent_run["id"]),
            evidence_id=evidence_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    async def verify_workspace_artifact(
        self,
        *,
        delegated_agent_run: Mapping[str, Any],
        artifact_evidence_id: str,
    ) -> dict[str, Any]:
        if self._workspace_verifier is None:
            raise RuntimeError("delegated workspace verification is unavailable")
        return await self._workspace_verifier.verify_artifact(
            parent_agent_task_id=str(delegated_agent_run["parent_agent_task_id"]),
            delegated_agent_run_id=str(delegated_agent_run["id"]),
            artifact_evidence_id=artifact_evidence_id,
        )

    async def settle_acp_run_for_supervision(
        self,
        *,
        delegated_agent_run: Mapping[str, Any],
        summary: str,
        verification_evidence_id: str | None,
    ) -> dict[str, Any]:
        if delegated_agent_run["executor_kind"] != "acp_provider":
            raise RuntimeError("only an ACP delegated child can settle through supervision")
        if delegated_agent_run["status"] != "supervision_due":
            raise RuntimeError("delegated_agent_run must be supervision_due to settle through supervision")
        evidence_state = "provider_reported"
        receipt_references: list[Mapping[str, Any]] = []
        if verification_evidence_id is not None:
            if self._workspace_verifier is None:
                raise RuntimeError("delegated workspace verification is unavailable")
            verification = await self._workspace_verifier.get_verification_for_settlement(
                parent_agent_task_id=str(delegated_agent_run["parent_agent_task_id"]),
                delegated_agent_run_id=str(delegated_agent_run["id"]),
                verification_evidence_id=verification_evidence_id,
            )
            evidence_state = str(verification["verification_state"])
            receipt_references = [{
                "evidence_id": verification["id"],
                "verification_state": verification["verification_state"],
            }]
        return await self.settle_run(
            delegated_agent_run=delegated_agent_run,
            child_status="completed",
            summary=summary,
            evidence_state=evidence_state,
            receipt_references=receipt_references,
        )

    async def settle_run(
        self,
        *,
        delegated_agent_run: Mapping[str, Any],
        child_status: str,
        summary: str,
        evidence_state: str,
        receipt_references: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        """Persist one terminal outcome and close an ACP session only after it is durable.

        Does not resume the parent. A live parent workflow must call this directly
        (never `settle_run_and_maybe_resume_parent`) to avoid recursively resuming
        the graph it is currently executing.
        """
        terminal_status = {
            "completed": "settled",
            "failed": "failed",
            "cancelled": "cancelled",
        }.get(child_status)
        if terminal_status is None:
            raise ValueError("child_status must be completed, failed, or cancelled")
        settled = await self._runs.record_outcome(
            delegated_agent_run_id=str(delegated_agent_run["id"]),
            expected_revision=int(delegated_agent_run["revision"]),
            transport_state=str(delegated_agent_run["executor_kind"]),
            executor_result_state=child_status,
            evidence_state=evidence_state,
            summary=summary,
            receipt_references=list(receipt_references),
            terminal_status=terminal_status,
        )
        if settled.get("executor_kind") == "acp_provider" and self._acp_sessions is not None:
            await self._acp_sessions.close(
                delegated_agent_run_id=str(settled["id"]),
                terminal_run=settled,
            )
        return settled

    async def settle_run_and_maybe_resume_parent(
        self,
        *,
        delegated_agent_run: Mapping[str, Any],
        child_status: str,
        summary: str,
        evidence_state: str,
        receipt_references: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        """Persist one terminal outcome and resume the parent only after every child settles."""
        settled = await self.settle_run(
            delegated_agent_run=delegated_agent_run,
            child_status=child_status,
            summary=summary,
            evidence_state=evidence_state,
            receipt_references=receipt_references,
        )
        if await self._runs.list_active_for_parent(str(settled["parent_agent_task_id"])):
            return settled
        outcomes = await self._runs.list_outcomes_for_parent(str(settled["parent_agent_task_id"]))
        await self._workflow_coordinator.resume_workflow_after_provider_delegation(
            parent_agent_task_id=str(settled["parent_agent_task_id"]),
            child_outcomes=outcomes,
        )
        return settled

    async def settle_and_resume(self, **kwargs: Any) -> dict[str, Any]:
        """Compatibility entrypoint retained until all callers use the generic name."""
        return await self.settle_run_and_maybe_resume_parent(**kwargs)

    async def handle_no_progress_lease(
        self, *, delegated_agent_run: Mapping[str, Any], reason: str = "no_progress_lease_expired"
    ) -> dict[str, Any]:
        return await self.handle_idle_turn(delegated_agent_run=delegated_agent_run, reason=reason)

    async def cancel_parent_runs(self, *, parent_agent_task_id: str) -> list[dict[str, Any]]:
        """Fence generic runs before executor cancellation and retain prior evidence."""

        runs = await self._runs.list_active_for_parent(parent_agent_task_id)
        cancelled: list[dict[str, Any]] = []
        for run in runs:
            fenced = await self._runs.transition_run(
                delegated_agent_run_id=str(run["id"]),
                expected_revision=int(run["revision"]),
                next_status="cancelling",
            )
            executor = self._executors.get(str(fenced["executor_kind"]))
            if executor is not None:
                await executor.cancel(delegated_agent_run_id=str(fenced["id"]))
            elif fenced["executor_kind"] == "acp_provider" and self._acp_sessions is not None:
                await self._acp_sessions.cancel(delegated_agent_run_id=str(fenced["id"]))
            cancelled.append(fenced)
        return cancelled
