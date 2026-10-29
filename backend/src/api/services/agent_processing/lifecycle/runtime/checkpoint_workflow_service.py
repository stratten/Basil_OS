"""Checkpoint request, resume, and recovery behavior for agent workflows."""

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any, Dict, Optional
from uuid import uuid4

from .resume_cancellation import ResumedRunCanceled, run_registered_resume
from .user_interaction_timeline import (
    checkpoint_interaction_kind,
    record_user_interaction_asked,
    resolve_latest_waiting_user_interaction,
)
from .workflow_results import WorkflowExecutionResult


# Sentinel value passed as `user_response` to resume_workflow when the user dismissed
# the checkpoint widget without answering (closed the agent-task widget or pressed
# Cancel / Skip). The dismiss branch in resume_workflow steers the agent toward
# emitting a final_envelope from already-completed work rather than calling more
# tools or asking another question.
USER_DISMISSED_CHECKPOINT_RESPONSE = "__BASIL_USER_DISMISSED_CHECKPOINT__"


def checkpoint_interaction_status(
    user_response: str,
    provider_target_authorization_resolution: Optional[Mapping[str, object]],
) -> str:
    if user_response == USER_DISMISSED_CHECKPOINT_RESPONSE:
        return "dismissed"
    if provider_target_authorization_resolution:
        return {
            "authorized": "approved",
            "rejected": "denied",
            "canceled": "canceled",
        }.get(str(provider_target_authorization_resolution.get("status")), "answered")
    return "answered"


def _create_provider_target_authorization_service(
    knowledge_service: Any,
) -> Any:
    from api.services.agent_providers.targeting.authorization_service import (
        ProviderTargetAuthorizationService,
    )

    return ProviderTargetAuthorizationService(
        proposal_repository=knowledge_service.provider_discovery_proposal_repository,
        authorization_repository=knowledge_service.provider_target_authorization_repository,
        provider_profile_repository=knowledge_service.provider_profile_repository,
        agent_task_service=knowledge_service.agent_task_service,
    )


class WorkflowCheckpointWorkflowService:
    """Manage workflow checkpoints and resume their persisted LangGraph state."""

    def __init__(self, websocket_manager=None, status_notifier=None):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.websocket_manager = websocket_manager
        self.status_notifier = status_notifier

    def is_checkpoint_request(self, exception: Exception) -> bool:
        """Check if an exception is a checkpoint request from the agent."""
        try:
            from ...tools.internal_basil_tools.checkpoint_tool import CheckpointRequest

            return isinstance(exception, CheckpointRequest)
        except ImportError:
            return False

    async def handle_checkpoint_request(
        self,
        exception: Exception,
        agent_task_id: Optional[str],
        user_agent_task: str,
    ) -> None:
        """Broadcast a requested checkpoint and report its waiting status."""
        try:
            checkpoint_data = exception.checkpoint_data
            prompt = checkpoint_data.get("prompt", "Waiting for your input...")
            self.logger.info(f"🛑 Handling checkpoint request: {prompt}")
            if self.websocket_manager:
                await self.websocket_manager.broadcast({
                    "event_type": "collaborative_checkpoint_request",
                    "agent_task_id": agent_task_id,
                    "checkpoint_data": {
                        "checkpoint_id": checkpoint_data.get("checkpoint_id"),
                        "prompt": prompt,
                        "input_type": checkpoint_data.get("input_type", "text"),
                        "options": checkpoint_data.get("options", []),
                        "allow_multiple": bool(checkpoint_data.get("allow_multiple", False)),
                        "context_summary": checkpoint_data.get("context_summary", ""),
                        "default_value": checkpoint_data.get("default_value", ""),
                        "metadata": checkpoint_data.get("metadata", {}),
                        "user_agent_task": user_agent_task,
                    },
                })
                self.logger.info("✅ Sent checkpoint request to frontend")
            else:
                self.logger.warning("⚠️ No WebSocket manager available for checkpoint request")
            await record_user_interaction_asked(
                agent_task_id,
                interaction_id=checkpoint_data.get("checkpoint_id") or f"checkpoint_{uuid4().hex}",
                kind=checkpoint_interaction_kind(checkpoint_data),
                prompt=prompt,
                input_type=checkpoint_data.get("input_type"),
                options=checkpoint_data.get("options"),
                broadcast=self.websocket_manager.broadcast if self.websocket_manager else None,
            )
            if self.status_notifier and agent_task_id:
                await self.status_notifier.send_checkpoint_waiting_status(
                    agent_task_id=agent_task_id,
                    prompt=prompt,
                )
        except Exception as error:
            self.logger.error(f"❌ Failed to handle checkpoint request: {error}", exc_info=True)

    def create_checkpoint_pending_result(self, user_agent_task: str) -> WorkflowExecutionResult:
        """Return the workflow result used while awaiting checkpoint input."""
        return WorkflowExecutionResult(
            original_prompt=user_agent_task,
            execution_results=[{"status": "awaiting_user_input", "needs_user_input": True}],
            total_execution_duration=0.0,
            todos_completed=0,
            todos_failed=0,
            overall_success=True,
            tool_execution_summary={
                "status": "awaiting_user_input",
                "message": "Workflow paused - awaiting user input",
            },
        )

    async def resume_workflow(
        self,
        agent_task_id: str,
        user_response: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> WorkflowExecutionResult:
        """Resume a checkpointed workflow using the user response."""
        try:
            from ..execution_graph.agent_graph_runtime import (
                _derive_thread_id,
                _open_tool_enhanced_graph,
            )
        except ImportError:
            self.logger.error("❌ Cannot resume workflow - LangGraph not available")
            raise RuntimeError("LangGraph is required for checkpoint resume functionality")

        try:
            self.logger.info(f"🔄 Resuming workflow for agent_task_id: {agent_task_id}")
            self.logger.info(f"   User response: {user_response}")
            thread_id = _derive_thread_id({"agent_task_id": agent_task_id}, "")
            async with _open_tool_enhanced_graph() as app:
                config = {"configurable": {"thread_id": thread_id}}
                try:
                    checkpoint_state = await app.aget_state(config)
                    if not checkpoint_state or not checkpoint_state.values:
                        self.logger.error(f"❌ No checkpoint found for thread_id: {thread_id}")
                        raise ValueError(f"No checkpoint found for agent_task_id: {agent_task_id}")
                    self.logger.info(f"✅ Found checkpoint for thread_id: {thread_id}")
                    self.logger.info(
                        f"   Checkpoint state keys: "
                        f"{list(checkpoint_state.values.keys()) if checkpoint_state.values else 'empty'}"
                    )
                except Exception as error:
                    self.logger.error(f"❌ Failed to retrieve checkpoint: {error}")
                    raise

                from api.dependencies import get_sqlite_knowledge_service

                knowledge_service = get_sqlite_knowledge_service()
                await knowledge_service.update_agent_task_status(
                    agent_task_id=agent_task_id,
                    status="processing",
                )
                if self.status_notifier:
                    await self.status_notifier.send_checkpoint_resumed_status(
                        agent_task_id=agent_task_id,
                        user_response=user_response,
                    )

                updated_state = dict(checkpoint_state.values)
                updated_state["user_checkpoint_response"] = user_response
                updated_state["checkpoint_resolved"] = True
                original_prompt = updated_state.get("user_agent_task", "")
                tool_results = updated_state.get("tool_execution_results", [])
                checkpoint_prompt = self._get_checkpoint_prompt(tool_results)
                agent_task = None
                if not checkpoint_prompt:
                    agent_task_service = getattr(
                        knowledge_service,
                        "agent_task_service",
                        None,
                    )
                    if agent_task_service is not None:
                        agent_task = await agent_task_service.get_agent_task(
                            agent_task_id
                        )
                        checkpoint_prompt = (
                            self._get_checkpoint_prompt_from_result_data(
                                getattr(agent_task, "result_data", None)
                            )
                        )
                provider_target_authorization_resolution = (
                    await self._resolve_provider_target_checkpoint_response(
                        knowledge_service=knowledge_service,
                        agent_task_id=agent_task_id,
                        agent_task=agent_task,
                        tool_results=tool_results,
                        user_response=user_response,
                    )
                )
                if updated_state.get("agent_messages"):
                    updated_state["agent_resume_input"] = self._build_checkpoint_tool_result(
                        tool_results=tool_results,
                        user_response=user_response,
                        provider_target_authorization_resolution=(
                            provider_target_authorization_resolution
                        ),
                    )
                    self.logger.info("🔄 Answering the paused tool call with the user's response")
                else:
                    updated_state["user_agent_task"] = self._build_continuation_agent_task(
                        original_prompt=original_prompt,
                        checkpoint_prompt=checkpoint_prompt,
                        tool_results=tool_results,
                        user_response=user_response,
                        agent_task_id=agent_task_id,
                        provider_target_authorization_resolution=(
                            provider_target_authorization_resolution
                        ),
                    )
                    self.logger.info("🔄 Updated user_agent_task for continuation")
                await resolve_latest_waiting_user_interaction(
                    agent_task_id,
                    kinds=("clarification", "provider_target"),
                    status=checkpoint_interaction_status(
                        user_response,
                        provider_target_authorization_resolution,
                    ),
                    response=(
                        None
                        if user_response == USER_DISMISSED_CHECKPOINT_RESPONSE
                        else user_response
                    ),
                    broadcast=self.websocket_manager.broadcast if self.websocket_manager else None,
                )

                existing_context = updated_state.get("context", {})
                resumed_context = dict(existing_context) if isinstance(existing_context, dict) else {}
                resumed_context["websocket_manager"] = self.websocket_manager
                resumed_context["agent_task_id"] = agent_task_id
                workflow_coordinator = getattr(self, "workflow_coordinator", None)
                if workflow_coordinator is not None:
                    resumed_context["_workflow_coordinator"] = workflow_coordinator
                paused_thinking_history = await self._paused_thinking_history(
                    knowledge_service,
                    agent_task_id,
                    agent_task,
                )
                if paused_thinking_history:
                    from ..finalization.task_state_persistence import (
                        PRIOR_THINKING_HISTORY_CONTEXT_KEY,
                    )

                    resumed_context[PRIOR_THINKING_HISTORY_CONTEXT_KEY] = paused_thinking_history
                updated_state["context"] = resumed_context
                if context:
                    if isinstance(context.get("context"), dict):
                        updated_state["context"].update(context["context"])
                    else:
                        for key, value in context.items():
                            if key != "context":
                                updated_state[key] = value

                self.logger.info(
                    f"🔄 Resuming with merged state. User response: '{user_response[:50]}...'"
                )
                self.logger.info(
                    f"   Preserved keys from checkpoint: {list(updated_state.keys())}"
                )
                try:
                    final_state = await run_registered_resume(
                        agent_task_id,
                        app.ainvoke(updated_state, config=config),
                    )
                    self.logger.info("✅ Workflow resumed and completed")
                    self.logger.info(
                        f"   Final state keys: {list(final_state.keys()) if isinstance(final_state, dict) else 'n/a'}"
                    )
                    result = self._create_resumed_workflow_result(final_state)
                    from .resume_terminal_finalizer import finalize_resumed_workflow

                    try:
                        await finalize_resumed_workflow(
                            agent_task_id,
                            final_state,
                            self.websocket_manager,
                        )
                    except Exception as finalize_error:
                        self.logger.error(
                            "❌ Resume terminal finalization failed for %s: %s",
                            agent_task_id,
                            finalize_error,
                            exc_info=True,
                        )
                    return result
                except ResumedRunCanceled:
                    return await self._settle_canceled_resume(agent_task_id, updated_state)
                except Exception as resume_error:
                    if self.is_checkpoint_request(resume_error):
                        self.logger.info("🛑 Agent requested another checkpoint during resume")
                        await self.handle_checkpoint_request(
                            resume_error,
                            agent_task_id,
                            "resumed workflow",
                        )
                        return self.create_checkpoint_pending_result("resumed workflow")
                    raise
        except Exception as error:
            self.logger.error(f"❌ Failed to resume workflow: {error}", exc_info=True)
            if self.status_notifier:
                await self.status_notifier.send_status_update(
                    "Workflow resume failed",
                    f"Error: {str(error)}",
                )
            raise

    async def resume_workflow_after_provider_delegation(
        self,
        *,
        parent_agent_task_id: str,
        child_outcomes: Sequence[Mapping[str, object]],
    ) -> WorkflowExecutionResult:
        """Resume one durable primary checkpoint from every settled delegated-child outcome."""
        from ..execution_graph.agent_graph_runtime import (
            _derive_thread_id,
            _open_tool_enhanced_graph,
        )
        from .resume_terminal_finalizer import finalize_resumed_workflow
        from api.dependencies import get_sqlite_knowledge_service

        required = {
            "delegated_agent_run_id",
            "executor_kind",
            "terminal_status",
            "evidence_state",
            "summary",
        }
        if not child_outcomes:
            raise ValueError("child_outcomes must contain at least one settled delegated child")
        for outcome in child_outcomes:
            if not required.issubset(outcome):
                raise ValueError("child_outcomes contains an incomplete outcome")
        config = {
            "configurable": {
                "thread_id": _derive_thread_id(
                    {"agent_task_id": parent_agent_task_id},
                    "",
                )
            }
        }
        async with _open_tool_enhanced_graph() as app:
            checkpoint_state = await app.aget_state(config)
            if checkpoint_state is None or not checkpoint_state.values:
                raise ValueError(
                    f"No parent workflow checkpoint found for {parent_agent_task_id}"
                )
            knowledge_service = get_sqlite_knowledge_service()
            parent = await knowledge_service.get_agent_task(parent_agent_task_id)
            if parent is None:
                raise ValueError(f"Parent Agent Task {parent_agent_task_id} does not exist")
            if parent.status in {"completed", "failed", "canceled"}:
                raise ValueError("Parent Agent Task is already terminal")
            await knowledge_service.update_agent_task_status(
                agent_task_id=parent_agent_task_id,
                status="processing",
            )
            updated_state = dict(checkpoint_state.values)
            if updated_state.get("agent_messages"):
                updated_state["agent_resume_input"] = self._build_provider_delegation_result(
                    child_outcomes=child_outcomes,
                )
            else:
                updated_state["user_agent_task"] = self._build_provider_delegation_continuation(
                    original_prompt=str(updated_state.get("user_agent_task") or ""),
                    child_outcomes=child_outcomes,
                )
            existing_context = updated_state.get("context")
            context = dict(existing_context) if isinstance(existing_context, dict) else {}
            context["agent_task_id"] = parent_agent_task_id
            context["websocket_manager"] = self.websocket_manager
            context["provider_delegation_continuation"] = True
            workflow_coordinator = getattr(self, "workflow_coordinator", None)
            if workflow_coordinator is not None:
                context["_workflow_coordinator"] = workflow_coordinator
            updated_state["context"] = context
            try:
                final_state = await run_registered_resume(
                    parent_agent_task_id,
                    app.ainvoke(updated_state, config=config),
                )
            except ResumedRunCanceled:
                return await self._settle_canceled_resume(parent_agent_task_id, updated_state)
            except Exception as error:
                if self.is_checkpoint_request(error):
                    await self.handle_checkpoint_request(
                        error,
                        parent_agent_task_id,
                        "delegated provider continuation",
                    )
                    return self.create_checkpoint_pending_result(
                        "delegated provider continuation"
                    )
                raise
            result = self._create_resumed_workflow_result(final_state)
            tool_results_for_wait_check = (
                final_state.get("tool_execution_results") if isinstance(final_state, dict) else None
            )
            still_waiting = isinstance(tool_results_for_wait_check, list) and any(
                isinstance(item, dict) and item.get("status") == "awaiting_delegated_agents"
                for item in tool_results_for_wait_check
            )
            if still_waiting:
                await knowledge_service.update_agent_task_status(
                    agent_task_id=parent_agent_task_id,
                    status="awaiting_delegated_agents",
                )
                return result
            await finalize_resumed_workflow(
                parent_agent_task_id,
                final_state,
                self.websocket_manager,
            )
            return result

    async def resume_workflow_for_delegated_supervision(
        self,
        *,
        parent_agent_task_id: str,
        delegated_agent_run: Mapping[str, object],
        report_card: Mapping[str, object],
    ) -> WorkflowExecutionResult:
        """Resume one paused parent so it may supervise a live ACP child turn."""
        from ..execution_graph.agent_graph_runtime import (
            _derive_thread_id,
            _open_tool_enhanced_graph,
        )
        from .resume_terminal_finalizer import finalize_resumed_workflow
        from api.dependencies import get_sqlite_knowledge_service

        if str(delegated_agent_run.get("executor_kind")) != "acp_provider":
            raise ValueError("delegated_agent_run must be an ACP provider child")
        if str(delegated_agent_run.get("status")) != "supervision_due":
            raise ValueError("delegated_agent_run must be supervision_due")
        if not isinstance(report_card, Mapping) or not report_card:
            raise ValueError("report_card must be a non-empty mapping")

        config = {
            "configurable": {
                "thread_id": _derive_thread_id({"agent_task_id": parent_agent_task_id}, "")
            }
        }
        async with _open_tool_enhanced_graph() as app:
            checkpoint_state = await app.aget_state(config)
            if checkpoint_state is None or not checkpoint_state.values:
                raise ValueError(f"No parent workflow checkpoint found for {parent_agent_task_id}")
            knowledge_service = get_sqlite_knowledge_service()
            parent = await knowledge_service.get_agent_task(parent_agent_task_id)
            if parent is None:
                raise ValueError(f"Parent Agent Task {parent_agent_task_id} does not exist")
            if parent.status in {"completed", "failed", "canceled"}:
                raise ValueError("Parent Agent Task is already terminal")
            await knowledge_service.update_agent_task_status(
                agent_task_id=parent_agent_task_id,
                status="processing",
            )
            updated_state = dict(checkpoint_state.values)
            if updated_state.get("agent_messages"):
                updated_state["agent_resume_input"] = self._build_acp_supervision_result(
                    delegated_agent_run_id=str(delegated_agent_run["id"]),
                    report_card=report_card,
                )
            else:
                updated_state["user_agent_task"] = self._build_acp_supervision_continuation(
                    original_prompt=str(updated_state.get("user_agent_task") or ""),
                    delegated_agent_run_id=str(delegated_agent_run["id"]),
                    report_card=report_card,
                )
            existing_context = updated_state.get("context")
            context = dict(existing_context) if isinstance(existing_context, dict) else {}
            context["agent_task_id"] = parent_agent_task_id
            context["websocket_manager"] = self.websocket_manager
            context["provider_delegation_continuation"] = True
            context["delegated_supervision"] = {"delegated_agent_run_id": str(delegated_agent_run["id"])}
            workflow_coordinator = getattr(self, "workflow_coordinator", None)
            if workflow_coordinator is not None:
                context["_workflow_coordinator"] = workflow_coordinator
            updated_state["context"] = context
            try:
                final_state = await run_registered_resume(
                    parent_agent_task_id,
                    app.ainvoke(updated_state, config=config),
                )
            except ResumedRunCanceled:
                return await self._settle_canceled_resume(parent_agent_task_id, updated_state)
            except Exception as error:
                if self.is_checkpoint_request(error):
                    await self.handle_checkpoint_request(
                        error,
                        parent_agent_task_id,
                        "delegated ACP supervision",
                    )
                    return self.create_checkpoint_pending_result("delegated ACP supervision")
                raise
            result = self._create_resumed_workflow_result(final_state)
            tool_results = final_state.get("tool_execution_results") if isinstance(final_state, dict) else None
            still_waiting = isinstance(tool_results, list) and any(
                isinstance(item, dict) and item.get("status") == "awaiting_delegated_agents"
                for item in tool_results
            )
            if still_waiting:
                await knowledge_service.update_agent_task_status(
                    agent_task_id=parent_agent_task_id,
                    status="awaiting_delegated_agents",
                )
                return result
            await finalize_resumed_workflow(
                parent_agent_task_id,
                final_state,
                self.websocket_manager,
            )
            return result

    @staticmethod
    def _build_acp_supervision_continuation(
        *, original_prompt: str, delegated_agent_run_id: str, report_card: Mapping[str, object]
    ) -> str:
        supervision_result = WorkflowCheckpointWorkflowService._build_acp_supervision_result(
            delegated_agent_run_id=delegated_agent_run_id,
            report_card=report_card,
        )
        return f"{original_prompt}\n\n{supervision_result}"

    @staticmethod
    def _build_acp_supervision_result(
        *, delegated_agent_run_id: str, report_card: Mapping[str, object]
    ) -> str:
        return f"""[ACP SUPERVISION REQUIRED]
delegated_agent_run_id: {delegated_agent_run_id}
executor_kind: acp_provider
evidence_capture_state: {report_card.get("capture_state")}
evidence_count: {report_card.get("evidence_count")}
latest_summary: {report_card.get("latest_summary")}
claims: {list(report_card.get("claims") or [])}
artifacts: {list(report_card.get("artifacts") or [])}

You are the supervisor. Treat every provider_reported claim as unverified. Use delegated_agent to continue, settle_completed, settle_failed, or cancel this exact run. Do not emit final_envelope while any delegated child remains active."""

    @staticmethod
    def _build_provider_delegation_continuation(
        *,
        original_prompt: str,
        child_outcomes: Sequence[Mapping[str, object]],
    ) -> str:
        delegation_result = WorkflowCheckpointWorkflowService._build_provider_delegation_result(
            child_outcomes=child_outcomes,
        )
        return f"{original_prompt}\n\n{delegation_result}"

    @staticmethod
    def _build_provider_delegation_result(
        *,
        child_outcomes: Sequence[Mapping[str, object]],
    ) -> str:
        blocks = "\n\n".join(
            f"""[DELEGATED CHILD RESULT {index + 1} of {len(child_outcomes)}]
delegated_agent_run_id: {outcome["delegated_agent_run_id"]}
executor_kind: {outcome["executor_kind"]}
terminal_status: {outcome["terminal_status"]}
evidence_state: {outcome["evidence_state"]}
summary: {outcome["summary"]}"""
            for index, outcome in enumerate(child_outcomes)
        )
        return f"""{blocks}

Every delegated child above is terminal. Treat each summary as durable evidence labeled by its evidence_state; an evidence_state of provider_reported or unavailable is not independently verified. Do not attempt another delegated-child proposal for work already reported above. Continue the original task from this evidence, ask another user checkpoint only when necessary, and otherwise emit your own final_envelope."""

    @staticmethod
    def _get_checkpoint_prompt(tool_results: Any) -> str:
        if not isinstance(tool_results, list) or not tool_results:
            return ""
        last_result = tool_results[-1]
        if not isinstance(last_result, dict):
            return ""
        checkpoint_data = last_result.get("checkpoint_data", {})
        return checkpoint_data.get("prompt", "") if isinstance(checkpoint_data, dict) else ""

    async def _paused_thinking_history(
        self,
        knowledge_service: Any,
        agent_task_id: str,
        agent_task: Any,
    ) -> list[dict[str, Any]]:
        """Return the reasoning saved when the task paused, so the resumed run keeps it."""
        from ..finalization.task_state_persistence import normalize_thinking_history

        try:
            if agent_task is None:
                agent_task_service = getattr(knowledge_service, "agent_task_service", None)
                if agent_task_service is None:
                    return []
                agent_task = await agent_task_service.get_agent_task(agent_task_id)
            result_data = getattr(agent_task, "result_data", None)
            if isinstance(result_data, str):
                result_data = json.loads(result_data)
            if not isinstance(result_data, Mapping):
                return []
            return normalize_thinking_history(result_data.get("thinking_history"))
        except Exception:
            self.logger.warning("Could not read paused reasoning for %s", agent_task_id, exc_info=True)
            return []

    async def _resolve_provider_target_checkpoint_response(
        self,
        *,
        knowledge_service: Any,
        agent_task_id: str,
        agent_task: Any,
        tool_results: Any,
        user_response: str,
    ) -> dict[str, object] | None:
        authorization_id = self._get_provider_target_checkpoint_authorization_id(
            tool_results
        )
        if authorization_id is None:
            authorization_id = self._get_provider_target_checkpoint_authorization_id_from_result_data(
                getattr(agent_task, "result_data", None)
            )
        if agent_task is None:
            agent_task_service = getattr(
                knowledge_service,
                "agent_task_service",
                None,
            )
            if agent_task_service is None:
                return None
            agent_task = await agent_task_service.get_agent_task(agent_task_id)
        root_task_id = getattr(agent_task, "root_task_id", None) or getattr(
            agent_task, "id", None
        )
        if not isinstance(root_task_id, str) or not root_task_id:
            raise ValueError(
                "Provider target checkpoint cannot resolve without a current root Agent Task ID."
            )
        if authorization_id is None:
            authorization_repository = getattr(
                knowledge_service,
                "provider_target_authorization_repository",
                None,
            )
            get_pending_authorization = getattr(
                authorization_repository,
                "get_single_pending_initial_authorization_for_task",
                None,
            )
            if callable(get_pending_authorization):
                pending_authorization = await get_pending_authorization(
                    agent_task_id=agent_task_id,
                    root_task_id=root_task_id,
                )
                if isinstance(pending_authorization, Mapping):
                    pending_id = pending_authorization.get("id")
                    if isinstance(pending_id, str) and pending_id.strip():
                        authorization_id = pending_id.strip()
        if authorization_id is None:
            return None
        authorization_service = _create_provider_target_authorization_service(
            knowledge_service
        )
        return await authorization_service.resolve_checkpoint_response(
            agent_task_id=agent_task_id,
            root_task_id=root_task_id,
            authorization_id=authorization_id,
            response=user_response,
        )

    def _build_continuation_agent_task(
        self,
        original_prompt: str,
        checkpoint_prompt: str,
        tool_results: Any,
        user_response: str,
        agent_task_id: str,
        provider_target_authorization_resolution: Mapping[str, object] | None = None,
    ) -> str:
        if user_response == USER_DISMISSED_CHECKPOINT_RESPONSE:
            dismiss_prompt_context = (
                f' (your last checkpoint prompt was: "{checkpoint_prompt}")'
                if checkpoint_prompt
                else ""
            )
            self.logger.info(
                f"🚪 Dismiss-resume path activated for {agent_task_id} - "
                "steering agent to emit final_envelope without further tool calls"
            )
            return f"""{original_prompt}

[USER DISMISSED CHECKPOINT]
The user closed the agent-task widget without answering your last checkpoint{dismiss_prompt_context}.

Instructions for this turn (STRICT):
- Do NOT call any more tools.
- Do NOT ask the user another question.
- Synthesize a final answer using ONLY the work you have already completed.
- Emit your final_envelope now.
- If no useful work was completed yet, emit a final_envelope explaining that
  the task was canceled before completion and briefly summarize what you had
  planned to do, so the user has a clean record.
"""

        if checkpoint_prompt or provider_target_authorization_resolution:
            resolution_context = self._get_provider_target_resolution_context(tool_results)
            if (
                provider_target_authorization_resolution
                and provider_target_authorization_resolution.get("status") == "authorized"
                and isinstance(
                    provider_target_authorization_resolution.get("id"),
                    str,
                )
            ):
                resolution_context += (
                    "\n[PROVIDER TARGET AUTHORIZATION RESOLVED]\n"
                    f"authorization_id: {provider_target_authorization_resolution['id']}\n"
                    "status: authorized\n"
                    "The selected target is already authorized. Do not list, describe, "
                    "propose, authorize, or request another provider target. Call "
                    "provider_catalog action='delegate' exactly once with this "
                    "authorization_id.\n"
                )
            prior_checkpoint_prompt = checkpoint_prompt or "provider target authorization"
            return f"""{original_prompt}
{resolution_context}
[CONTINUATION - The agent previously asked: "{prior_checkpoint_prompt}"]
[USER RESPONSE: {user_response}]

Continue from where you left off and act on the user's response above."""

        return f"""{original_prompt}

[CONTINUATION - User responded: {user_response}]

Continue from where you left off using the user's response above."""

    def _build_checkpoint_tool_result(
        self,
        *,
        tool_results: Any,
        user_response: str,
        provider_target_authorization_resolution: Mapping[str, object] | None = None,
    ) -> str:
        if user_response == USER_DISMISSED_CHECKPOINT_RESPONSE:
            return (
                "The user closed the question without answering. Do NOT call any more tools and do NOT ask "
                "another question. Write your final answer now using only the work already completed in this "
                "conversation. If no useful work was completed, say the task was canceled before completion "
                "and briefly summarize what you had planned to do."
            )
        resolution_context = self._get_provider_target_resolution_context(tool_results)
        if (
            provider_target_authorization_resolution
            and provider_target_authorization_resolution.get("status") == "authorized"
            and isinstance(provider_target_authorization_resolution.get("id"), str)
        ):
            resolution_context += (
                "\n[PROVIDER TARGET AUTHORIZATION RESOLVED]\n"
                f"authorization_id: {provider_target_authorization_resolution['id']}\n"
                "status: authorized\n"
                "The selected target is already authorized. Do not list, describe, "
                "propose, authorize, or request another provider target. Call "
                "provider_catalog action='delegate' exactly once with this "
                "authorization_id.\n"
            )
        resolution_context = resolution_context.strip()
        if not resolution_context:
            return f"User response: {user_response}"
        return f"{resolution_context}\n\nUser response: {user_response}"

    def _get_provider_target_resolution_context(self, tool_results: Any) -> str:
        if not isinstance(tool_results, list) or not tool_results:
            return ""
        last_result = tool_results[-1]
        if not isinstance(last_result, dict):
            return ""
        prior_checkpoint = last_result.get("checkpoint_data", {})
        if not isinstance(prior_checkpoint, dict):
            return ""
        checkpoint_metadata = prior_checkpoint.get("metadata")
        if not isinstance(checkpoint_metadata, dict):
            return ""
        if checkpoint_metadata.get("source") != "provider_target_authorization":
            return ""
        authorization_id = self._get_provider_target_checkpoint_authorization_id(
            tool_results
        )
        if authorization_id is None:
            return ""
        return (
            "\n[CHECKPOINT RESOLUTION CONTEXT]\n"
            f"authorization_id: {authorization_id}\n"
            "source: provider_target_authorization\n"
        )

    @staticmethod
    def _get_provider_target_checkpoint_authorization_id(
        tool_results: Any,
    ) -> str | None:
        if not isinstance(tool_results, list) or not tool_results:
            return None
        last_result = tool_results[-1]
        if not isinstance(last_result, dict):
            return None
        checkpoint_data = last_result.get("checkpoint_data", {})
        if not isinstance(checkpoint_data, dict):
            return None
        checkpoint_metadata = checkpoint_data.get("metadata")
        if (
            not isinstance(checkpoint_metadata, dict)
            or checkpoint_metadata.get("source") != "provider_target_authorization"
        ):
            return None
        authorization_id = checkpoint_metadata.get("authorization_id")
        if not isinstance(authorization_id, str) or not authorization_id.strip():
            return None
        return authorization_id.strip()

    @classmethod
    def _get_provider_target_checkpoint_authorization_id_from_result_data(
        cls,
        result_data: Any,
    ) -> str | None:
        checkpoint_data = cls._get_checkpoint_data_from_result_data(result_data)
        return cls._get_provider_target_checkpoint_authorization_id(
            [{"checkpoint_data": checkpoint_data}]
        )

    @classmethod
    def _get_checkpoint_prompt_from_result_data(cls, result_data: Any) -> str:
        checkpoint_data = cls._get_checkpoint_data_from_result_data(result_data)
        return cls._get_checkpoint_prompt([{"checkpoint_data": checkpoint_data}])

    @staticmethod
    def _get_checkpoint_data_from_result_data(result_data: Any) -> Any:
        if isinstance(result_data, str):
            try:
                result_data = json.loads(result_data)
            except json.JSONDecodeError:
                return None
        if not isinstance(result_data, dict):
            return None
        return result_data.get("checkpoint_data")

    async def _settle_canceled_resume(
        self,
        agent_task_id: str,
        updated_state: Dict[str, Any],
    ) -> WorkflowExecutionResult:
        self.logger.info("🛑 Resumed run stopped by the user: %s", agent_task_id)
        try:
            from api.dependencies import get_sqlite_knowledge_service

            await get_sqlite_knowledge_service().update_agent_task_status(
                agent_task_id=agent_task_id,
                status="canceled",
            )
        except Exception as error:
            self.logger.warning("Could not record the stopped resume for %s: %s", agent_task_id, error)
        return WorkflowExecutionResult(
            original_prompt=str(updated_state.get("user_agent_task") or ""),
            execution_results=[{"status": "canceled", "success": False}],
            total_execution_duration=0.0,
            todos_completed=0,
            todos_failed=0,
            overall_success=False,
            error_message="Run stopped",
        )

    def _create_resumed_workflow_result(self, final_state: Dict[str, Any]) -> WorkflowExecutionResult:
        tool_results = final_state.get("tool_execution_results", [])
        todos_completed = len([result for result in tool_results if result.get("success", False)])
        todos_failed = len([result for result in tool_results if not result.get("success", True)])
        result = WorkflowExecutionResult(
            original_prompt=final_state.get("user_agent_task", ""),
            execution_results=tool_results,
            total_execution_duration=0.0,
            todos_completed=todos_completed,
            todos_failed=todos_failed,
            overall_success=todos_completed > 0 or todos_failed == 0,
        )
        final_envelope = final_state.get("final_envelope")
        if final_envelope:
            setattr(result, "final_envelope", final_envelope)
            self.logger.info("✅ Attached final_envelope to result")
        return result

    async def has_checkpoint(self, agent_task_id: str) -> bool:
        """Return whether a resumable checkpoint exists for one agent task."""
        try:
            from ..execution_graph.agent_graph_runtime import (
                _derive_thread_id,
                _open_tool_enhanced_graph,
            )
        except ImportError:
            self.logger.debug("LangGraph not available - no checkpoint support")
            return False

        try:
            thread_id = _derive_thread_id({"agent_task_id": agent_task_id}, "")
            async with _open_tool_enhanced_graph() as app:
                config = {"configurable": {"thread_id": thread_id}}
                checkpoint_state = await app.aget_state(config)
                has_checkpoint = (
                    checkpoint_state is not None
                    and checkpoint_state.values is not None
                    and len(checkpoint_state.values) > 0
                )
                if has_checkpoint:
                    self.logger.info(f"✅ Checkpoint found for agent_task_id: {agent_task_id}")
                else:
                    self.logger.debug(f"No checkpoint for agent_task_id: {agent_task_id}")
                return has_checkpoint
        except Exception as error:
            self.logger.debug(f"Error checking checkpoint for {agent_task_id}: {error}")
            return False

    async def resume_failed_workflow(
        self,
        agent_task_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> WorkflowExecutionResult:
        """Resume a failed workflow from its checkpoint when one exists."""
        if not await self.has_checkpoint(agent_task_id):
            raise ValueError(f"No checkpoint found for agent_task_id: {agent_task_id}. Use retry instead.")
        return await self.resume_workflow(
            agent_task_id=agent_task_id,
            user_response="[RESUMING FAILED WORKFLOW - Continue from where execution was interrupted]",
            context=context,
        )
