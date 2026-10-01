"""
AgentTask Orchestrator - Event-Driven Integration.

This module is the public lifecycle facade. Submission, routing, processing,
and workflow-result responsibilities live in focused services.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from api.core.knowledge.sqlite.sqlite_knowledge_service import AgentTaskEvent, SQLiteKnowledgeService

from .agent_task_cancellation import AgentTaskCancellationRegistry
from .agent_task_event_handlers import AgentTaskEventHandlers
from .agent_task_provider_run_service import AgentTaskProviderRunService
from .agent_task_processing_service import AgentTaskProcessingService
from .agent_task_routing_service import AgentTaskRoutingService
from .agent_task_screen_context_service import AgentTaskScreenContextService
from .agent_task_state_manager import AgentTaskStateMachine, AgentTaskStatus
from .agent_task_submission_service import AgentTaskSubmissionService
from .agent_task_workflow_result_service import AgentTaskWorkflowResultService
from .authorized_provider_delegation_submission_service import (
    AuthorizedProviderDelegationSubmissionService,
)
from api.services.agent_processing.lifecycle.runtime.provider_delegation_result_bridge import (
    ProviderDelegationResultBridge,
)
from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import (
    WorkflowCoordinator,
)
from api.services.agent_processing.lifecycle.delegation.acp_session_controller import (
    AcpDelegatedSessionController,
)
from api.services.agent_processing.lifecycle.delegation.controller import DelegatedAgentController
from api.services.agent_processing.lifecycle.delegation.delegated_agent_evidence_capture_service import (
    DelegatedAgentEvidenceCaptureService,
)
from api.services.agent_processing.lifecycle.delegation.delegated_agent_evidence_service import (
    DelegatedAgentEvidenceService,
)
from api.services.agent_processing.lifecycle.delegation.delegated_agent_workspace_verifier import (
    DelegatedAgentWorkspaceVerifier,
)

logger = logging.getLogger(__name__)


class AgentTaskOrchestrator:
    """
    Orchestrates agent task processing using an event-driven architecture.

    This facade keeps the historical public API stable while delegating each
    lifecycle stage to a focused service.
    """

    def __init__(self, llm_service=None, websocket_manager=None, basil_services=None, db_service=None):
        self.llm_service = llm_service
        self.websocket_manager = websocket_manager
        self.basil_services = basil_services or {}
        self.logger = logging.getLogger(__name__)
        self._processed_events = set()
        self._processing_agent_tasks = set()
        self._cancellation = AgentTaskCancellationRegistry()

        self.db_service = db_service if db_service is not None else SQLiteKnowledgeService()
        self.state_machine = AgentTaskStateMachine()
        self.delegated_agent_repository = getattr(
            self.db_service, "delegated_agent_repository", None
        )
        self.delegated_agent_evidence_repository = getattr(
            self.db_service, "delegated_agent_evidence_repository", None
        )
        self.delegated_agent_evidence_capture_service = DelegatedAgentEvidenceCaptureService(
            evidence_repository=self.delegated_agent_evidence_repository
        )
        self.delegated_agent_evidence_service = DelegatedAgentEvidenceService(
            delegated_agent_repository=self.delegated_agent_repository,
            evidence_repository=self.delegated_agent_evidence_repository,
        )
        self.delegated_agent_workspace_verifier = DelegatedAgentWorkspaceVerifier(
            delegated_agent_repository=self.delegated_agent_repository,
            evidence_repository=self.delegated_agent_evidence_repository,
            provider_target_delegation_repository=self.db_service.provider_target_delegation_repository,
            provider_profile_repository=self.db_service.provider_profile_repository,
        )

        self.screen_context_service = AgentTaskScreenContextService(
            websocket_manager=websocket_manager,
            ocr_service=basil_services.get("ocr") if basil_services else None,
        )
        if basil_services:
            self.screen_context_service.initialize_services(basil_services)

        self.workflow_result_service = AgentTaskWorkflowResultService(
            db_service=self.db_service,
            websocket_manager=self.websocket_manager,
            basil_services=self.basil_services,
            is_canceled=self.is_agent_task_canceled,
            logger=self.logger,
        )
        self.routing_service = AgentTaskRoutingService(
            db_service=self.db_service,
            websocket_manager=self.websocket_manager,
            is_canceled=self.is_agent_task_canceled,
            logger=self.logger,
        )
        self.workflow_coordinator = WorkflowCoordinator(
            websocket_manager=self.websocket_manager,
            agent_task_submission_service=None,
        )
        self.acp_delegated_session_controller = AcpDelegatedSessionController()
        self.delegated_agent_controller = DelegatedAgentController(
            delegated_agent_repository=self.delegated_agent_repository,
            workflow_coordinator=self.workflow_coordinator,
            acp_session_controller=self.acp_delegated_session_controller,
            delegated_agent_evidence_service=self.delegated_agent_evidence_service,
            evidence_capture_service=self.delegated_agent_evidence_capture_service,
            provider_state_publisher=self.routing_service,
            delegated_agent_workspace_verifier=self.delegated_agent_workspace_verifier,
        )
        self.provider_delegation_result_bridge = ProviderDelegationResultBridge(
            delegation_repository=self.db_service.provider_target_delegation_repository,
            agent_task_service=self.db_service.agent_task_service,
            routing_service=self.routing_service,
            workflow_coordinator=self.workflow_coordinator,
            delegated_agent_repository=self.delegated_agent_repository,
            delegated_agent_controller=self.delegated_agent_controller,
        )
        self.routing_service.set_provider_delegation_result_bridge(
            self.provider_delegation_result_bridge
        )
        self.provider_run_service = AgentTaskProviderRunService(
            provider_profile_repository=self.db_service.provider_profile_repository,
            provider_run_repository=self.db_service.provider_run_repository,
            provider_interaction_repository=self.db_service.provider_interaction_repository,
            routing_service=self.routing_service,
            delegated_agent_repository=self.delegated_agent_repository,
            acp_session_controller=self.acp_delegated_session_controller,
            delegated_agent_controller=self.delegated_agent_controller,
            evidence_capture_service=self.delegated_agent_evidence_capture_service,
            logger=self.logger,
        )
        self.processing_service = AgentTaskProcessingService(
            db_service=self.db_service,
            cancellation_registry=self._cancellation,
            routing_service=self.routing_service,
            workflow_result_service=self.workflow_result_service,
            provider_run_service=self.provider_run_service,
            logger=self.logger,
        )
        self.submission_service = AgentTaskSubmissionService(
            db_service=self.db_service,
            screen_context_service=self.screen_context_service,
            routing_service=self.routing_service,
            processing_service=self.processing_service,
            is_canceled=self.is_agent_task_canceled,
            logger=self.logger,
        )
        self.authorized_provider_delegation_submission_service = (
            AuthorizedProviderDelegationSubmissionService(
                self.submission_service,
                delegated_agent_controller=self.delegated_agent_controller,
            )
        )

        self.event_handlers = AgentTaskEventHandlers(
            db_service=self.db_service,
            model_service=llm_service,
            operation_router=self.routing_service,
            websocket_manager=websocket_manager,
        )
        self.event_handlers.register_handlers(self.state_machine)
        self._register_real_handlers()
        self.db_service.register_agent_task_callback(self._handle_database_event)
        self.logger.info("AgentTask Orchestrator initialized with event-driven architecture")

    def _register_real_handlers(self) -> None:
        """Replace mock handlers with real implementations that use focused services."""
        self.event_handlers._perform_routing = self.routing_service.perform_routing
        self.event_handlers._perform_clarification_routing = self.processing_service.perform_clarification_routing
        self.event_handlers._perform_processing = self.processing_service.perform_processing
        self.logger.info("Registered real implementation handlers")
        self.workflow_result_service.agent_task_submission_service = (
            self.authorized_provider_delegation_submission_service
        )
        self.workflow_coordinator._agent_task_submission_service = (
            self.authorized_provider_delegation_submission_service
        )

    def request_agent_task_preemption(self, agent_task_id: str) -> bool:
        """Set the cancellation signal and schedule runtime preemption without awaiting I/O."""
        agent_task_id = (agent_task_id or "").strip()
        if not agent_task_id:
            self.logger.warning("🛑 Ignoring cancel request with empty agent_task_id")
            return False

        request_received_at = time.perf_counter()
        self._cancellation.mark_canceled({agent_task_id})
        signal_set_at = time.perf_counter()
        task_cancel_scheduled = self._cancellation.cancel_active_task(agent_task_id)
        task_cancel_scheduled_at = time.perf_counter()
        self._processing_agent_tasks.discard(agent_task_id)
        self._release_lifecycle_for_canceled_task(agent_task_id)
        self.logger.info(
            "🛑 Cancellation preemption task=%s request_received=%.6f signal_set=%.6f "
            "task_cancel_scheduled=%.6f active_task_found=%s",
            agent_task_id,
            request_received_at,
            signal_set_at,
            task_cancel_scheduled_at,
            task_cancel_scheduled,
        )
        return task_cancel_scheduled

    async def cancel_agent_task(self, agent_task_id: str) -> bool:
        """Cancel a specific agent-task thread's processing."""
        agent_task_id = (agent_task_id or "").strip()
        if not agent_task_id:
            self.logger.warning("🛑 Ignoring cancel request with empty agent_task_id")
            return False

        self.request_agent_task_preemption(agent_task_id)
        cancellation_ids = {agent_task_id}
        cancellation_broadcast_ids = {agent_task_id}
        root_task_id = agent_task_id

        try:
            agent_task_record = await self.db_service.get_agent_task(agent_task_id)
            if agent_task_record:
                root_task_id = agent_task_record.root_task_id or agent_task_record.id

            chain = await self.db_service.get_agent_task_chain(root_task_id)
            if chain:
                cancellation_ids = {c.id for c in chain}
                cancellation_ids.add(root_task_id)
                active_statuses = {
                    "capturing",
                    "routing",
                    "processing",
                    "awaiting_user_input",
                    "awaiting_provider_delegation",
                    "awaiting_delegated_agents",
                    "paused",
                    "canceled",
                }
                cancellation_broadcast_ids = {
                    c.id for c in chain if c.status in active_statuses
                }
        except Exception as exc:
            self.logger.warning("🛑 Failed to expand cancellation thread for %s: %s", agent_task_id, exc)

        try:
            active_delegated_runs = []
            if self.delegated_agent_repository is not None:
                active_delegated_runs = (
                    await self.delegated_agent_repository.list_active_for_parent(agent_task_id)
                )
            generic_child_ids = {
                str(run["child_agent_task_id"]) for run in active_delegated_runs
            }
            delegated_child_id = await self.provider_delegation_result_bridge.request_parent_cancellation(
                agent_task_id
            )
            for delegated_run in active_delegated_runs:
                if delegated_run["executor_kind"] == "acp_provider":
                    await self.acp_delegated_session_controller.cancel(
                        delegated_agent_run_id=str(delegated_run["id"])
                    )
            if delegated_child_id or generic_child_ids:
                if delegated_child_id:
                    cancellation_ids.add(delegated_child_id)
                cancellation_broadcast_ids.add(agent_task_id)
            cancellation_ids.update(generic_child_ids)
        except Exception as exc:
            self.logger.warning("🛑 Failed to fence delegated provider cancellation for %s: %s", agent_task_id, exc)

        self._cancellation.mark_canceled(cancellation_ids)
        for canceled_id in cancellation_ids:
            self._processing_agent_tasks.discard(canceled_id)
            self._cancellation.cancel_active_task(canceled_id)
            self._release_lifecycle_for_canceled_task(canceled_id)

        if self.websocket_manager:
            for canceled_id in cancellation_broadcast_ids:
                if not self._cancellation.claim_terminal_notification(canceled_id):
                    continue
                try:
                    await self.websocket_manager.broadcast({
                        "event_type": "agent_task_canceled",
                        "agent_task_id": canceled_id,
                        "root_task_id": root_task_id,
                        "message": "AgentTask canceled",
                    })
                except Exception as exc:
                    self._cancellation.release_terminal_notification(canceled_id)
                    self.logger.warning(
                        "Failed to broadcast cancel notification for %s: %s",
                        canceled_id,
                        exc,
                    )

        self.logger.info(
            "🛑 AgentTask thread marked for cancellation: root=%s, count=%s",
            root_task_id,
            len(cancellation_ids),
        )
        return True

    def is_agent_task_canceled(self, agent_task_id: str) -> bool:
        """Check if an agent task has been canceled."""
        return self._cancellation.is_canceled(agent_task_id)

    def _get_cancellation_event(self, agent_task_id: str) -> asyncio.Event:
        """Return the cooperative cancellation signal for an agent task."""
        return self._cancellation.get_cancellation_event(agent_task_id)

    def _release_lifecycle_for_canceled_task(self, agent_task_id: str) -> None:
        """Release the wake lifecycle gate immediately when a task is canceled."""
        if not agent_task_id:
            return
        try:
            from api.main import app

            wake_word_service = getattr(app.state, "wake_word_service", None)
            orchestration = (
                getattr(wake_word_service, "agent_task_orchestration_service", None)
                if wake_word_service is not None
                else None
            )
            if orchestration is not None and hasattr(orchestration, "release_lifecycle"):
                orchestration.release_lifecycle(f"task:{agent_task_id}", "user_canceled")
        except Exception as release_err:
            self.logger.debug("Lifecycle release on cancel skipped for %s: %s", agent_task_id, release_err)

    async def process_agent_task(
        self,
        agent_task: str,
        display_prompt_markdown: Optional[str] = None,
        pre_captured_screenshot: Dict[str, Any] = None,
        agent_task_id: str = None,
        synchronous: bool = False,
        chain_context: Dict[str, Any] = None,
        reference_paths: Optional[List[str]] = None,
        model_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        provider_target: Optional[Dict[str, Any]] = None,
        origin_type: Optional[str] = None,
        origin_id: Optional[str] = None,
        todo_workspace_context: Optional[Dict[str, Any]] = None,
        todo_worker_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Process a new AgentTask using the submission service."""
        return await self.submission_service.process_agent_task(
            agent_task=agent_task,
            display_prompt_markdown=display_prompt_markdown,
            pre_captured_screenshot=pre_captured_screenshot,
            agent_task_id=agent_task_id,
            synchronous=synchronous,
            chain_context=chain_context,
            reference_paths=reference_paths,
            model_id=model_id,
            conversation_id=conversation_id,
            provider_target=provider_target,
            origin_type=origin_type,
            origin_id=origin_id,
            todo_workspace_context=todo_workspace_context,
            todo_worker_context=todo_worker_context,
        )

    async def add_clarification(self, agent_task_id: str, clarification_text: str) -> Dict[str, Any]:
        """Add clarification to an existing AgentTask."""
        return await self.submission_service.add_clarification(agent_task_id, clarification_text)

    async def _handle_database_event(self, event: AgentTaskEvent) -> None:
        """Handle database events by triggering appropriate state machine transitions."""
        updated_at = (event.agent_task_data or {}).get("updated_at")
        event_key = (
            f"{event.agent_task_id}:{event.event_type}:"
            f"{event.old_status}->{event.new_status}:{updated_at}:"
            f"{len(event.new_clarifications or [])}"
        )
        if event_key in self._processed_events:
            return

        self._processed_events.add(event_key)
        self.provider_delegation_result_bridge.handle_agent_task_event(event)
        if len(self._processed_events) > 1000:
            old_events = list(self._processed_events)[:500]
            for old_event in old_events:
                self._processed_events.discard(old_event)

        if self.is_agent_task_canceled(event.agent_task_id):
            self.logger.info(
                "🛑 Ignoring database event for canceled agent_task %s: %s",
                event.agent_task_id,
                event.event_type,
            )
            return

        self.logger.debug(
            "Handling database event: %s for agent_task %s",
            event.event_type,
            event.agent_task_id,
        )

        try:
            handled = self.state_machine.handle_event(event)
            if event.event_type == "status_changed":
                new_status = event.new_status
                if new_status in {"completed", "failed", "canceled"}:
                    self._processing_agent_tasks.discard(event.agent_task_id)
                    self._release_lifecycle_for_canceled_task(event.agent_task_id)
                elif new_status in {"routing", "processing", "clarification_added"}:
                    self._processing_agent_tasks.add(event.agent_task_id)
            return handled

        except Exception as exc:
            self.logger.error("Error handling database event: %s", exc, exc_info=True)

    def get_status(self) -> Dict[str, Any]:
        """Get orchestrator status information."""
        return {
            "orchestrator_active": True,
            "state_machine_states": len(AgentTaskStatus),
            "registered_handlers": len(self.state_machine._state_handlers),
            "database_connected": self.db_service is not None,
            "screen_context_service_available": self.screen_context_service is not None,
        }

    async def get_agent_task_status(self, agent_task_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific agent task."""
        agent_task_record = await self.db_service.get_agent_task(agent_task_id)
        if not agent_task_record:
            return None

        return {
            "agent_task_id": agent_task_id,
            "status": agent_task_record.status,
            "transcribed_prompt": agent_task_record.transcribed_prompt,
            "app_name": agent_task_record.app_name,
            "created_at": agent_task_record.timestamp.isoformat(),
            "updated_at": agent_task_record.updated_at.isoformat() if agent_task_record.updated_at else None,
            "operation_parameters": agent_task_record.operation_parameters,
            "result_data": agent_task_record.result_data,
            "clarifications": agent_task_record.clarifications,
        }

    # Compatibility wrappers for existing tests and internal callers.
    async def _perform_routing(self, agent_task_id: str) -> None:
        await self.routing_service.perform_routing(agent_task_id)

    def _build_routing_request(self, agent_task_record: Any):
        return self.routing_service.build_routing_request(agent_task_record)

    async def _persist_progress_update(self, agent_task_id: str, step: str, status: str, details: str = None) -> None:
        await self.routing_service.persist_progress_update(agent_task_id, step, status, details)

    async def _send_progress_update(
        self,
        step: str,
        status: str,
        details: str = None,
        agent_task_id: str = None,
        root_task_id: str = None,
        previous_task_id: str = None,
    ) -> None:
        await self.routing_service.send_progress_update(
            step,
            status,
            details,
            agent_task_id,
            root_task_id=root_task_id,
            previous_task_id=previous_task_id,
        )

    async def _generate_agent_task_title(self, agent_task_id: str, agent_task: str) -> None:
        await self.routing_service.generate_agent_task_title(agent_task_id, agent_task)

    async def _perform_processing(self, agent_task_id: str) -> None:
        patched_executor = self.__dict__.get("_execute_multi_step_workflow")
        if patched_executor is not None:
            self.processing_service.workflow_result_service.execute_multi_step_workflow = patched_executor
        await self.processing_service.perform_processing(agent_task_id)

    async def _perform_clarification_routing(self, agent_task_id: str) -> None:
        await self.processing_service.perform_clarification_routing(agent_task_id)

    async def _execute_multi_step_workflow(self, parameters: Dict[str, Any], request: Any):
        return await self._workflow_result_helpers().execute_multi_step_workflow(parameters, request)

    def _sanitize_for_json(self, obj: Any) -> Any:
        return self._workflow_result_helpers().sanitize_for_json(obj)

    def _merge_result_data(self, existing_data: Dict[str, Any], new_data: Dict[str, Any]) -> Dict[str, Any]:
        return self._workflow_result_helpers().merge_result_data(existing_data, new_data)

    def _has_successful_finalizer_result(self, result_data: Dict[str, Any]) -> bool:
        return self._workflow_result_helpers().has_successful_finalizer_result(result_data)

    def _derive_failure_error_message(self, operation_result: Any) -> str:
        return self._workflow_result_helpers().derive_failure_error_message(operation_result)

    async def _send_result_message(
        self,
        success: bool,
        result: str = None,
        error: str = None,
        operation: str = None,
        agent_task_id: str = None,
        payload: Any = None,
        root_task_id: str = None,
        previous_task_id: str = None,
    ) -> None:
        await self.workflow_result_service.send_result_message(
            success,
            result,
            error,
            operation,
            agent_task_id,
            payload,
            root_task_id,
            previous_task_id,
        )

    async def _broadcast_agent_task_message(self, agent_task_id: Optional[str], message: Dict[str, Any]) -> bool:
        if agent_task_id and self.is_agent_task_canceled(agent_task_id):
            self.logger.info(
                "🛑 Suppressing %s for canceled agent_task %s",
                message.get("event_type"),
                agent_task_id,
            )
            return False
        if not self.websocket_manager:
            return False
        await self.websocket_manager.broadcast(message)
        return True

    async def _capture_screen_context(self, pre_captured_screenshot: Dict[str, Any] = None) -> Dict[str, Any]:
        return await self.submission_service.capture_screen_context(pre_captured_screenshot)

    def _workflow_result_helpers(self) -> AgentTaskWorkflowResultService:
        service = getattr(self, "workflow_result_service", None)
        if service is not None:
            return service
        return AgentTaskWorkflowResultService(db_service=getattr(self, "db_service", None))


__all__ = ["AgentTaskOrchestrator"]
