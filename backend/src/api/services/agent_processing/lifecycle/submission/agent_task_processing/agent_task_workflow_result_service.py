"""Workflow execution and result handling for AgentTask processing."""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional

from ...runtime.workflow_coordinator import WorkflowCoordinator
from ....shared.serialization import convert_to_serializable_dict


class AgentTaskWorkflowResultService:
    """Runs the canonical workflow and normalizes/broadcasts its result."""

    def __init__(
        self,
        *,
        db_service: Any,
        websocket_manager: Any = None,
        agent_task_submission_service: Any = None,
        basil_services: Optional[Dict[str, Any]] = None,
        is_cancelled: Optional[Callable[[str], bool]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.db_service = db_service
        self.websocket_manager = websocket_manager
        self.agent_task_submission_service = agent_task_submission_service
        self.basil_services = basil_services or {}
        self._is_cancelled = is_cancelled or (lambda _agent_task_id: False)
        self.logger = logger or logging.getLogger(__name__)

    def sanitize_for_json(self, obj: Any) -> Any:
        """Recursively convert workflow payloads to JSON-serializable structures."""
        return convert_to_serializable_dict(obj)

    async def execute_multi_step_workflow(self, parameters: Dict[str, Any], request: Any):
        """Run the canonical agent workflow without the legacy operation-router adapter."""
        try:
            chain_context = None
            root_task_id = getattr(request, "root_task_id", None)
            previous_task_id = getattr(request, "previous_task_id", None)
            retry_context = getattr(request, "retry_context", None)
            todo_worker_context = getattr(request, "todo_worker_context", None)

            if getattr(request, "agent_task_id", None):
                try:
                    agent_task_record = await self.db_service.get_agent_task(request.agent_task_id)
                    if agent_task_record:
                        artifacts = agent_task_record.accumulated_artifacts
                        if isinstance(artifacts, dict):
                            if "todo_worker_context" in artifacts:
                                todo_worker_context = artifacts["todo_worker_context"]
                            chain_context = artifacts
                            self.logger.info(
                                "🔗 Retrieved chain context for agent task %s: %s keys",
                                request.agent_task_id,
                                len(artifacts),
                            )
                        root_task_id = getattr(agent_task_record, "root_task_id", None) or root_task_id
                        previous_task_id = getattr(agent_task_record, "previous_task_id", None)
                        if not retry_context and agent_task_record.result_data and isinstance(agent_task_record.result_data, dict):
                            retry_context = agent_task_record.result_data.get("retry_context")
                except Exception as exc:
                    self.logger.warning("⚠️ Failed to retrieve chain context: %s", exc)

            clarification_agent_task = getattr(request, "clarification_agent_task", None)
            if clarification_agent_task:
                combined_agent_task = f"{request.agent_task}. {clarification_agent_task}"
                self.logger.info("🔗 Combined agent task with clarification: %r", combined_agent_task)
            else:
                combined_agent_task = request.agent_task

            workflow_context = {
                "active_app": request.active_app,
                "screen_text": request.full_screen_text or request.screen_text,
                "clarification_agent_task": clarification_agent_task,
                "available_services": self.basil_services,
                "routing_parameters": parameters or {},
                "websocket_manager": self.websocket_manager,
                "chain_context": chain_context,
                "retry_context": retry_context,
                "agent_task_id": getattr(request, "agent_task_id", None),
                "root_task_id": root_task_id,
                "previous_task_id": previous_task_id,
                "user_agent_task": combined_agent_task,
                "reference_paths": getattr(request, "reference_paths", None),
                "model_id": getattr(request, "model_id", None),
                "conversation_id": getattr(request, "conversation_id", None),
                "todo_worker_context": todo_worker_context,
                "cancel_event": getattr(request, "cancel_event", None),
            }
            try:
                from ...runtime.agent_work_ledger_service import AgentWorkLedgerService

                ledger = AgentWorkLedgerService(self.db_service)
                await ledger.ensure_session(
                    context=workflow_context,
                    goal=combined_agent_task,
                    collection_type="agent_work",
                )
                workflow_context["work_ledger_handoff"] = await ledger.handoff(
                    context=workflow_context,
                )
            except Exception as ledger_error:
                self.logger.warning(
                    "Could not initialize work ledger for task %s: %s",
                    getattr(request, "agent_task_id", None),
                    ledger_error,
                )

            self.logger.info("🎯 Direct workflow execution in caller event loop")
            coordinator = WorkflowCoordinator(
                websocket_manager=self.websocket_manager,
                agent_task_submission_service=self.agent_task_submission_service,
            )
            workflow_result = await coordinator._execute_with_tools(
                combined_agent_task,
                workflow_context,
                request.agent_task_id,
            )

            cancel_event = getattr(request, "cancel_event", None)
            if cancel_event is not None and cancel_event.is_set():
                raise asyncio.CancelledError()

            return await self.finalize_workflow_output(workflow_result, request)
        except asyncio.CancelledError:
            self.logger.info(
                "🛑 Enhanced multi-step workflow cancelled for %s",
                getattr(request, "agent_task_id", None),
            )
            raise
        except Exception as exc:
            self.logger.error("Enhanced multi-step workflow execution failed: %s", exc, exc_info=True)
            return SimpleNamespace(
                operation="multi_step_workflow",
                success=False,
                data=None,
                user_feedback=f"Workflow execution failed: {exc}",
                error_message=str(exc),
                widget_content_delivered=False,
            )

    async def finalize_workflow_output(self, workflow_result: Any, request: Any):
        """Normalize workflow output, broadcast the final envelope once, and return the terminal operation_result.

        Shared by the initial run rail (``execute_multi_step_workflow``) and the
        checkpoint-resume rail so both converge on identical result-data shape and a
        single ``agent_task_result`` broadcast.
        """
        result_data = self.build_workflow_result_data(workflow_result, request)
        await self.broadcast_final_envelope_if_present(result_data, request)

        needs_user_input = bool(result_data.get("needs_user_input"))
        needs_provider_delegation = bool(result_data.get("needs_provider_delegation"))
        workflow_success = bool(result_data.get("success", True))
        workflow_error = None

        if not needs_user_input and not needs_provider_delegation:
            final_envelope = result_data.get("final_envelope")
            if not isinstance(final_envelope, dict):
                workflow_success = False
                workflow_error = self.extract_workflow_error(result_data) or (
                    "Workflow failed - the agent did not properly finalize its work."
                )
                self.logger.error("🧪 Workflow missing finalizer envelope - marking as failed")
            elif final_envelope.get("success") is True:
                workflow_success = True
                workflow_error = None
            elif final_envelope.get("success") is False:
                workflow_success = False
                workflow_error = final_envelope.get("summary_text", "Operation failed")

        return SimpleNamespace(
            operation="multi_step_workflow",
            success=workflow_success,
            data=result_data,
            user_feedback=result_data.get("workflow_result") if workflow_success else workflow_error,
            error_message=workflow_error,
            widget_content_delivered=bool(result_data.get("finalizer_broadcasted")),
        )

    def build_workflow_result_data(self, workflow_result: Any, request: Any) -> Dict[str, Any]:
        """Normalize WorkflowCoordinator output into the result shape the task lifecycle stores."""
        from ...finalization.task_state_persistence import normalize_thinking_history

        if isinstance(workflow_result, dict):
            execution_results = workflow_result.get("tool_execution_results") or workflow_result.get("execution_results", [])
            details = {
                "total_todos": workflow_result.get("total_todos", 0),
                "todos_completed": workflow_result.get("todos_completed", 0),
                "execution_time": workflow_result.get("execution_time", 0),
                "results": execution_results,
            }
            final_envelope = workflow_result.get("final_envelope")
            success = workflow_result.get("overall_success", workflow_result.get("success", True))
            summary = workflow_result.get("summary") or workflow_result.get("workflow_result") or "Workflow completed"
            reasoning_fallback_model_used = workflow_result.get("reasoning_fallback_model_used")
            thinking_history = workflow_result.get("thinking_history")
        else:
            execution_results = getattr(workflow_result, "execution_results", [])
            details = {
                "total_todos": getattr(workflow_result, "total_todos", 0),
                "todos_completed": getattr(workflow_result, "todos_completed", 0),
                "execution_time": getattr(workflow_result, "execution_time", 0),
                "results": execution_results if execution_results is not None else getattr(workflow_result, "results", []),
            }
            final_envelope = getattr(workflow_result, "final_envelope", None)
            success = getattr(workflow_result, "overall_success", getattr(workflow_result, "success", True))
            summary = getattr(workflow_result, "summary", None) or "Enhanced workflow completed successfully"
            reasoning_fallback_model_used = getattr(workflow_result, "reasoning_fallback_model_used", None)
            thinking_history = getattr(workflow_result, "thinking_history", None)

        result_data = {
            "success": success,
            "workflow_result": summary,
            "message": f"Enhanced workflow processed: {request.agent_task}",
            "todos_completed": details["todos_completed"],
            "workflow_details": details,
        }
        if reasoning_fallback_model_used:
            result_data["reasoning_fallback_model_used"] = reasoning_fallback_model_used
        if thinking_history:
            result_data["thinking_history"] = normalize_thinking_history(thinking_history)

        for execution_result in execution_results or []:
            if not isinstance(execution_result, dict):
                continue
            if execution_result.get("needs_user_input"):
                result_data["needs_user_input"] = True
                self.logger.info("🤝 Propagating needs_user_input flag from workflow execution results")
                break
            if execution_result.get("needs_provider_delegation"):
                result_data["needs_provider_delegation"] = True
                result_data["provider_delegation"] = {
                    "delegation_id": execution_result["delegation_id"],
                    "child_agent_task_id": execution_result["child_agent_task_id"],
                    "status": "awaiting_child",
                }
                self.logger.info("🔗 Preserving delegated-provider wait without terminal finalization")
                break

        if isinstance(final_envelope, dict):
            result_data["final_envelope"] = final_envelope
            result_data["result_payload"] = final_envelope.get("result_payload")

        return result_data

    async def broadcast_final_envelope_if_present(self, result_data: Dict[str, Any], request: Any) -> None:
        """Broadcast finalized workflow output once, then mark it as delivered for the lifecycle layer."""
        if (
            not self.websocket_manager
            or result_data.get("needs_user_input")
            or result_data.get("needs_provider_delegation")
        ):
            return

        final_envelope = result_data.get("final_envelope")
        if not isinstance(final_envelope, dict):
            return

        payload = final_envelope.get("result_payload") or {}
        env_success = final_envelope.get("success")
        if env_success is None:
            env_success = bool(result_data.get("success", True))

        await self.send_result_message(
            success=bool(env_success),
            result=final_envelope.get("summary_text", ""),
            error=None if env_success else final_envelope.get("outcome_reason"),
            operation="multi_step_workflow",
            agent_task_id=getattr(request, "agent_task_id", None),
            payload=payload,
            root_task_id=getattr(request, "root_task_id", None),
            previous_task_id=getattr(request, "previous_task_id", None),
        )
        result_data["finalizer_broadcasted"] = True
        result_data["broadcast_payload"] = payload

    def extract_workflow_error(self, result_data: Dict[str, Any]) -> Optional[str]:
        """Pull a specific failure from workflow execution data when the agent never finalized."""
        try:
            workflow_details = result_data.get("workflow_details") or {}
            tool_results = workflow_details.get("results") or []
            if tool_results and isinstance(tool_results[0], dict):
                error = tool_results[0].get("error") or tool_results[0].get("error_message")
                if error:
                    return str(error)
        except Exception:
            pass
        return None

    async def send_result_message(
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
        """Send WebSocket result message to frontend in expected format."""
        self.logger.info(
            "🔥 _send_result_message called: success=%s, result_length=%s, operation=%s, agent_task_id=%s",
            success,
            len(result or ""),
            operation,
            agent_task_id,
        )

        if not self.websocket_manager:
            self.logger.error("🚨 NO WEBSOCKET MANAGER - Cannot send result message!")
            return

        try:
            message_data = {
                "event_type": "agent_task_result",
                "success": success,
                "result": result or "",
                "error": error,
                "operation": operation,
            }

            if agent_task_id:
                message_data["agent_task_id"] = agent_task_id
            if payload is not None:
                message_data["result_payload"] = payload
            if root_task_id:
                message_data["root_task_id"] = root_task_id
            if previous_task_id:
                message_data["previous_task_id"] = previous_task_id

            self.logger.info("🔥 About to broadcast agent_task_result: %s", message_data)
            sent = await self.broadcast_agent_task_message(agent_task_id, message_data)
            if sent:
                self.logger.info("🔥 Successfully broadcasted agent_task_result to frontend")

        except Exception as exc:
            self.logger.error("🚨 Failed to send result message: %s", exc, exc_info=True)

    async def broadcast_agent_task_message(self, agent_task_id: Optional[str], message: Dict[str, Any]) -> bool:
        """Broadcast unless this task has already been cancelled."""
        if agent_task_id and self._is_cancelled(agent_task_id):
            self.logger.info(
                "🛑 Suppressing %s for cancelled agent_task %s",
                message.get("event_type"),
                agent_task_id,
            )
            return False
        if not self.websocket_manager:
            return False
        await self.websocket_manager.broadcast(message)
        return True

    def merge_result_data(self, existing_data: Dict[str, Any], new_data: Dict[str, Any]) -> Dict[str, Any]:
        """Merge workflow result details without discarding earlier persisted context."""
        if not isinstance(existing_data, dict):
            existing_data = {}
        if not isinstance(new_data, dict):
            return existing_data

        merged = dict(existing_data)
        for key, value in new_data.items():
            if value is None:
                continue
            if key == "data" and isinstance(value, dict) and isinstance(merged.get("data"), dict):
                nested = dict(merged["data"])
                nested.update(value)
                merged["data"] = nested
            else:
                merged[key] = value
        return merged

    def has_successful_finalizer_result(self, result_data: Dict[str, Any]) -> bool:
        """Detect a completed finalizer result that should not be downgraded by later errors."""
        if not isinstance(result_data, dict):
            return False

        for key in ("final_envelope", "finalizer_result"):
            envelope = result_data.get(key)
            if isinstance(envelope, dict) and envelope.get("success") is not False:
                summary = envelope.get("summary_text") or result_data.get("workflow_result") or result_data.get("message")
                if isinstance(summary, str) and summary.strip():
                    return True

        nested_data = result_data.get("data")
        if isinstance(nested_data, dict):
            return self.has_successful_finalizer_result(nested_data)

        return False

    def derive_failure_error_message(self, operation_result: Any) -> str:
        """Prefer specific workflow/finalizer details over a null or generic failure."""
        fallback = "Workflow failed - the agent did not properly finalize its work."
        if not operation_result:
            return "Operation failed"

        error_message = getattr(operation_result, "error_message", None)
        if isinstance(error_message, str) and error_message.strip():
            return error_message.strip()

        data = getattr(operation_result, "data", None)
        if isinstance(data, dict):
            final_envelope = data.get("final_envelope")
            if isinstance(final_envelope, dict):
                for key in ("outcome_reason", "summary_text"):
                    value = final_envelope.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()

            finalizer_result = data.get("finalizer_result")
            if isinstance(finalizer_result, dict):
                value = finalizer_result.get("summary_text")
                if isinstance(value, str) and value.strip():
                    return value.strip()

            for key in ("workflow_result", "message", "error"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

            workflow_error = self.extract_workflow_error(data)
            if workflow_error:
                return workflow_error

        feedback = getattr(operation_result, "user_feedback", None)
        if isinstance(feedback, str) and feedback.strip():
            return feedback.strip()

        return fallback

    async def commit_terminal_outcome(
        self,
        *,
        agent_task_id: str,
        agent_task_record: Any,
        operation: str,
        operation_result: Any,
    ) -> None:
        """Persist the terminal status/result_data and emit the single result message.

        Shared committer for both the initial run rail (``perform_processing``) and the
        checkpoint-resume rail so completed/failed persistence and the ``agent_task_result``
        broadcast are identical regardless of which rail drove the run.
        """
        if operation_result is not None and getattr(operation_result, "success", False):
            await self._commit_success(agent_task_id, agent_task_record, operation, operation_result)
        else:
            await self._commit_failure(agent_task_id, agent_task_record, operation, operation_result)

    async def _commit_success(
        self, agent_task_id: str, agent_task_record: Any, operation: str, operation_result: Any
    ) -> None:
        needs_user_input = False
        if operation_result.data and isinstance(operation_result.data, dict):
            needs_user_input = operation_result.data.get("needs_user_input", False)

        if needs_user_input:
            self.logger.info("🤝 Agent requested user input - skipping status update (already awaiting_user_input)")
            return
        if operation_result.data and isinstance(operation_result.data, dict):
            if operation_result.data.get("needs_provider_delegation"):
                self.logger.info("🔗 Delegated provider child is active - skipping parent terminal persistence")
                return

        safe_data = dict(self.sanitize_for_json(operation_result.data or {}) or {})
        hoisted_thinking_history = safe_data.pop("thinking_history", None)
        completed_result_data = self.sanitize_for_json({
            "success": True,
            "operation_type": operation,
            "data": {
                **(safe_data or {}),
                "widget_content_delivered": getattr(operation_result, "widget_content_delivered", False),
            },
            "message": getattr(operation_result, "user_feedback", "Operation completed successfully"),
        })
        if hoisted_thinking_history:
            completed_result_data["thinking_history"] = hoisted_thinking_history
        changed = await self._update_terminal_status_if_active(
            agent_task_id=agent_task_id,
            status="completed",
            result_data=completed_result_data,
        )
        if not changed:
            self.logger.info("🛑 Cancellation won terminal success race for %s", agent_task_id)
            return

        user_feedback = getattr(operation_result, "user_feedback", "Operation completed successfully")
        widget_content_delivered = getattr(operation_result, "widget_content_delivered", False)
        self.logger.info(
            "🔍 RESULT_MESSAGE_DEBUG: operation=%r, widget_content_delivered=%s",
            operation,
            widget_content_delivered,
        )

        if widget_content_delivered:
            self.logger.info("🔥 Skipping final result message - widget content already delivered for: %s", operation)
        elif operation == "capture_screen":
            self.logger.info("🔥 Skipping final result message for intermediate capture_screen operation: %s", operation)
        elif operation == "multi_step_workflow":
            already_finalized = False
            try:
                data_dict = operation_result.data or {}
                already_finalized = bool(data_dict.get("finalizer_broadcasted") or data_dict.get("final_envelope"))
            except Exception:
                already_finalized = False

            if already_finalized:
                self.logger.info("🔥 Skipping legacy final result send: finalizer-driven result already broadcast by router")
            else:
                self.logger.info("🚫 Skipping legacy fallback: no finalized agent envelope present for multi_step_workflow")
        else:
            self.logger.info("🔥 About to send success result to frontend: %s", user_feedback)
            await self.send_result_message(
                success=True,
                result=user_feedback,
                operation=operation,
                agent_task_id=agent_task_id,
                root_task_id=getattr(agent_task_record, "root_task_id", None),
                previous_task_id=getattr(agent_task_record, "previous_task_id", None),
            )

        self.logger.info("🔥 AgentTask %s execution completed successfully", agent_task_id)

    async def _commit_failure(
        self, agent_task_id: str, agent_task_record: Any, operation: str, operation_result: Any
    ) -> None:
        error_message = self.derive_failure_error_message(operation_result)
        existing_data = await self._load_existing_result_data(agent_task_id)
        if operation_result and isinstance(getattr(operation_result, "data", None), dict):
            existing_data = self.merge_result_data(existing_data, operation_result.data)
        existing_data["failure_info"] = {
            "success": False,
            "error": error_message,
            "operation_type": operation,
        }
        changed = await self._update_terminal_status_if_active(
            agent_task_id=agent_task_id,
            status="failed",
            result_data=self.sanitize_for_json(existing_data),
        )
        if not changed:
            self.logger.info("🛑 Cancellation won terminal failure race for %s", agent_task_id)
            return
        await self.send_result_message(
            success=False,
            error=error_message,
            operation=operation,
            agent_task_id=agent_task_id,
            root_task_id=getattr(agent_task_record, "root_task_id", None),
            previous_task_id=getattr(agent_task_record, "previous_task_id", None),
        )
        self.logger.error("AgentTask %s execution failed: %s", agent_task_id, error_message)

    async def _update_terminal_status_if_active(self, **kwargs: Any) -> bool:
        conditional_update = getattr(
            self.db_service,
            "update_agent_task_status_if_active",
            None,
        )
        if conditional_update is not None:
            return bool(await conditional_update(**kwargs))
        await self.db_service.update_agent_task_status(**kwargs)
        return True

    async def _load_existing_result_data(self, agent_task_id: str) -> Dict[str, Any]:
        try:
            return self._extract_result_data(await self.db_service.get_agent_task(agent_task_id))
        except Exception:
            return {}

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


__all__ = ["AgentTaskWorkflowResultService"]
