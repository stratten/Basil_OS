"""Provider-run execution for AgentTask lifecycle (Package 3A)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Optional

from api.services.agent_providers.acp.protocol import ACP_PROTOCOL_V1, ACP_PROTOCOL_VERSION
from api.services.agent_providers.acp.session_client import AcpClientError
from api.services.agent_providers.profiles.launch_validation import (
    ProviderLaunchValidationError,
    ProviderLaunchValidationService,
)
from api.services.agent_providers.runtime.process_supervisor import (
    ProviderLaunchOutcome,
    ProviderLaunchOutcomeStatus,
    ProviderProcessSupervisor,
)
from api.services.agent_processing.lifecycle.delegation.briefs import (
    compile_delegated_agent_brief,
)
from api.services.agent_processing.lifecycle.delegation.acp_executor import (
    AcpDelegatedAgentExecutor,
)
from api.services.agent_processing.lifecycle.delegation.acp_session_controller import (
    AcpDelegatedSessionController,
)
from .provider_activity_projector import ProviderActivityProjector
from .provider_interaction_coordinator import ProviderInteractionCoordinator
from .provider_permission_activation_coordinator import ProviderPermissionActivationCoordinator


_CLIENT_INFO = {"name": "Basil", "version": "1.0.0"}
_CLIENT_CAPABILITIES = {"elicitation": {"form": {}}}


def _safe_delegated_turn_response(response: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only bounded protocol-level turn evidence out of provider payloads."""

    safe: dict[str, Any] = {}
    stop_reason = response.get("stopReason")
    if isinstance(stop_reason, str):
        safe["stopReason"] = stop_reason[:200]
    usage = response.get("usage")
    if isinstance(usage, Mapping):
        safe_usage = {
            str(key): value
            for key, value in usage.items()
            if isinstance(key, str) and isinstance(value, (int, float))
        }
        if safe_usage:
            safe["usage"] = safe_usage
    return safe


def _build_observed_provider_capability_snapshot(
    outcome: ProviderLaunchOutcome,
) -> dict[str, Any]:
    """Persist the negotiated ACP major alongside the agent capability payload."""
    if outcome.protocol_version is None:
        return dict(outcome.agent_capabilities or {})
    return {
        "protocol_version": outcome.protocol_version,
        "agent_capabilities": dict(outcome.agent_capabilities or {}),
    }


class AgentTaskProviderRunService:
    """Launch one validated provider run and return a terminal operation result."""

    def __init__(
        self,
        *,
        provider_profile_repository: Any,
        provider_run_repository: Any,
        provider_interaction_repository: Any,
        routing_service: Any,
        delegated_agent_repository: Any | None = None,
        acp_session_controller: AcpDelegatedSessionController | None = None,
        delegated_agent_controller: Any | None = None,
        evidence_capture_service: Any | None = None,
        supervisor_factory: Callable[..., Any] = ProviderProcessSupervisor,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._provider_profile_repository = provider_profile_repository
        self._provider_run_repository = provider_run_repository
        self._provider_interaction_repository = provider_interaction_repository
        self._routing_service = routing_service
        self._delegated_agent_runs = delegated_agent_repository
        self._acp_sessions = acp_session_controller
        self._delegated_agent_controller = delegated_agent_controller
        self._evidence_capture = evidence_capture_service
        self._supervisor_factory = supervisor_factory
        self.logger = logger or logging.getLogger(__name__)

    async def run_provider_task(
        self,
        *,
        agent_task_id: str,
        agent_task_record: Any,
        provider_target: Mapping[str, Any],
    ) -> SimpleNamespace:
        provider_profile_id = (provider_target.get("provider_profile_id") or "").strip()
        workspace_grant_id = (provider_target.get("workspace_grant_id") or "").strip()
        if not provider_profile_id or not workspace_grant_id:
            raise ValueError("provider_target requires provider_profile_id and workspace_grant_id")

        candidate_workspace_path = provider_target.get("candidate_workspace_path")
        if not candidate_workspace_path:
            grant = await self._provider_profile_repository.get_workspace_grant(workspace_grant_id)
            if grant is None:
                return self._build_result(
                    success=False,
                    provider_run_id=None,
                    provider_profile_id=provider_profile_id,
                    display_name="Unknown provider",
                    runtime_version=None,
                    outcome_status="launch_validation_failed",
                    diagnostic_message=f"workspace grant {workspace_grant_id!r} does not exist",
                    user_feedback=None,
                    error_message=f"workspace grant {workspace_grant_id!r} does not exist",
                )
            candidate_workspace_path = grant["canonical_workspace_root"]

        validator = ProviderLaunchValidationService(self._provider_profile_repository)
        try:
            validated = await validator.validate_launch_request(
                provider_profile_id=provider_profile_id,
                workspace_grant_id=workspace_grant_id,
                candidate_workspace_path=str(candidate_workspace_path),
            )
        except ProviderLaunchValidationError as exc:
            return self._build_result(
                success=False,
                provider_run_id=None,
                provider_profile_id=provider_profile_id,
                display_name="Unknown provider",
                runtime_version=None,
                outcome_status="launch_validation_failed",
                diagnostic_message=str(exc),
                user_feedback=None,
                error_message=str(exc),
            )

        effective_root_task_id = agent_task_record.root_task_id or agent_task_record.id
        run = await self._provider_run_repository.create_run(
            agent_task_id=agent_task_record.id,
            root_task_id=effective_root_task_id,
            provider_profile_id=validated.provider_profile_id,
            workspace_grant_id=validated.workspace_grant_id,
        )

        root_task_id = getattr(agent_task_record, "root_task_id", None)
        previous_task_id = getattr(agent_task_record, "previous_task_id", None)
        supervisor: ProviderProcessSupervisor | None = None
        interaction_coordinator: ProviderInteractionCoordinator | None = None
        permission_coordinator: ProviderPermissionActivationCoordinator | None = None
        initialized_run: dict[str, object] | None = None

        try:
            await self._send_progress(
                "Launching provider",
                "started",
                agent_task_id=agent_task_id,
                root_task_id=root_task_id,
                previous_task_id=previous_task_id,
            )
            supervisor = self._supervisor_factory(
                validated,
                client_info=_CLIENT_INFO,
                client_capabilities=_CLIENT_CAPABILITIES,
            )
            outcome = await supervisor.launch()

            if outcome.status is not ProviderLaunchOutcomeStatus.RUNNING:
                await self._send_progress(
                    "Launching provider",
                    "failed",
                    agent_task_id=agent_task_id,
                    root_task_id=root_task_id,
                    previous_task_id=previous_task_id,
                )
                return await self._fail_run(
                    run,
                    outcome,
                    validated.display_name,
                    validated.provider_profile_id,
                )
            await self._send_progress(
                "Launching provider",
                "completed",
                agent_task_id=agent_task_id,
                root_task_id=root_task_id,
                previous_task_id=previous_task_id,
            )

            await self._send_progress(
                "Starting provider session",
                "started",
                agent_task_id=agent_task_id,
                root_task_id=root_task_id,
                previous_task_id=previous_task_id,
            )
            try:
                session = await supervisor.create_session()
            except (AcpClientError, OSError):
                await self._send_progress(
                    "Starting provider session",
                    "failed",
                    agent_task_id=agent_task_id,
                    root_task_id=root_task_id,
                    previous_task_id=previous_task_id,
                )
                return await self._fail_run(
                    run,
                    supervisor.last_outcome,
                    validated.display_name,
                    validated.provider_profile_id,
                )
            await self._send_progress(
                "Starting provider session",
                "completed",
                agent_task_id=agent_task_id,
                root_task_id=root_task_id,
                previous_task_id=previous_task_id,
            )

            generic_run = (
                await self._delegated_agent_runs.get_run_for_child(agent_task_id)
                if self._delegated_agent_runs is not None
                else None
            )
            async def observe_safe_activity(entry: Mapping[str, Any]) -> None:
                if generic_run is None or self._evidence_capture is None:
                    return
                turn_id = self._acp_sessions.active_evidence_turn_id(
                    delegated_agent_run_id=str(generic_run["id"])
                ) if self._acp_sessions is not None else None
                if turn_id is None:
                    return
                await self._evidence_capture.capture_activity(
                    delegated_agent_run_id=str(generic_run["id"]),
                    delegated_agent_turn_id=turn_id,
                    entry=entry,
                )
                await self._routing_service.publish_delegated_provider_report_cards(
                    parent_agent_task_id=str(generic_run["parent_agent_task_id"]),
                    root_task_id=str(generic_run["root_task_id"]),
                )

            activity_projector = ProviderActivityProjector(
                routing_service=self._routing_service,
                agent_task_id=agent_task_id,
                root_task_id=root_task_id,
                previous_task_id=previous_task_id,
                provider_run_id=str(run["id"]),
                workspace_root=validated.resolved_workspace_root,
                logger=self.logger,
                safe_activity_observer=observe_safe_activity,
            )
            activity_projector.bind_session(session.session_id)
            supervisor.register_notification_handler(
                "session/update",
                activity_projector.handle_session_update,
            )

            if outcome.protocol_version != ACP_PROTOCOL_V1:
                interaction_coordinator = ProviderInteractionCoordinator(
                    routing_service=self._routing_service,
                    provider_interaction_repository=self._provider_interaction_repository,
                    agent_task_id=agent_task_id,
                    root_task_id=root_task_id,
                    previous_task_id=previous_task_id,
                    provider_run_id=str(run["id"]),
                    logger=self.logger,
                    delegated_interaction_callback=self._delegated_interaction_callback(
                        agent_task_id=agent_task_id,
                    ),
                )
                interaction_coordinator.bind_session(session.session_id)
                supervisor.register_request_handler(
                    "elicitation/create",
                    interaction_coordinator.handle_elicitation_create,
                )

            permission_coordinator = ProviderPermissionActivationCoordinator(
                routing_service=self._routing_service,
                provider_interaction_repository=self._provider_interaction_repository,
                agent_task_id=agent_task_id,
                root_task_id=root_task_id,
                previous_task_id=previous_task_id,
                provider_run_id=str(run["id"]),
                protocol_version=outcome.protocol_version or ACP_PROTOCOL_VERSION,
                logger=self.logger,
                delegated_interaction_callback=self._delegated_interaction_callback(
                    agent_task_id=agent_task_id,
                ),
            )
            permission_coordinator.bind_session(session.session_id)
            supervisor.register_request_handler(
                "session/request_permission",
                permission_coordinator.handle_request_permission,
            )

            initialized_run = await self._provider_run_repository.mark_run_initialized(
                provider_run_id=str(run["id"]),
                expected_revision=int(run["revision"]),
                capabilities=_build_observed_provider_capability_snapshot(outcome),
                runtime_version=outcome.runtime_version or "unknown",
                provider_session_id=session.session_id,
            )

            await self._send_progress(
                "Running provider turn",
                "started",
                agent_task_id=agent_task_id,
                root_task_id=root_task_id,
                previous_task_id=previous_task_id,
            )
            try:
                artifacts = getattr(agent_task_record, "accumulated_artifacts", {})
                provider_delegation = (
                    artifacts.get("provider_delegation", {})
                    if isinstance(artifacts, Mapping)
                    else {}
                )
                rationale = (
                    provider_delegation.get("rationale")
                    if isinstance(provider_delegation, Mapping)
                    else None
                )
                assessment_reason = (
                    rationale.strip()
                    if isinstance(rationale, str) and rationale.strip()
                    else "The ACP provider executes the task in its own supervised turn."
                )
                brief = compile_delegated_agent_brief(
                    original_task=agent_task_record.transcribed_prompt,
                    executor_kind="acp_provider",
                    admitted_scope={
                        "read_only": False,
                    },
                    strategic_assessment={
                        "parallelism_reason": assessment_reason,
                        "independence_rationale": (
                            "The provider turn is isolated from the parent workflow and its "
                            "authority remains bounded by the admitted provider target."
                        ),
                        "expected_benefit": assessment_reason,
                        "parent_work_can_continue": False,
                        "child_cannot_delegate": True,
                    },
                )
                if generic_run is not None and self._acp_sessions is not None:
                    self._acp_sessions.register(
                        provider_run_id=str(run["id"]),
                        delegated_agent_run_id=str(generic_run["id"]),
                        supervisor=supervisor,
                        session_id=session.session_id,
                        runtime_identity={
                            "provider_profile_id": validated.provider_profile_id,
                            "executable_fingerprint": hashlib.sha256(
                                "\0".join(validated.launch_argv).encode("utf-8")
                            ).hexdigest(),
                            "runtime_version": outcome.runtime_version or "unknown",
                            "acp_major": outcome.protocol_version or ACP_PROTOCOL_VERSION,
                        },
                    )
                    turn_result = await AcpDelegatedAgentExecutor(
                        delegated_agent_repository=self._delegated_agent_runs,
                        session_controller=self._acp_sessions,
                        evidence_capture_service=self._evidence_capture,
                    ).start_turn(
                        delegated_agent_run_id=str(generic_run["id"]),
                        instruction=brief.worker_instruction,
                    )
                    prompt_response = _safe_delegated_turn_response(
                        turn_result["terminal_response"]
                    )
                    supervised_run = (
                        await self._delegated_agent_controller.handle_idle_turn(
                            delegated_agent_run=turn_result["run"],
                        )
                        if self._delegated_agent_controller is not None
                        else turn_result["run"]
                    )
                    if self._delegated_agent_controller is not None:
                        await self._delegated_agent_controller.present_acp_turn_to_parent(
                            delegated_agent_run=supervised_run,
                        )
                    return self._build_result(
                        success=True,
                        provider_run_id=str(run["id"]),
                        provider_profile_id=validated.provider_profile_id,
                        display_name=validated.display_name,
                        runtime_version=outcome.runtime_version,
                        outcome_status="awaiting_supervision",
                        diagnostic_message=None,
                        user_feedback=(
                            f"{validated.display_name} completed an ACP turn. "
                            "Basil is supervising the delegated work."
                        ),
                        error_message=None,
                        delegated_turn_response=prompt_response,
                        delegated_agent_run_id=str(supervised_run["id"]),
                        awaiting_supervision=True,
                    )
                else:
                    prompt_response = _safe_delegated_turn_response(
                        await supervisor.send_prompt(
                        session_id=session.session_id,
                        prompt=[{"type": "text", "text": brief.worker_instruction}],
                        )
                    )
                    final_outcome = await supervisor.complete_turn()
            except (AcpClientError, OSError):
                await self._send_progress(
                    "Running provider turn",
                    "failed",
                    agent_task_id=agent_task_id,
                    root_task_id=root_task_id,
                    previous_task_id=previous_task_id,
                )
                return await self._fail_run(
                    run,
                    supervisor.last_outcome,
                    validated.display_name,
                    validated.provider_profile_id,
                    expected_revision=int(initialized_run["revision"]),
                )

            if final_outcome.status is ProviderLaunchOutcomeStatus.COMPLETED:
                await self._provider_run_repository.transition_run(
                    provider_run_id=str(run["id"]),
                    expected_revision=int(initialized_run["revision"]),
                    next_status="completed",
                )
                await self._send_progress(
                    "Running provider turn",
                    "completed",
                    agent_task_id=agent_task_id,
                    root_task_id=root_task_id,
                    previous_task_id=previous_task_id,
                )
                return self._build_result(
                    success=True,
                    provider_run_id=str(run["id"]),
                    provider_profile_id=validated.provider_profile_id,
                    display_name=validated.display_name,
                    runtime_version=final_outcome.runtime_version,
                    outcome_status=final_outcome.status.value,
                    diagnostic_message=None,
                    user_feedback=(
                        f"{validated.display_name} completed an ACP turn. "
                        "Basil is evaluating the delegated work evidence."
                    ),
                    error_message=None,
                    delegated_turn_response=prompt_response,
                )

            terminal_reason = final_outcome.diagnostic_message or (
                f"provider exited with code {final_outcome.exit_code}"
            )
            await self._provider_run_repository.transition_run(
                provider_run_id=str(run["id"]),
                expected_revision=int(initialized_run["revision"]),
                next_status="failed",
                terminal_reason=terminal_reason,
            )
            await self._send_progress(
                "Running provider turn",
                "failed",
                agent_task_id=agent_task_id,
                root_task_id=root_task_id,
                previous_task_id=previous_task_id,
            )
            return self._build_result(
                success=False,
                provider_run_id=str(run["id"]),
                provider_profile_id=validated.provider_profile_id,
                display_name=validated.display_name,
                runtime_version=final_outcome.runtime_version,
                outcome_status=final_outcome.status.value,
                diagnostic_message=terminal_reason,
                user_feedback=None,
                error_message=terminal_reason,
            )
        except asyncio.CancelledError:
            if interaction_coordinator is not None:
                await interaction_coordinator.cancel_pending_interaction()
            if permission_coordinator is not None:
                await permission_coordinator.cancel_pending_interaction()
            if supervisor is not None:
                await self._shutdown_supervisor(supervisor, str(run["id"]))
            await self._transition_run_if_active(
                provider_run_id=str(run["id"]),
                next_status="canceled",
                terminal_reason=None,
            )
            raise
        except Exception as exc:
            self.logger.exception(
                "Unexpected provider-run failure for task %s; terminating the provider process",
                agent_task_id,
            )
            if interaction_coordinator is not None:
                await interaction_coordinator.cancel_pending_interaction()
            if permission_coordinator is not None:
                await permission_coordinator.cancel_pending_interaction()
            if supervisor is not None:
                await self._shutdown_supervisor(supervisor, str(run["id"]))
            diagnostic = str(exc) or "Provider run failed unexpectedly"
            await self._transition_run_if_active(
                provider_run_id=str(run["id"]),
                next_status="failed",
                terminal_reason=diagnostic,
            )
            return self._build_result(
                success=False,
                provider_run_id=str(run["id"]),
                provider_profile_id=validated.provider_profile_id,
                display_name=validated.display_name,
                runtime_version=None,
                outcome_status="unexpected_failure",
                diagnostic_message=diagnostic,
                user_feedback=None,
                error_message=diagnostic,
            )

    async def _fail_run(
        self,
        run: dict[str, object],
        outcome: ProviderLaunchOutcome | None,
        display_name: str,
        provider_profile_id: str,
        *,
        expected_revision: int | None = None,
    ) -> SimpleNamespace:
        diagnostic = (outcome.diagnostic_message if outcome else None) or "Provider run failed"
        outcome_status = outcome.status.value if outcome else "failed"
        revision = expected_revision if expected_revision is not None else int(run["revision"])
        await self._provider_run_repository.transition_run(
            provider_run_id=str(run["id"]),
            expected_revision=revision,
            next_status="failed",
            terminal_reason=diagnostic,
        )
        return self._build_result(
            success=False,
            provider_run_id=str(run["id"]),
            provider_profile_id=provider_profile_id,
            display_name=display_name,
            runtime_version=outcome.runtime_version if outcome else None,
            outcome_status=outcome_status,
            diagnostic_message=diagnostic,
            user_feedback=None,
            error_message=diagnostic,
        )

    async def _shutdown_supervisor(self, supervisor: Any, provider_run_id: str) -> None:
        """Terminate a provider only while its supervisor remains running."""

        last_outcome = getattr(supervisor, "last_outcome", None)
        if (
            last_outcome is not None
            and getattr(last_outcome, "status", None)
            is not ProviderLaunchOutcomeStatus.RUNNING
        ):
            return
        try:
            await supervisor.cancel()
            return
        except Exception as exc:
            self.logger.warning(
                "Provider supervisor cancellation failed for run %s: %s",
                provider_run_id,
                exc,
            )

        client = getattr(supervisor, "client", None)
        close = getattr(client, "close", None)
        if not callable(close):
            return
        try:
            await close()
        except Exception as exc:
            self.logger.error(
                "Provider client cleanup failed for run %s: %s",
                provider_run_id,
                exc,
            )

    async def _transition_run_if_active(
        self,
        *,
        provider_run_id: str,
        next_status: str,
        terminal_reason: str | None,
    ) -> None:
        """Transition the current revision when an interrupted run is still active."""
        try:
            current = await self._provider_run_repository.get_run(provider_run_id)
            if current is None or current["status"] in {"completed", "failed", "canceled"}:
                return
            await self._provider_run_repository.transition_run(
                provider_run_id=provider_run_id,
                expected_revision=int(current["revision"]),
                next_status=next_status,
                terminal_reason=terminal_reason,
            )
        except Exception as exc:
            self.logger.error(
                "Unable to persist provider run %s as %s: %s",
                provider_run_id,
                next_status,
                exc,
            )

    def _delegated_interaction_callback(self, *, agent_task_id: str):
        async def callback(
            *,
            interaction_id: str,
            permission: bool,
            resolved: bool = False,
        ) -> None:
            if self._delegated_agent_runs is None or self._delegated_agent_controller is None:
                return
            run = await self._delegated_agent_runs.get_run_for_child(agent_task_id)
            if run is None:
                return
            if resolved:
                await self._delegated_agent_controller.handle_provider_interaction_resolved(
                    delegated_agent_run=run,
                    interaction_id=interaction_id,
                )
                return
            await self._delegated_agent_controller.handle_provider_interaction_opened(
                delegated_agent_run=run,
                interaction_id=interaction_id,
                permission=permission,
            )
        return callback

    def _build_result(
        self,
        *,
        success: bool,
        provider_run_id: str | None,
        provider_profile_id: str,
        display_name: str,
        runtime_version: str | None,
        outcome_status: str,
        diagnostic_message: str | None,
        user_feedback: str | None,
        error_message: str | None,
        delegated_turn_response: Mapping[str, Any] | None = None,
        delegated_agent_run_id: str | None = None,
        awaiting_supervision: bool = False,
    ) -> SimpleNamespace:
        data = {
            "provider_run_id": provider_run_id,
            "provider_profile_id": provider_profile_id,
            "display_name": display_name,
            "runtime_version": runtime_version,
            "outcome_status": outcome_status,
        }
        if diagnostic_message:
            data["diagnostic_message"] = diagnostic_message
        if delegated_turn_response is not None:
            data["delegated_turn_response"] = dict(delegated_turn_response)
        if delegated_agent_run_id is not None:
            data["delegated_agent_run_id"] = delegated_agent_run_id
        if awaiting_supervision:
            data["awaiting_delegated_supervision"] = True
        return SimpleNamespace(
            operation="provider_run",
            success=success,
            data=data,
            user_feedback=user_feedback or error_message or "Provider run failed",
            error_message=error_message,
            widget_content_delivered=False,
        )

    async def _send_progress(
        self,
        step: str,
        status: str,
        *,
        agent_task_id: str,
        root_task_id: str | None,
        previous_task_id: str | None,
    ) -> None:
        await self._routing_service.send_progress_update(
            step,
            status,
            agent_task_id=agent_task_id,
            root_task_id=root_task_id,
            previous_task_id=previous_task_id,
        )


__all__ = ["AgentTaskProviderRunService"]
