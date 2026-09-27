import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from api.services.agent_processing.lifecycle.execution_graph.agent_result_synthesis import (
    stream_synthesized_final_answer,
)
from api.services.agent_processing.lifecycle.planning.agent_context_assembler import (
    render_chain_turns_as_conversation,
)
from api.services.agent_processing.lifecycle.submission.agent_task_event_broadcaster import (
    AgentTaskEventBroadcaster,
)
from api.services.agent_processing.lifecycle.runtime.workflow_status_notifier import (
    WorkflowStatusNotifier,
)
from api.services.agent_processing.lifecycle.submission.fast_lane_intent_gate import (
    evaluate_fast_lane_intent,
    resolve_fast_lane_reasoning_model,
)

logger = logging.getLogger(__name__)

FAST_LANE_SYSTEM = (
    "You are continuing an ongoing conversation with this user. The conversation "
    "history you're given is the actual exchange so far -- \"You:\" lines are "
    "things you already said, not a report about someone else's work. Answer the "
    "user's latest follow-up using that history. Do not call tools or invent new "
    "actions; if the answer isn't already available from the conversation, say so "
    "plainly rather than guessing. If a WORK_LEDGER section is present, it holds "
    "durable, structured records (scope, discovered entities, operation receipts) "
    "from this task chain's actual tool execution -- prefer it over your own "
    "conversational recollection whenever the user asks about what was found, "
    "decided, or verified, since the ledger reflects what actually happened rather "
    "than a prior turn's self-reported summary."
)


class AgentTaskSubmissionService:
    """Owns direct agent-task submission, state, and frontend broadcasts."""

    def __init__(
        self,
        *,
        agent_task_orchestrator,
        db_service,
        wake_word_service=None,
    ) -> None:
        self.agent_task_orchestrator = agent_task_orchestrator
        self.db_service = db_service
        self.wake_word_service = wake_word_service
        self._current_screenshot_data: Optional[Dict[str, Any]] = None
        self._last_cancel_timestamp = 0.0
        self._event_broadcaster = AgentTaskEventBroadcaster()

    async def broadcast(self, message_data: Dict[str, Any]) -> None:
        """Broadcast a message to all connected WebSocket clients."""
        event_type = str(message_data.get("event_type") or "")
        agent_task_id = str(message_data.get("agent_task_id") or "")
        cancellation_safe_events = {
            "agent_task_cancelled",
            "agentTask_cancelled",
            "agent_task_origin",
        }
        if (
            agent_task_id
            and event_type not in cancellation_safe_events
            and self.agent_task_orchestrator is not None
            and hasattr(self.agent_task_orchestrator, "is_agent_task_cancelled")
            and self.agent_task_orchestrator.is_agent_task_cancelled(agent_task_id)
        ):
            logger.debug(
                "Dropping %s for cancelled agent task %s",
                event_type,
                agent_task_id,
            )
            return
        await self._event_broadcaster.broadcast(message_data)

    async def _process_agent_task_direct_impl(
        self,
        agent_task: str,
        display_prompt_markdown: Optional[str] = None,
        clarification_agent_task: str = None,
        agent_task_id: str = None,
        root_task_id: str = None,
        previous_task_id: str = None,
        reference_paths: Optional[List[str]] = None,
        model_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        approval_policy_override: Optional[Dict[str, Any]] = None,
        origin_type: Optional[str] = None,
        origin_id: Optional[str] = None,
        todo_workspace_context: Optional[Dict[str, Any]] = None,
        todo_worker_context: Optional[Dict[str, Any]] = None,
        local_preview_feedback: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Process an agent task directly without wake-word detection."""
        logger.info("Processing agent_task directly: %r", agent_task)

        try:
            if self._last_cancel_timestamp and (time.time() - self._last_cancel_timestamp) < 5.0:
                logger.info("Direct processing suppressed due to recent cancellation window")
                return {
                    "success": False,
                    "operation": "cancelled",
                    "confidence": 0.0,
                    "reasoning": "User cancelled the agent_task; ignoring late-arriving audio.",
                    "message": "Task was cancelled",
                }

            chain_context = None
            if root_task_id:
                logger.info("Building chain context for follow-up root=%s previous=%s", root_task_id, previous_task_id)
                chain_context = await self._build_chain_context(root_task_id, previous_task_id=previous_task_id)
                if not chain_context:
                    logger.warning("Root task %s not found, treating as standalone task", root_task_id)

            if local_preview_feedback is not None:
                if chain_context is None:
                    raise ValueError("local_preview_feedback requires an existing task chain")
                accumulated_artifacts = chain_context.setdefault("accumulated_artifacts", {})
                accumulated_artifacts["local_web_preview_feedback"] = dict(local_preview_feedback)

            if clarification_agent_task and agent_task_id:
                logger.info("Processing clarification for agent task %s", agent_task_id)
                return await self.agent_task_orchestrator.add_clarification(
                    agent_task_id=agent_task_id,
                    clarification_text=agent_task,
                )

            if not agent_task_id:
                agent_task_id = str(uuid.uuid4())

            if approval_policy_override:
                from api.services.agent_processing.tools.safety.approval_override import (
                    ApprovalOverride,
                    register_override,
                )
                try:
                    register_override(agent_task_id, ApprovalOverride(**approval_policy_override))
                except Exception as exc:
                    logger.warning("Ignoring invalid approval_policy_override: %s", exc)

            if origin_type and origin_id:
                await self.broadcast(
                    {
                        "event_type": "agent_task_origin",
                        "agent_task_id": agent_task_id,
                        "root_task_id": root_task_id,
                        "previous_task_id": previous_task_id,
                        "origin_type": origin_type,
                        "origin_id": origin_id,
                    }
                )

            result = await self.agent_task_orchestrator.process_agent_task(
                agent_task=agent_task,
                display_prompt_markdown=display_prompt_markdown,
                pre_captured_screenshot=self._current_screenshot_data,
                agent_task_id=agent_task_id,
                synchronous=False,
                chain_context=chain_context,
                reference_paths=reference_paths,
                model_id=model_id,
                conversation_id=conversation_id,
                origin_type=origin_type,
                origin_id=origin_id,
                todo_workspace_context=todo_workspace_context,
                todo_worker_context=todo_worker_context,
            )
            logger.info("Orchestrator processing completed: status=%s", result.get("status", "unknown"))
            return result
        except Exception as exc:
            logger.error("Error in process_agent_task_direct: %s", exc, exc_info=True)
            return {
                "success": False,
                "operation": "error",
                "confidence": 0.0,
                "reasoning": f"Error during agent-task processing: {str(exc)}",
                "message": "AgentTask processing failed",
                "error": str(exc),
            }

    async def _build_chain_context(self, root_task_id: str, previous_task_id: str = None) -> Optional[Dict[str, Any]]:
        """Build context for a follow-up turn by retrieving root task and chain history."""
        try:
            root_task = await self.db_service.get_agent_task(root_task_id)
            if root_task:
                root_task_id = root_task.root_task_id or root_task.id

            chain_agent_tasks = await self.db_service.get_agent_task_chain(root_task_id)
            if not chain_agent_tasks:
                logger.warning("Root task %s not found", root_task_id)
                return None

            accumulated_artifacts = {"chain_agentTasks": []}
            for agent_task_record in chain_agent_tasks:
                agent_task_artifact = {
                    "id": agent_task_record.id,
                    "root_task_id": agent_task_record.root_task_id or agent_task_record.id,
                    "previous_task_id": agent_task_record.previous_task_id,
                    "sequence": agent_task_record.chain_sequence_number,
                    "text": agent_task_record.transcribed_prompt,
                    "timestamp": agent_task_record.timestamp.isoformat(),
                    "status": agent_task_record.status,
                }
                if agent_task_record.result_data:
                    agent_task_artifact["result"] = agent_task_record.result_data
                if agent_task_record.operation_parameters:
                    agent_task_artifact["operation"] = agent_task_record.operation_parameters
                accumulated_artifacts["chain_agentTasks"].append(agent_task_artifact)

            latest_agent_task = chain_agent_tasks[-1]
            if latest_agent_task.accumulated_artifacts:
                for key, value in latest_agent_task.accumulated_artifacts.items():
                    if key != "chain_agentTasks":
                        accumulated_artifacts[key] = value

            return {
                "root_task_id": root_task_id,
                "previous_task_id": previous_task_id or latest_agent_task.id,
                "chain_sequence_number": len(chain_agent_tasks),
                "session_type": "chain",
                "accumulated_artifacts": accumulated_artifacts,
            }
        except Exception as exc:
            logger.error("Error building chain context: %s", exc, exc_info=True)
            return None

    async def process_agent_task_direct(
        self,
        agent_task: str,
        display_prompt_markdown: Optional[str] = None,
        clarification_agent_task: str = None,
        agent_task_id: str = None,
        root_task_id: str = None,
        previous_task_id: str = None,
        reference_paths: Optional[List[str]] = None,
        model_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        approval_policy_override: Optional[Dict[str, Any]] = None,
        origin_type: Optional[str] = None,
        origin_id: Optional[str] = None,
        todo_workspace_context: Optional[Dict[str, Any]] = None,
        todo_worker_context: Optional[Dict[str, Any]] = None,
        local_preview_feedback: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Capability-named wrapper for delegated task processing."""
        if agent_task is None:
            raise ValueError("process_agent_task_direct requires agent_task")
        return await self._process_agent_task_direct_impl(
            agent_task,
            display_prompt_markdown=display_prompt_markdown,
            clarification_agent_task=clarification_agent_task,
            agent_task_id=agent_task_id,
            root_task_id=root_task_id,
            previous_task_id=previous_task_id,
            reference_paths=reference_paths,
            model_id=model_id,
            conversation_id=conversation_id,
            approval_policy_override=approval_policy_override,
            local_preview_feedback=local_preview_feedback,
            origin_type=origin_type,
            origin_id=origin_id,
            todo_workspace_context=todo_workspace_context,
            todo_worker_context=todo_worker_context,
        )

    async def determine_operation_type(
        self,
        agent_task: str,
        clarification_agent_task: str = None,
        root_task_id: str = None,
        model_id: str = None,
    ) -> str:
        """Decide whether a follow-up can be answered from context alone (the
        fast lane) or must enter the full multi_step_workflow pipeline.

        First-time tasks (no root_task_id) always go to multi_step_workflow --
        there is no conversation context yet to answer from, so no model call
        is made. Follow-ups are routed by evaluate_fast_lane_intent, a genuine
        model judgment call (fast_lane_intent_gate.py) -- there is no
        keyword/substring matching here.
        """
        if not root_task_id:
            return "multi_step_workflow"

        chain_context = await self._build_chain_context(root_task_id)
        chain_agent_tasks = []
        if chain_context:
            chain_agent_tasks = (chain_context.get("accumulated_artifacts") or {}).get("chain_agentTasks") or []
        conversation_history = render_chain_turns_as_conversation(chain_agent_tasks)

        model = await self._resolve_fast_lane_model(model_id)
        decision = await evaluate_fast_lane_intent(model, agent_task, conversation_history)

        if decision.takes_fast_lane:
            logger.info(
                "Follow-up routed to fast lane: confidence=%.2f reason=%r",
                decision.confidence, decision.reason,
            )
            return "discussion"

        logger.info(
            "Follow-up escalated to multi_step_workflow: confidence=%.2f reason=%r",
            decision.confidence, decision.reason,
        )
        return "multi_step_workflow"

    async def handle_discussion_followup(
        self,
        agent_task: str,
        root_task_id: str,
        agent_task_id: str = None,
        previous_task_id: str = None,
        model_id: str = None,
    ) -> Dict[str, Any]:
        """Answer a follow-up directly from conversation context/artifacts, with
        no tool use -- the fast lane. Streams the answer into the result bubble
        via stream_synthesized_final_answer, the same mechanism the main
        pipeline's finalizer synthesis uses, so this reads as a live streamed
        chat reply rather than a spinner-then-blob response.
        """
        cmd_id = agent_task_id or f"disc_{root_task_id[:8]}_{int(time.time())}"
        chain_context = await self._build_chain_context(root_task_id, previous_task_id=previous_task_id)

        chain_agent_tasks = []
        if chain_context:
            chain_agent_tasks = (chain_context.get("accumulated_artifacts") or {}).get("chain_agentTasks") or []

        # Shared with the tool-workflow follow-up path (agent_context_assembler.py)
        # so this fast-lane turn and a workflow follow-up in the same chain
        # render prior turns identically.
        conversation_history = render_chain_turns_as_conversation(chain_agent_tasks)

        resolved_root_task_id = chain_context.get("root_task_id") if chain_context else root_task_id
        resolved_previous_task_id = chain_context.get("previous_task_id") if chain_context else previous_task_id

        # Read-only lookup of the same durable work ledger the full
        # multi_step_workflow pipeline writes to (agent_task_workflow_result_
        # service.py). This does not call ensure_session -- the fast lane does
        # no tool work of its own, so it should never create ledger state,
        # only read whatever a prior full-pipeline turn in this chain already
        # captured. resolve_session(create=False) returns None/"" gracefully
        # when no session exists yet (e.g. an all-discussion chain), so this
        # is safe on every follow-up, not just ledger-backed ones.
        work_ledger_handoff = ""
        try:
            from api.services.agent_processing.lifecycle.runtime.agent_work_ledger_service import (
                AgentWorkLedgerService,
            )

            ledger = AgentWorkLedgerService(self.db_service)
            work_ledger_handoff = await ledger.handoff(
                context={
                    "root_task_id": resolved_root_task_id,
                    "agent_task_id": cmd_id,
                    "user_agent_task": agent_task,
                },
            )
        except Exception as ledger_error:
            logger.warning(
                "Could not read work ledger handoff for fast-lane task %s: %s",
                cmd_id, ledger_error,
            )

        ledger_section = (
            f"===== WORK_LEDGER =====\n{work_ledger_handoff}\n===== END WORK_LEDGER =====\n\n"
            if work_ledger_handoff else ""
        )

        model = await self._resolve_fast_lane_model(model_id)
        response_text = ""
        if model is not None:
            notifier = WorkflowStatusNotifier(
                websocket_manager=getattr(self.agent_task_orchestrator, "websocket_manager", None),
                agent_task_id=cmd_id,
                root_task_id=resolved_root_task_id,
                previous_task_id=resolved_previous_task_id,
            )
            messages = [
                {"role": "system", "content": FAST_LANE_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"{ledger_section}{conversation_history}\n\n"
                        f"User: {agent_task}\n\n"
                        "Respond to the user's latest message:"
                    ),
                },
            ]
            try:
                synthesis = await stream_synthesized_final_answer(
                    llm_model=model,
                    messages=messages,
                    stream_notifier=notifier,
                    stream_source="fast_lane",
                    operation="discussion",
                )
                response_text = synthesis.text
            except Exception as exc:
                logger.error("Fast-lane response generation failed: %s", exc, exc_info=True)

        generation_succeeded = bool(response_text)
        if not response_text:
            response_text = "I wasn't able to generate a response just now -- please try again."

        # Mirror the full pipeline's result_payload.outcome contract (see
        # result_finalizer_tool.py's docstring) so list/detail views that read
        # `outcome` render the same way regardless of which lane answered the
        # turn -- the fast lane has no tool execution to evaluate, so success
        # here just tracks whether generation itself produced real content.
        outcome = "success" if generation_succeeded else "failure"
        outcome_reason = None if generation_succeeded else (
            "The fast-lane response generation failed; please try again."
        )

        try:
            await self.db_service.store_agent_task(
                agent_task_id=cmd_id,
                original_prompt=agent_task,
                transcribed_prompt=agent_task,
                status="completed",
                root_task_id=resolved_root_task_id,
                previous_task_id=resolved_previous_task_id,
                chain_sequence_number=chain_context.get("chain_sequence_number", 0) if chain_context else 0,
                session_type=chain_context.get("session_type") if chain_context else "chain",
            )
            await self.db_service.update_agent_task_status(
                agent_task_id=cmd_id,
                status="completed",
                result_data={
                    "success": generation_succeeded,
                    "operation_type": "discussion",
                    "response": response_text,
                    "finalizer_result": {
                        "success": generation_succeeded,
                        "summary_text": response_text,
                        "result_payload": {
                            "files": [],
                            "result_type": "discussion",
                            "outcome": outcome,
                            "outcome_reason": outcome_reason,
                        },
                    },
                },
            )
        except Exception as exc:
            logger.warning("Failed to persist discussion entry: %s", exc)

        await self.broadcast(
            {
                "event_type": "agent_task_result",
                "agent_task_id": cmd_id,
                "root_task_id": resolved_root_task_id,
                "previous_task_id": resolved_previous_task_id,
                "success": generation_succeeded,
                "result": response_text,
                "operation": "discussion",
                "timestamp": datetime.now().isoformat(),
            }
        )

        return {
            "success": generation_succeeded,
            "operation": "discussion",
            "confidence": 1.0,
            "reasoning": "Fast-lane follow-up handled directly from context",
            "message": response_text,
            "processing_time": 0.0,
            "agent_task_id": cmd_id,
        }

    async def _resolve_fast_lane_model(self, model_id: str = None):
        """Resolve the fast-lane model through an overridable service seam."""
        return await resolve_fast_lane_reasoning_model(model_id)

    async def add_clarification(self, agent_task_id: str, clarification_text: str) -> Dict[str, Any]:
        """Add clarification to an existing agent task."""
        try:
            return await self.agent_task_orchestrator.add_clarification(
                agent_task_id=agent_task_id,
                clarification_text=clarification_text,
            )
        except Exception as exc:
            logger.error("Error adding clarification: %s", exc, exc_info=True)
            return {
                "success": False,
                "agent_task_id": agent_task_id,
                "error": str(exc),
                "message": "Failed to process clarification. Please try again.",
            }

    async def cancel_agent_task_durably(
        self,
        agent_task_id: str,
        reason: str,
    ) -> Dict[str, Any]:
        """Cancel active work in a task chain and persist its terminal state."""
        agent_task_id = (agent_task_id or "").strip()
        if not agent_task_id:
            raise ValueError("agent_task_id is required for durable cancellation")

        runtime_preempted = False
        if self.agent_task_orchestrator and hasattr(
            self.agent_task_orchestrator,
            "request_agent_task_preemption",
        ):
            runtime_preempted = self.agent_task_orchestrator.request_agent_task_preemption(
                agent_task_id
            )
        preemption_completed_at = time.perf_counter()

        agent_task_record = await self.db_service.get_agent_task(agent_task_id)
        if agent_task_record is None:
            # The result widget registers its UUID before capture/transcription
            # creates the durable row. Treat cancellation during that interval
            # as a valid preemptive tombstone: the orchestrator registry retains
            # the ID, so later routing/processing checks skip work even if the
            # row is persisted immediately after this request.
            durable_completed_at = preemption_completed_at
            runtime_cancelled = await self.cancel_current_agent_task(
                agent_task_id=agent_task_id,
            )
            cleanup_completed_at = time.perf_counter()
            logger.info(
                "🛑 Registered provisional cancellation before persistence: "
                "agent_task_id=%s runtime_cancelled=%s",
                agent_task_id,
                runtime_cancelled,
            )
            return {
                "root_task_id": agent_task_id,
                "cancelled_task_ids": [agent_task_id],
                "runtime_cancelled": runtime_cancelled or runtime_preempted,
                "preemption_completed_at": preemption_completed_at,
                "durable_completed_at": durable_completed_at,
                "cleanup_completed_at": cleanup_completed_at,
            }

        root_task_id = agent_task_record.root_task_id or agent_task_record.id
        chain = await self.db_service.get_agent_task_chain(root_task_id)
        if not chain:
            chain = [agent_task_record]

        active_statuses = {
            "capturing",
            "routing",
            "processing",
            "awaiting_user_input",
            "awaiting_provider_delegation",
            "awaiting_delegated_agents",
            "paused",
        }
        cancellation_payload = {
            "cancelled": True,
            "cancellation_reason": reason,
            "cancelled_at": datetime.utcnow().isoformat(),
        }
        active_task_ids = [
            task.id for task in chain if task.status in active_statuses
        ]
        if hasattr(self.db_service, "cancel_agent_tasks_if_active"):
            cancelled_task_ids = await self.db_service.cancel_agent_tasks_if_active(
                agent_task_ids=active_task_ids,
                result_data=cancellation_payload,
            )
        else:
            cancelled_task_ids = []
            for active_task_id in active_task_ids:
                await self.db_service.update_agent_task_status(
                    agent_task_id=active_task_id,
                    status="cancelled",
                    result_data=cancellation_payload,
                )
                cancelled_task_ids.append(active_task_id)
        durable_completed_at = time.perf_counter()

        runtime_cancelled = await self.cancel_current_agent_task(
            agent_task_id=root_task_id,
        )
        cleanup_completed_at = time.perf_counter()

        orchestrator_broadcast_available = bool(
            getattr(self.agent_task_orchestrator, "websocket_manager", None)
        )
        if not orchestrator_broadcast_available:
            for cancelled_task_id in cancelled_task_ids:
                await self.broadcast(
                    {
                        "event_type": "agent_task_cancelled",
                        "agent_task_id": cancelled_task_id,
                        "root_task_id": root_task_id,
                        "message": "AgentTask cancelled",
                    }
                )

        return {
            "root_task_id": root_task_id,
            "cancelled_task_ids": cancelled_task_ids,
            "runtime_cancelled": runtime_cancelled or runtime_preempted,
            "preemption_completed_at": preemption_completed_at,
            "durable_completed_at": durable_completed_at,
            "cleanup_completed_at": cleanup_completed_at,
        }

    async def cancel_current_agent_task(self, agent_task_id: str = None):
        """Cancel agent-task processing, scoped to an agent task when an ID is provided."""
        if agent_task_id:
            agent_task_id = agent_task_id.strip()
            if not agent_task_id:
                logger.warning("Received empty agent_task_id for scoped cancel")
                return False
            if self.agent_task_orchestrator and hasattr(self.agent_task_orchestrator, "cancel_agent_task"):
                return await self.agent_task_orchestrator.cancel_agent_task(agent_task_id)
            logger.warning("Orchestrator not available for scoped cancel")
            return False

        self._last_cancel_timestamp = time.time()
        try:
            from api.services.agent_task_streaming import cleanup_all_streaming_sessions

            cleanup_all_streaming_sessions()
        except Exception as exc:
            logger.error("Error terminating streaming sessions: %s", exc)

        if self.agent_task_orchestrator and hasattr(self.agent_task_orchestrator, "cancel_current_processing"):
            try:
                await asyncio.wait_for(self.agent_task_orchestrator.cancel_current_processing(), timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning("Agent-task orchestrator cancellation timed out")
            except Exception as exc:
                logger.error("Error cancelling agent-task orchestrator: %s", exc)

        if self.wake_word_service and hasattr(self.wake_word_service, "reset_agent_task_capture_after_cancel"):
            self.wake_word_service.reset_agent_task_capture_after_cancel()
        return True

    def set_current_screenshot_data(self, screenshot_data: Dict[str, Any]) -> None:
        """Set pre-captured screenshot data for agent-task processing."""
        self._current_screenshot_data = screenshot_data
        if screenshot_data and screenshot_data.get("success"):
            logger.info("Screenshot data stored for agent-task submission: %s", screenshot_data.get("app_name", "Unknown"))
        else:
            logger.info("Screenshot data cleared for agent-task submission")

    def get_current_screenshot_data(self) -> Optional[Dict[str, Any]]:
        """Get screenshot data captured before submission."""
        return self._current_screenshot_data
