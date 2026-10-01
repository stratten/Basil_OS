"""Processing-stage execution for AgentTask lifecycle."""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any, Dict, Optional


class AgentTaskProcessingService:
    """Executes routed AgentTasks and persists terminal outcomes."""

    def __init__(
        self,
        *,
        db_service: Any,
        cancellation_registry: Any,
        routing_service: Any,
        workflow_result_service: Any,
        provider_run_service: Optional[Any] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.db_service = db_service
        self._cancellation = cancellation_registry
        self.routing_service = routing_service
        self.workflow_result_service = workflow_result_service
        self.provider_run_service = provider_run_service
        self.logger = logger or logging.getLogger(__name__)

    async def perform_processing(self, agent_task_id: str) -> None:
        """Execute the operation determined during routing."""
        active_task = asyncio.current_task()
        self._cancellation.register_active_task(agent_task_id, active_task)
        operation_result = None
        operation = None
        try:
            if self._cancellation.is_canceled(agent_task_id):
                self.logger.info("🛑 Skipping processing for canceled agent_task: %s", agent_task_id)
                return

            agent_task_record = await self.db_service.get_agent_task(agent_task_id)
            if not agent_task_record:
                self.logger.error("AgentTask %s not found for processing", agent_task_id)
                return

            root_task_id = getattr(agent_task_record, "root_task_id", None)
            if root_task_id and hasattr(self._cancellation, "register_alias"):
                self._cancellation.register_alias(root_task_id, agent_task_id)
            if self._cancellation.is_canceled(agent_task_id):
                self.logger.info("🛑 Processing canceled after task lookup: %s", agent_task_id)
                return

            operation_params = agent_task_record.operation_parameters or {}
            operation = operation_params.get("operation")
            if not operation:
                self.logger.error("No operation found in agent_task %s parameters", agent_task_id)
                await self.db_service.update_agent_task_status(
                    agent_task_id=agent_task_id,
                    status="failed",
                    result_data={"error": "No operation specified"},
                )
                return

            self.logger.info("Executing operation %s for agent_task %s", operation, agent_task_id)
            await self.routing_service.send_progress_update(
                "Processing request",
                "started",
                agent_task_id=agent_task_id,
                root_task_id=getattr(agent_task_record, "root_task_id", None),
                previous_task_id=getattr(agent_task_record, "previous_task_id", None),
            )

            parameters = operation_params.get("parameters", {})
            if operation == "multi_step_workflow":
                request = self.routing_service.build_routing_request(agent_task_record)
                request.cancel_event = self._cancellation.get_cancellation_event(agent_task_id)
                self.logger.info("🔥 About to execute operation %s for agent_task %s", operation, agent_task_id)
                operation_result = await self.workflow_result_service.execute_multi_step_workflow(
                    parameters,
                    request,
                )
            elif operation == "provider_run":
                if self.provider_run_service is None:
                    raise ValueError("provider_run operation requested but no provider_run_service is configured")
                provider_target = parameters.get("provider_target") or {}
                self.logger.info("🔥 About to execute operation %s for agent_task %s", operation, agent_task_id)
                operation_result = await self.provider_run_service.run_provider_task(
                    agent_task_id=agent_task_id,
                    agent_task_record=agent_task_record,
                    provider_target=provider_target,
                )
            else:
                raise ValueError(f"Unsupported agent-task operation: {operation}")
            if self._cancellation.is_canceled(agent_task_id):
                self.logger.info(
                    "🛑 AgentTask %s canceled during workflow execution; skipping final persistence",
                    agent_task_id,
                )
                return
            self.logger.info(
                "🔥 Operation execution completed. Result: success=%s, has_data=%s",
                operation_result.success if operation_result else None,
                bool(operation_result.data if operation_result else False),
            )

            if (
                operation_result
                and isinstance(operation_result.data, dict)
                and operation_result.data.get("awaiting_delegated_supervision") is True
            ):
                await self.db_service.update_agent_task_status(
                    agent_task_id=agent_task_id,
                    status="awaiting_delegated_agents",
                    result_data=self.workflow_result_service.sanitize_for_json(
                        operation_result.data
                    ),
                )
                return
            if operation_result and operation_result.success:
                await self._persist_success(agent_task_id, agent_task_record, operation, operation_result)
            else:
                await self._persist_failure(agent_task_id, agent_task_record, operation, operation_result)

        except asyncio.CancelledError:
            self.logger.info("🛑 Processing coroutine canceled for agent_task %s", agent_task_id)
            return
        except Exception as exc:
            await self._handle_processing_exception(agent_task_id, exc, operation_result, operation)
        finally:
            self._cancellation.deregister_active_task(agent_task_id, active_task)

    async def perform_clarification_routing(self, agent_task_id: str) -> None:
        """Execute a follow-up after clarification text has been added."""
        active_task = asyncio.current_task()
        self._cancellation.register_active_task(agent_task_id, active_task)
        try:
            if self._cancellation.is_canceled(agent_task_id):
                self.logger.info(
                    "🛑 Skipping clarification routing for canceled agent_task: %s",
                    agent_task_id,
                )
                return

            agent_task_record = await self.db_service.get_agent_task(agent_task_id)
            if not agent_task_record:
                self.logger.error("AgentTask %s not found for clarification routing", agent_task_id)
                return

            root_task_id = getattr(agent_task_record, "root_task_id", None)
            if root_task_id and hasattr(self._cancellation, "register_alias"):
                self._cancellation.register_alias(root_task_id, agent_task_id)
            if self._cancellation.is_canceled(agent_task_id):
                self.logger.info("🛑 Clarification canceled after task lookup: %s", agent_task_id)
                return

            clarifications = agent_task_record.clarifications
            if not clarifications:
                self.logger.error("No clarifications found for agent_task %s", agent_task_id)
                return

            latest_clarification = clarifications[-1]
            clarification_text = latest_clarification.get("text", "")
            self.logger.info("Re-routing with clarification: %s", clarification_text)

            artifacts = agent_task_record.accumulated_artifacts or {}
            request = SimpleNamespace(
                agent_task=agent_task_record.transcribed_prompt,
                active_app=agent_task_record.app_name or "Unknown",
                screen_text=agent_task_record.screen_text or "",
                clarification_agent_task=clarification_text,
                root_task_id=agent_task_record.root_task_id,
                previous_task_id=agent_task_record.previous_task_id,
                reference_paths=artifacts.get("reference_paths") if isinstance(artifacts, dict) else None,
                model_id=artifacts.get("model_id") if isinstance(artifacts, dict) else None,
                conversation_id=artifacts.get("conversation_id") if isinstance(artifacts, dict) else None,
                todo_worker_context=(
                    artifacts.get("todo_worker_context")
                    if isinstance(artifacts, dict)
                    else None
                ),
                retry_context=(
                    agent_task_record.result_data.get("retry_context")
                    if isinstance(agent_task_record.result_data, dict)
                    else None
                ),
            )
            request.full_screen_text = agent_task_record.screen_text or ""
            request.agent_task_id = agent_task_id
            request.cancel_event = self._cancellation.get_cancellation_event(agent_task_id)

            operation = "multi_step_workflow"
            # Clarification submission keeps the original task row. Mark it
            # processing before execution so backend hydration cannot restore its
            # prior awaiting_user_input state while the follow-up is streaming.
            await self.db_service.update_agent_task_status(
                agent_task_id=agent_task_id,
                status="processing",
            )
            parameters = {
                "workflow_type": "general",
                "action": "dynamic_execution",
                "clarification": clarification_text,
            }
            operation_result = await self.workflow_result_service.execute_multi_step_workflow(
                parameters,
                request,
            )
            if self._cancellation.is_canceled(agent_task_id):
                self.logger.info(
                    "🛑 Follow-up agent_task %s canceled during workflow execution; skipping final persistence",
                    agent_task_id,
                )
                return

            if operation_result and operation_result.success:
                if operation_result.data and isinstance(operation_result.data, dict) and operation_result.data.get("needs_user_input"):
                    self.logger.info("🤝 Follow-up workflow requested user input - preserving awaiting_user_input status")
                    return

                await self.db_service.update_agent_task_status(
                    agent_task_id=agent_task_id,
                    status="completed",
                    operation_parameters={
                        "operation": operation,
                        "confidence": 1.0,
                        "reasoning": "Direct routing to agent with clarification context",
                        "used_clarification": True,
                        "clarification_text": clarification_text,
                        "parameters": parameters,
                    },
                    result_data={
                        "success": True,
                        "operation_type": operation,
                        "data": self.workflow_result_service.sanitize_for_json(operation_result.data),
                        "message": getattr(operation_result, "user_feedback", "Operation completed successfully"),
                    },
                )
                await self.workflow_result_service.send_result_message(
                    success=True,
                    result=getattr(operation_result, "user_feedback", "Operation completed successfully"),
                    operation=operation,
                    agent_task_id=agent_task_id,
                    root_task_id=getattr(agent_task_record, "root_task_id", None),
                    previous_task_id=getattr(agent_task_record, "previous_task_id", None),
                )
                self.logger.info("🔥 Follow-up agent_task %s execution completed successfully", agent_task_id)
            else:
                error_message = operation_result.error_message if operation_result else "Operation failed"
                await self.db_service.update_agent_task_status(
                    agent_task_id=agent_task_id,
                    status="failed",
                    result_data={
                        "success": False,
                        "error": error_message,
                        "operation_type": operation,
                    },
                )
                await self.workflow_result_service.send_result_message(
                    success=False,
                    error=error_message,
                    operation=operation,
                    agent_task_id=agent_task_id,
                    root_task_id=getattr(agent_task_record, "root_task_id", None),
                    previous_task_id=getattr(agent_task_record, "previous_task_id", None),
                )
                self.logger.error("Follow-up agent_task %s execution failed: %s", agent_task_id, error_message)

        except asyncio.CancelledError:
            self.logger.info("🛑 Clarification routing coroutine canceled for agent_task %s", agent_task_id)
            return
        except Exception as exc:
            self.logger.error("Error in clarification routing for %s: %s", agent_task_id, exc)
            await self.db_service.update_agent_task_status(
                agent_task_id=agent_task_id,
                status="needs_clarification",
                operation_parameters={
                    "clarification_message": "I'm having trouble understanding. Could you try rephrasing?"
                },
            )
        finally:
            self._cancellation.deregister_active_task(agent_task_id, active_task)

    async def _persist_success(self, agent_task_id: str, agent_task_record: Any, operation: str, operation_result: Any) -> None:
        # Delegates to the shared terminal committer so the initial run rail and the
        # checkpoint-resume rail persist/broadcast identically. commit_terminal_outcome
        # branches on operation_result.success internally.
        await self.workflow_result_service.commit_terminal_outcome(
            agent_task_id=agent_task_id,
            agent_task_record=agent_task_record,
            operation=operation,
            operation_result=operation_result,
        )

    async def _persist_failure(self, agent_task_id: str, agent_task_record: Any, operation: str, operation_result: Any) -> None:
        # Delegates to the shared terminal committer (see _persist_success).
        await self.workflow_result_service.commit_terminal_outcome(
            agent_task_id=agent_task_id,
            agent_task_record=agent_task_record,
            operation=operation,
            operation_result=operation_result,
        )

    async def _handle_processing_exception(
        self,
        agent_task_id: str,
        exc: Exception,
        operation_result: Any,
        operation: Optional[str],
    ) -> None:
        self.logger.error("Error processing agent_task %s: %s", agent_task_id, exc, exc_info=True)
        existing_cmd = None
        existing_data = {}
        try:
            existing_cmd = await self.db_service.get_agent_task(agent_task_id)
            existing_data = self._extract_result_data(existing_cmd)
        except Exception:
            existing_data = {}

        if operation_result and isinstance(getattr(operation_result, "data", None), dict):
            existing_data = self.workflow_result_service.merge_result_data(existing_data, operation_result.data)

        if self.workflow_result_service.has_successful_finalizer_result(existing_data):
            existing_data["post_processing_warning"] = str(exc) or "Post-processing persistence warning"
            await self.db_service.update_agent_task_status(
                agent_task_id=agent_task_id,
                status="completed",
                result_data=self.workflow_result_service.sanitize_for_json(existing_data),
            )
            self.logger.warning(
                "Preserved successful agent_task %s despite post-processing error: %s",
                agent_task_id,
                exc,
            )
            return

        existing_data["failure_info"] = {
            "success": False,
            "error": str(exc) or "Workflow execution failed unexpectedly",
            "operation_type": operation or "multi_step_workflow",
        }
        await self.db_service.update_agent_task_status(
            agent_task_id=agent_task_id,
            status="failed",
            result_data=self.workflow_result_service.sanitize_for_json(existing_data),
        )
        await self.workflow_result_service.send_result_message(
            success=False,
            error=str(exc),
            operation=operation,
            agent_task_id=agent_task_id,
            root_task_id=getattr(existing_cmd, "root_task_id", None) if existing_cmd else None,
            previous_task_id=getattr(existing_cmd, "previous_task_id", None) if existing_cmd else None,
        )

    @staticmethod
    def _extract_result_data(agent_task_record: Any) -> Dict[str, Any]:
        if not agent_task_record or not getattr(agent_task_record, "result_data", None):
            return {}
        result_data = agent_task_record.result_data
        if isinstance(result_data, str):
            return json.loads(result_data)
        if isinstance(result_data, dict):
            return result_data
        return {}


__all__ = ["AgentTaskProcessingService"]
