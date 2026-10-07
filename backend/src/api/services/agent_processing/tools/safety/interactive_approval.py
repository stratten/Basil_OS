"""
Interactive command approval via WebSocket.

Manages user approval prompts and responses for command execution.
"""

import asyncio
import logging
import time
from typing import Dict, Any, Tuple

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.execution_approvals.repository import (
    ExecutionApprovalConflictError,
    ExecutionApprovalPersistenceError,
)
from api.core.models.preferences import ApprovalTimeoutBehavior
from api.services.agent_processing.lifecycle.runtime.timeline_persistence import persist_timeline_entry
from api.services.agent_processing.lifecycle.runtime.user_interaction_timeline import (
    record_user_interaction_asked,
    record_user_interaction_resolved,
)
from api.services.agent_processing.shared.workflow_budget_pause import pause_workflow_budget
from api.services.conversation.conversation_agent_turn_lifecycle import (
    clear_conversation_agent_attention,
    publish_conversation_agent_attention,
)

from .approval_override import resolve_tool_execution_settings
from .models import ExecutionApprovalDecision

logger = logging.getLogger(__name__)


class InteractiveApprovalManager:
    """
    Manages interactive approval flow via WebSocket.

    Handles approval requests, user responses, and maintains state of
    pending approvals across service instances.
    """

    _pending_approvals: Dict[str, asyncio.Future] = {}
    _processing_approvals: set = set()

    def __init__(self, websocket_manager, generalizer):
        self.websocket_manager = websocket_manager
        self.generalizer = generalizer

    async def request_approval(
        self,
        command: str,
        decision: ExecutionApprovalDecision,
        context: Dict[str, Any],
    ) -> Tuple[bool, bool, str]:
        """Request user approval for a command via WebSocket and wait for response."""
        agent_task_id = context.get("agent_task_id")
        if not isinstance(agent_task_id, str) or not agent_task_id.strip():
            logger.error("Execution approval requested without a durable agent_task_id")
            return (False, False, "approval_unavailable")

        agent_task_id = agent_task_id.strip()
        root_task_id = context.get("root_task_id") or agent_task_id
        if not isinstance(root_task_id, str) or not root_task_id.strip():
            root_task_id = agent_task_id

        approval_id: str | None = None
        future: asyncio.Future | None = None
        persisted_revision = 0

        try:
            generalized_pattern = self.generalizer.generalize_command(command)

            from .risk_assessment import RiskAssessor

            risk_assessor = RiskAssessor()
            risk_metadata = risk_assessor.get_risk_metadata(command)

            render_context = {
                "cwd": context.get("cwd"),
                "source": context.get("source", "shell_service"),
                "description": context.get(
                    "description",
                    "Command requires approval before execution",
                ),
                "risk_metadata": risk_metadata,
            }
            execution_type = context.get("execution_type", "shell")
            script_content = context.get("script_content")

            from api.dependencies import get_sqlite_knowledge_service

            knowledge_service = get_sqlite_knowledge_service()
            try:
                persisted = await knowledge_service.execution_approval_repository.create_pending_approval(
                    agent_task_id=agent_task_id,
                    root_task_id=root_task_id.strip(),
                    execution_type=execution_type,
                    command=command,
                    reason=decision.reason,
                    risk_level=decision.risk_level,
                    generalized_pattern=generalized_pattern,
                    render_context=render_context,
                    script_content=script_content if isinstance(script_content, str) else None,
                )
                approval_id = str(persisted["id"])
                persisted_revision = int(persisted["revision"])
            except (ExecutionApprovalConflictError, ExecutionApprovalPersistenceError) as exc:
                logger.error("Failed to persist execution approval for %s: %s", agent_task_id, exc)
                return (False, False, "approval_unavailable")
            except Exception:
                logger.exception("Failed to persist execution approval for %s", agent_task_id)
                return (False, False, "approval_unavailable")

            future = asyncio.Future()
            InteractiveApprovalManager._pending_approvals[approval_id] = future

            try:
                await persist_timeline_entry(
                    agent_task_id,
                    {
                        "id": f"approval-wait-{approval_id}",
                        "type": "activity",
                        "title": "Waiting for your approval",
                        "phase": "approval_waiting",
                        "state": "waiting",
                        "timestamp": time.time(),
                    },
                )
            except Exception:
                logger.exception("Failed to persist approval-wait activity for %s", approval_id)
                try:
                    await knowledge_service.execution_approval_repository.cancel_pending_approval(
                        approval_id=approval_id,
                        expected_revision=persisted_revision,
                    )
                except Exception:
                    logger.exception(
                        "Failed to cancel execution approval %s after timeline persistence failure",
                        approval_id,
                    )
                return (False, False, "approval_unavailable")

            await record_user_interaction_asked(
                agent_task_id,
                interaction_id=approval_id,
                kind="approval",
                prompt=command,
                input_type=execution_type,
                broadcast=self.websocket_manager.broadcast,
            )

            try:
                await publish_conversation_agent_attention(agent_task_id, approval_id)
            except Exception:
                logger.exception(
                    "Failed to project execution approval attention for %s",
                    approval_id,
                )

            approval_event: Dict[str, Any] = {
                "event_type": "execution_approval_request",
                "approval_id": approval_id,
                "command": command,
                "reason": decision.reason,
                "risk_level": decision.risk_level,
                "generalized_pattern": generalized_pattern,
                "context": {
                    "cwd": render_context.get("cwd"),
                    "source": render_context.get("source"),
                    "description": render_context.get("description"),
                },
                "options": {
                    "risk_level": decision.risk_level,
                    "reason": decision.reason,
                    "show_remember": True,
                },
                "risk_metadata": risk_metadata,
                "revision": persisted_revision,
                "agent_task_id": agent_task_id,
                "execution_type": execution_type,
            }
            if script_content:
                approval_event["script_content"] = script_content

            try:
                await self.websocket_manager.broadcast(approval_event)
            except Exception as exc:
                logger.error("Failed to broadcast execution approval %s: %s", approval_id, exc)
                try:
                    await knowledge_service.execution_approval_repository.cancel_pending_approval(
                        approval_id=approval_id,
                        expected_revision=persisted_revision,
                    )
                except Exception:
                    logger.exception("Failed to cancel durable approval after broadcast failure")
                try:
                    await clear_conversation_agent_attention(agent_task_id, approval_id)
                except Exception:
                    logger.exception(
                        "Failed to clear execution approval attention after broadcast failure for %s",
                        approval_id,
                    )
                if approval_id in InteractiveApprovalManager._pending_approvals:
                    pending = InteractiveApprovalManager._pending_approvals.pop(approval_id)
                    if not pending.done():
                        pending.cancel()
                return (False, False, "approval_unavailable")

            logger.info("Sent command approval request: %s for command: %s", approval_id, command)
            logger.info("Generalized pattern for whitelisting: %s", generalized_pattern)

            _exec_settings = resolve_tool_execution_settings(context)
            _timeout_seconds = _exec_settings.approval_timeout_seconds
            _timeout_behavior = _exec_settings.timeout_behavior

            try:
                logger.info(
                    "Waiting for approval response for: %s (timeout_behavior=%s, timeout=%ss)",
                    approval_id,
                    _timeout_behavior.value,
                    _timeout_seconds,
                )
                wait_start = time.time()

                with pause_workflow_budget("execution_approval"):
                    if _timeout_behavior == ApprovalTimeoutBehavior.WAIT_FOREVER:
                        result = await future
                    else:
                        result = await asyncio.wait_for(future, timeout=float(_timeout_seconds))

                wait_duration = time.time() - wait_start
                logger.info("Received approval response after %.2fs: %s", wait_duration, type(result))
                logger.info("Approval tuple: approved=%s", result[0] if result else "N/A")

                return result

            except asyncio.TimeoutError:
                logger.warning(
                    "Command approval timed out after %ss: %s",
                    _timeout_seconds,
                    approval_id,
                )
                try:
                    await knowledge_service.execution_approval_repository.cancel_pending_approval(
                        approval_id=approval_id,
                        expected_revision=persisted_revision,
                    )
                except ExecutionApprovalConflictError:
                    logger.info("Approval %s was resolved while its timeout was expiring", approval_id)
                await record_user_interaction_resolved(
                    agent_task_id,
                    interaction_id=approval_id,
                    status="timed_out",
                    broadcast=self.websocket_manager.broadcast,
                )
                try:
                    await clear_conversation_agent_attention(agent_task_id, approval_id)
                except Exception:
                    logger.exception(
                        "Failed to clear execution approval attention after timeout for %s",
                        approval_id,
                    )
                if _timeout_behavior == ApprovalTimeoutBehavior.RETRY_ALTERNATIVE:
                    return (False, False, "timeout_retry_hint")
                return (False, False, "timeout_denied")

            except asyncio.CancelledError:
                # Either the surrounding task is being canceled (re-raise after cleanup) or the durable approval was retired by cancel/retry, which cancels only this future (report it as unavailable instead of leaking CancelledError out of a task nobody canceled).
                current_task = asyncio.current_task()
                task_is_canceling = bool(current_task is not None and current_task.cancelling())
                try:
                    await knowledge_service.execution_approval_repository.cancel_pending_approval(
                        approval_id=approval_id,
                        expected_revision=persisted_revision,
                    )
                except Exception:
                    logger.info(
                        "Approval %s was already resolved or retired when its waiter was interrupted",
                        approval_id,
                    )
                try:
                    await clear_conversation_agent_attention(agent_task_id, approval_id)
                except Exception:
                    logger.exception(
                        "Failed to clear execution approval attention after interruption for %s",
                        approval_id,
                    )
                resolution = record_user_interaction_resolved(
                    agent_task_id,
                    interaction_id=approval_id,
                    status="canceled",
                    broadcast=self.websocket_manager.broadcast,
                )
                if task_is_canceling:
                    # The run is ending; the waiting card must not outlive it, so the resolution is shielded from the cancellation that is unwinding this task.
                    try:
                        await asyncio.shield(resolution)
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        logger.exception("Failed to record canceled interaction for %s", approval_id)
                    raise
                await resolution
                logger.info("Approval %s was retired while waiting; reporting it as unavailable", approval_id)
                return (False, False, "approval_unavailable")

        finally:
            if approval_id and approval_id in InteractiveApprovalManager._pending_approvals:
                del InteractiveApprovalManager._pending_approvals[approval_id]

    async def handle_approval_response(
        self,
        approval_id: str,
        approved: bool,
        remember: bool = False,
        pattern_type: str = "exact",
        *,
        agent_task_id: str | None = None,
        expected_revision: int | None = None,
    ) -> None:
        """Process user's approval response from frontend."""
        handler_start = time.time()
        logger.info(
            "handle_approval_response called: approval_id=%s, approved=%s, remember=%s",
            approval_id,
            approved,
            remember,
        )

        if approval_id in InteractiveApprovalManager._processing_approvals:
            logger.warning("Approval %s is already being processed, ignoring duplicate request", approval_id)
            return

        from api.dependencies import get_sqlite_knowledge_service

        knowledge_service = get_sqlite_knowledge_service()
        durable_record = await knowledge_service.execution_approval_repository.get_approval(approval_id)
        if durable_record is None:
            raise ExecutionApprovalConflictError(
                f"execution approval {approval_id!r} is not pending"
            )
        if durable_record["status"] != "pending":
            raise ExecutionApprovalConflictError(
                f"execution approval {approval_id!r} is not pending "
                f"(status={durable_record['status']!r})"
            )

        task_id = str(durable_record["agent_task_id"])
        if agent_task_id and durable_record["agent_task_id"] != agent_task_id:
            raise ExecutionApprovalConflictError(
                f"execution approval {approval_id!r} does not belong to agent task {agent_task_id!r}"
            )
        revision = expected_revision if expected_revision is not None else int(durable_record["revision"])
        future = InteractiveApprovalManager._pending_approvals.get(approval_id)
        if future is None or future.done():
            raise ExecutionApprovalConflictError(
                f"execution approval {approval_id!r} is not active in this process"
            )

        InteractiveApprovalManager._processing_approvals.add(approval_id)
        try:
            await knowledge_service.execution_approval_repository.resolve_pending_approval(
                approval_id=approval_id,
                agent_task_id=task_id,
                expected_revision=revision,
                approved=approved,
                remember_choice=remember,
                pattern_type=pattern_type,
            )
            try:
                await clear_conversation_agent_attention(task_id, approval_id)
            except Exception:
                logger.exception(
                    "Failed to clear execution approval attention for %s",
                    approval_id,
                )

            await persist_timeline_entry(
                task_id,
                {
                    "id": (
                        f"approval-granted-{approval_id}"
                        if approved
                        else f"approval-denied-{approval_id}"
                    ),
                    "type": "activity",
                    "title": "Approval granted" if approved else "Approval denied",
                    "phase": "approval_waiting",
                    "state": "completed" if approved else "failed",
                    "timestamp": time.time(),
                },
            )
            await record_user_interaction_resolved(
                task_id,
                interaction_id=approval_id,
                status="approved" if approved else "denied",
                broadcast=self.websocket_manager.broadcast,
            )
            if not future.done():
                future.set_result((approved, remember, pattern_type))
        finally:
            InteractiveApprovalManager._processing_approvals.discard(approval_id)

        handler_duration = time.time() - handler_start
        logger.info("handle_approval_response completed in %.2fs total", handler_duration)

    @classmethod
    def cancel_pending_future(cls, approval_id: str) -> bool:
        """Stop the local waiter after its durable approval was retired."""
        future = cls._pending_approvals.pop(approval_id, None)
        if future is None:
            return False
        if not future.done():
            future.cancel()
        return True

    @classmethod
    def has_pending_future(cls, approval_id: str) -> bool:
        future = cls._pending_approvals.get(approval_id)
        return future is not None and not future.done()
