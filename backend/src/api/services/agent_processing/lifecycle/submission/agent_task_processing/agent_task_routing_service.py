"""Routing and progress helpers for AgentTask processing."""

from __future__ import annotations

import asyncio
import logging
import re
from types import SimpleNamespace
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from api.services.agent_processing.lifecycle.delegation.delegated_agent_evidence_service import (
    DelegatedAgentEvidenceService,
)
from ...runtime.agent_timeline_contract import normalize_timeline_entry


def plain_agent_task_title(response: str) -> str:
    """Reduce a model's title reply to its first line of plain text, without markdown or a "Title:" prefix."""
    first_line = next((line for line in response.splitlines() if line.strip()), "")
    title = re.sub(r"^\s{0,3}(?:#{1,6}\s+|[-+*]\s+|\d+[.)]\s+|>\s?)", "", first_line)
    title = re.sub(r"(\*\*|__|~~|`+)", "", title)
    title = re.sub(r"(^|[^\w])[*_](\S(?:.*?\S)?)[*_](?!\w)", r"\1\2", title)
    title = re.sub(r"^\s*title\s*:\s*", "", title, flags=re.IGNORECASE)
    return title.strip().strip('"').strip("'").strip()

class AgentTaskRoutingService:
    """Routes AgentTasks into the canonical workflow and emits progress."""

    def __init__(
        self,
        *,
        db_service: Any,
        websocket_manager: Any = None,
        is_canceled: Optional[Callable[[str], bool]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.db_service = db_service
        self.websocket_manager = websocket_manager
        self._is_canceled = is_canceled or (lambda _agent_task_id: False)
        self.logger = logger or logging.getLogger(__name__)
        self._provider_delegation_result_bridge: Any | None = None

    def set_provider_delegation_result_bridge(self, bridge: Any) -> None:
        """Attach the concrete bridge after its routing dependency is constructed."""
        self._provider_delegation_result_bridge = bridge

    async def publish_delegated_provider_state(
        self,
        *,
        parent_agent_task_id: str,
        root_task_id: str,
        delegation_id: str,
        state: str,
        message: str,
        interaction_id: str | None = None,
    ) -> bool:
        """Persist and broadcast one bounded delegated-child projection on its parent."""
        published = await self.publish_activity_entry(
            agent_task_id=parent_agent_task_id,
            root_task_id=root_task_id,
            previous_task_id=None,
            entry={
                "id": f"provider_delegation_{delegation_id}_{state}_{interaction_id or 'state'}",
                "type": "provider_delegation",
                "content": message,
                "summary": "Delegated provider task",
                "body": message,
                "detail_kind": "provider_status",
                "state": state,
                "metadata": {
                    "delegation_id": delegation_id,
                    "interaction_id": interaction_id,
                    "projected_from_child": True,
                },
            },
        )
        if published:
            await self.publish_delegated_provider_report_cards(
                parent_agent_task_id=parent_agent_task_id,
                root_task_id=root_task_id,
            )
        return published

    async def _build_delegated_provider_report_cards(
        self, parent_agent_task_id: str
    ) -> dict[str, object]:
        runs = getattr(self.db_service, "delegated_agent_repository", None)
        evidence = getattr(self.db_service, "delegated_agent_evidence_repository", None)
        if runs is None or evidence is None:
            return {"items": []}
        try:
            items = await DelegatedAgentEvidenceService(
                delegated_agent_repository=runs,
                evidence_repository=evidence,
            ).build_parent_report_cards(parent_agent_task_id=parent_agent_task_id)
        except Exception as exc:  # noqa: BLE001 - display reads must not interrupt provider work.
            self.logger.debug(
                "Delegated provider report-card projection failed for %s: %s",
                parent_agent_task_id,
                exc.__class__.__name__,
            )
            return {"items": []}
        return {"items": items}

    async def publish_delegated_provider_report_cards(
        self,
        *,
        parent_agent_task_id: str,
        root_task_id: str,
    ) -> bool:
        """Broadcast an additive, durable delegated-provider card snapshot."""
        return await self.broadcast_agent_task_message(
            parent_agent_task_id,
            {
                "event_type": "delegated_provider_report_cards",
                "agent_task_id": parent_agent_task_id,
                "root_task_id": root_task_id,
                "delegated_provider_report_cards": {
                    "parent_agent_task_id": parent_agent_task_id,
                    **await self._build_delegated_provider_report_cards(parent_agent_task_id),
                },
            },
        )

    async def perform_routing(self, agent_task_id: str) -> None:
        """Route an AgentTask directly to the canonical multi-step workflow."""
        try:
            if self._is_canceled(agent_task_id):
                self.logger.info("🛑 Skipping routing for canceled agent_task: %s", agent_task_id)
                return

            agent_task_record = await self.db_service.get_agent_task(agent_task_id)
            if not agent_task_record:
                self.logger.error("AgentTask %s not found for routing", agent_task_id)
                return

            self.logger.info("Routing agent_task: %s", agent_task_record.transcribed_prompt)
            root_task_id = getattr(agent_task_record, "root_task_id", None)
            previous_task_id = getattr(agent_task_record, "previous_task_id", None)
            await self.send_progress_update(
                "Analyzing request",
                "started",
                agent_task_record.transcribed_prompt,
                agent_task_id,
                root_task_id=root_task_id,
                previous_task_id=previous_task_id,
            )
            await self.send_progress_update(
                "Analyzing request",
                "completed",
                agent_task_id=agent_task_id,
                root_task_id=root_task_id,
                previous_task_id=previous_task_id,
            )
            await self.send_progress_update(
                "Determining operation",
                "started",
                agent_task_id=agent_task_id,
                root_task_id=root_task_id,
                previous_task_id=previous_task_id,
            )

            provider_target = None
            if isinstance(agent_task_record.accumulated_artifacts, dict):
                candidate = agent_task_record.accumulated_artifacts.get("provider_target")
                if isinstance(candidate, dict) and candidate.get("provider_profile_id") and candidate.get("workspace_grant_id"):
                    provider_target = candidate

            if provider_target is not None:
                operation = "provider_run"
                parameters = {"provider_target": provider_target}
            else:
                operation = "multi_step_workflow"
                parameters = {"workflow_type": "general", "action": "dynamic_execution"}

            await self.send_progress_update(
                "Determining operation",
                "completed",
                agent_task_id=agent_task_id,
                root_task_id=root_task_id,
                previous_task_id=previous_task_id,
            )
            await self.db_service.update_agent_task_status(
                agent_task_id=agent_task_id,
                status="processing",
                operation_parameters={
                    "operation": operation,
                    "confidence": 1.0,
                    "reasoning": "Direct routing to agent - agent handles all agent tasks",
                    "parameters": parameters,
                },
            )
            self.logger.info("AgentTask %s successfully routed to: %s", agent_task_id, operation)

        except Exception as exc:
            self.logger.error("Error routing agent_task %s: %s", agent_task_id, exc, exc_info=True)
            await self.db_service.update_agent_task_status(
                agent_task_id=agent_task_id,
                status="failed",
                result_data={"error": str(exc)},
            )

    def build_routing_request(self, agent_task_record: Any):
        """Build the workflow execution request from AgentTask data."""
        reference_paths = None
        model_id = None
        conversation_id = None
        todo_worker_context = None
        retry_context = None
        if agent_task_record.accumulated_artifacts and isinstance(agent_task_record.accumulated_artifacts, dict):
            reference_paths = agent_task_record.accumulated_artifacts.get("reference_paths")
            model_id = agent_task_record.accumulated_artifacts.get("model_id")
            conversation_id = agent_task_record.accumulated_artifacts.get("conversation_id")
            todo_worker_context = agent_task_record.accumulated_artifacts.get(
                "todo_worker_context"
            )
        if agent_task_record.result_data and isinstance(agent_task_record.result_data, dict):
            retry_context = agent_task_record.result_data.get("retry_context")

        request = SimpleNamespace(
            agent_task=agent_task_record.transcribed_prompt,
            active_app=agent_task_record.app_name or "Unknown",
            screen_text=(agent_task_record.screen_text or "")[:1000],
            clarification_agent_task=None,
            root_task_id=agent_task_record.root_task_id,
            previous_task_id=agent_task_record.previous_task_id,
            reference_paths=reference_paths,
            model_id=model_id,
            conversation_id=conversation_id,
            todo_worker_context=todo_worker_context,
            retry_context=retry_context,
            workflow_wallclock_limit_seconds=1500,
        )
        request.full_screen_text = agent_task_record.screen_text or ""
        request.agent_task_id = agent_task_record.id
        return request

    async def persist_progress_update(
        self,
        agent_task_id: str,
        step: str,
        status: str,
        details: str = None,
    ) -> Dict[str, Any]:
        """Store visible progress so late-joining result widgets can replay it."""
        timeline_entry = normalize_timeline_entry(
            {
                "id": f"progress_{''.join(ch.lower() if ch.isalnum() else '_' for ch in step).strip('_')}_{status}",
                "type": "step",
                "content": details or step,
                "detail_kind": "step_complete" if status == "completed" else "step_note",
                "summary": step,
                "body": details or step,
                "metadata": {"progress_step": step, "status": status},
                "streaming": False,
            },
            phase="routing",
            state=status,
            source="agent_task_routing",
            title=step,
            correlation_id=agent_task_id,
        )
        try:
            agent_task_record = await self.db_service.get_agent_task(agent_task_id)
            if not agent_task_record:
                return timeline_entry

            timeline = list(agent_task_record.execution_timeline or [])
            timeline = [entry for entry in timeline if entry.get("id") != timeline_entry["id"]]
            timeline.append(timeline_entry)
            await self.db_service.agent_task_service._mutations.update_execution_timeline(agent_task_id, timeline)
        except Exception as exc:
            self.logger.debug("Failed to persist progress update for %s: %s", agent_task_id, exc)
        return timeline_entry

    async def send_progress_update(
        self,
        step: str,
        status: str,
        details: str = None,
        agent_task_id: str = None,
        root_task_id: str = None,
        previous_task_id: str = None,
    ) -> None:
        """Send progress update to WebSocket clients."""
        timeline_entry = normalize_timeline_entry(
            {
                "type": "step",
                "content": details or step,
                "summary": step,
                "body": details or step,
                "metadata": {"progress_step": step, "status": status},
            },
            phase="routing",
            state=status,
            source="agent_task_routing",
            title=step,
            correlation_id=agent_task_id,
        )
        if agent_task_id:
            timeline_entry = await self.persist_progress_update(agent_task_id, step, status, details)

        if not self.websocket_manager:
            return

        try:
            message = {
                "event_type": "agent_task_progress",
                "step": step,
                "status": status,
                "details": details,
                "timeline_entry": timeline_entry,
            }
            if agent_task_id:
                message["agent_task_id"] = agent_task_id
            if root_task_id:
                message["root_task_id"] = root_task_id
            if previous_task_id:
                message["previous_task_id"] = previous_task_id
            sent = await self.broadcast_agent_task_message(agent_task_id, message)
            if sent:
                self.logger.debug("Sent progress update: %s - %s (agent_task_id=%s)", step, status, agent_task_id)
        except Exception as exc:
            self.logger.error("Failed to send progress update: %s", exc)

    async def publish_activity_entry(
        self,
        *,
        agent_task_id: str,
        root_task_id: str | None,
        previous_task_id: str | None,
        entry: Mapping[str, Any],
    ) -> bool:
        """Persist and broadcast one provider-activity timeline entry.

        Returns False without persisting or broadcasting when the Agent Task
        is absent or already terminal (`completed`, `failed`, `canceled`),
        so late provider noise cannot revive a finished task. This is the
        sole publication path used by `ProviderActivityProjector`; it never
        touches `send_progress_update`'s behavior.
        """
        try:
            agent_task_record = await self.db_service.get_agent_task(agent_task_id)
            if not agent_task_record or agent_task_record.status in ("completed", "failed", "canceled"):
                return False

            timeline_entry = normalize_timeline_entry(
                dict(entry),
                phase="provider",
                source="provider_activity",
                correlation_id=agent_task_id,
            )
            entry_id = timeline_entry.get("id")
            timeline = list(agent_task_record.execution_timeline or [])
            replaced = False
            if entry_id:
                for index, existing in enumerate(timeline):
                    if existing.get("id") == entry_id:
                        timeline[index] = timeline_entry
                        replaced = True
                        break
            if not replaced:
                timeline.append(timeline_entry)
            persisted = await self.db_service.agent_task_service._mutations.update_execution_timeline_if_active(
                agent_task_id, timeline
            )
            if not persisted:
                return False

            if not self.websocket_manager:
                return True

            message: Dict[str, Any] = {
                "event_type": "agent_task_progress",
                "status": timeline_entry.get("state", "in_progress"),
                "timeline_entry": timeline_entry,
                "agent_task_id": agent_task_id,
            }
            if root_task_id:
                message["root_task_id"] = root_task_id
            if previous_task_id:
                message["previous_task_id"] = previous_task_id
            await self.broadcast_agent_task_message(agent_task_id, message)
            return True
        except Exception as exc:
            self.logger.debug(
                "Failed to publish provider activity entry for %s: %s",
                agent_task_id,
                exc.__class__.__name__,
            )
            return False

    async def publish_provider_interaction_request(
        self,
        *,
        agent_task_id: str,
        root_task_id: str | None,
        previous_task_id: str | None,
        interaction_id: str,
        provider_run_id: str,
        message: str,
        fields: Sequence[Mapping[str, Any]],
    ) -> bool:
        """Broadcast a provider elicitation request through the existing checkpoint channel.

        Reuses the `collaborative_checkpoint_request` event type so the
        existing `CheckpointFlow` presentation surface renders it with zero
        new WebSocket event types. Returns False without broadcasting when
        the Agent Task is absent or already terminal.
        """
        try:
            agent_task_record = await self.db_service.get_agent_task(agent_task_id)
            if not agent_task_record or agent_task_record.status in ("completed", "failed", "canceled"):
                return False
            from api.services.conversation.conversation_agent_turn_lifecycle import (
                publish_conversation_agent_attention,
            )

            await publish_conversation_agent_attention(agent_task_id, interaction_id)
            if not self.websocket_manager:
                return True

            checkpoint = {
                "checkpoint_id": interaction_id,
                "prompt": message,
                "input_type": "provider_form",
                "fields": [dict(field) for field in fields],
                "metadata": {
                    "source": "provider_user_input",
                    "provider_run_id": provider_run_id,
                },
            }
            message_payload: Dict[str, Any] = {
                "event_type": "collaborative_checkpoint_request",
                "agent_task_id": agent_task_id,
                "checkpoint": checkpoint,
            }
            if root_task_id:
                message_payload["root_task_id"] = root_task_id
            if previous_task_id:
                message_payload["previous_task_id"] = previous_task_id
            await self.broadcast_agent_task_message(agent_task_id, message_payload)
            return True
        except Exception as exc:
            self.logger.debug(
                "Failed to publish provider interaction request for %s: %s",
                agent_task_id,
                exc.__class__.__name__,
            )
            return False

    async def publish_provider_interaction_resolved(
        self,
        *,
        agent_task_id: str,
        root_task_id: str | None,
        previous_task_id: str | None,
        interaction_id: str,
    ) -> bool:
        """Clear delegated attention and broadcast a provider-form continuation."""
        try:
            from api.services.conversation.conversation_agent_turn_lifecycle import (
                clear_conversation_agent_attention,
            )

            await clear_conversation_agent_attention(agent_task_id, interaction_id)
            if not self.websocket_manager:
                return True
            message_payload: Dict[str, Any] = {
                "event_type": "checkpoint_resumed",
                "agent_task_id": agent_task_id,
                "message": "Resumed",
            }
            if root_task_id:
                message_payload["root_task_id"] = root_task_id
            if previous_task_id:
                message_payload["previous_task_id"] = previous_task_id
            await self.broadcast_agent_task_message(agent_task_id, message_payload)
            return True
        except Exception as exc:
            self.logger.debug(
                "Failed to publish provider interaction resolution for %s: %s",
                agent_task_id,
                exc.__class__.__name__,
            )
            return False

    async def publish_provider_permission_resolved(
        self,
        *,
        agent_task_id: str,
        root_task_id: str | None,
        previous_task_id: str | None,
        interaction_id: str,
    ) -> bool:
        """Clear delegated attention after a provider permission decision."""
        try:
            from api.services.conversation.conversation_agent_turn_lifecycle import (
                clear_conversation_agent_attention,
            )

            await clear_conversation_agent_attention(agent_task_id, interaction_id)
            if not self.websocket_manager:
                return True
            message_payload: Dict[str, Any] = {
                "event_type": "checkpoint_resumed",
                "agent_task_id": agent_task_id,
                "message": "Provider permission resolved",
            }
            if root_task_id:
                message_payload["root_task_id"] = root_task_id
            if previous_task_id:
                message_payload["previous_task_id"] = previous_task_id
            await self.broadcast_agent_task_message(agent_task_id, message_payload)
            return True
        except Exception as exc:
            self.logger.debug(
                "Failed to publish provider permission resolution for %s: %s",
                agent_task_id,
                exc.__class__.__name__,
            )
            return False

    async def publish_provider_permission_request(
        self,
        *,
        agent_task_id: str,
        root_task_id: str | None,
        previous_task_id: str | None,
        interaction_id: str,
        provider_run_id: str,
        title: str,
        description: str | None,
        subject: Mapping[str, Any] | None,
        allow_option_id: str | None,
        reject_option_id: str,
    ) -> bool:
        """Broadcast a provider permission request through the existing approval channel.

        Reuses the `execution_approval_request` event type so `ApprovalOverlay`
        renders it with zero new WebSocket event types. Returns False without
        broadcasting when the Agent Task is absent or already terminal.
        """
        try:
            agent_task_record = await self.db_service.get_agent_task(agent_task_id)
            if not agent_task_record or agent_task_record.status in ("completed", "failed", "canceled"):
                return False
            from api.services.conversation.conversation_agent_turn_lifecycle import (
                publish_conversation_agent_attention,
            )

            await publish_conversation_agent_attention(agent_task_id, interaction_id)
            if not self.websocket_manager:
                return True

            message_payload: Dict[str, Any] = {
                "event_type": "execution_approval_request",
                "agent_task_id": agent_task_id,
                "approval_id": interaction_id,
                "command": title,
                "reason": description or "The provider is requesting permission to proceed.",
                "risk_level": "medium",
                "execution_type": "provider_permission",
                "provider_permission": {
                    "interaction_id": interaction_id,
                    "provider_run_id": provider_run_id,
                    "agent_task_id": agent_task_id,
                    "subject": dict(subject) if subject is not None else None,
                    "allow_option_id": allow_option_id,
                    "reject_option_id": reject_option_id,
                },
            }
            if root_task_id:
                message_payload["root_task_id"] = root_task_id
            if previous_task_id:
                message_payload["previous_task_id"] = previous_task_id
            await self.broadcast_agent_task_message(agent_task_id, message_payload)
            return True
        except Exception as exc:
            self.logger.debug(
                "Failed to publish provider permission request for %s: %s",
                agent_task_id,
                exc.__class__.__name__,
            )
            return False

    async def generate_agent_task_title(self, agent_task_id: str, agent_task: str) -> None:
        """Generate a concise sidebar title for an agent task via a lightweight LLM call."""
        try:
            from api.services.model_usage_service import ModelUsageService
            from api.dependencies import get_model_service
            from api.core.models.model_types import ModelCapability
            from api.core.models.model_invocation import call_model_with_prompt

            model_service = get_model_service()
            model_usage_service = ModelUsageService(model_service)
            model = await model_usage_service.get_model_for_task(
                capabilities={ModelCapability.REASONING}
            )
            if not model:
                self.logger.debug("No model available for title generation")
                return

            prompt = (
                "Generate a concise 3-6 word title that captures the intent of this request. "
                "Use noun phrases, not sentences. Examples:\n"
                "- \"Help me understand why this folder is so large\" → \"Large Folder Size Investigation\"\n"
                "- \"Can you draft a response to this email\" → \"Email Response Draft\"\n"
                "- \"Analyze the performance of our API endpoints\" → \"API Performance Analysis\"\n\n"
                f"Request: \"{agent_task}\"\n\n"
                "Title:"
            )

            response = await asyncio.wait_for(
                call_model_with_prompt(
                    model, prompt=prompt, max_tokens=30, enable_web_search=False
                ),
                timeout=8.0,
            )

            if response:
                title = plain_agent_task_title(response)
                if title and 2 < len(title) < 80:
                    await self.db_service.agent_task_service._mutations.update_agent_task_title(agent_task_id, title)
                    self.logger.info("📝 Generated title for %s: %r", agent_task_id, title)
        except Exception as exc:
            self.logger.debug("Title generation skipped: %s", exc)

    async def broadcast_agent_task_message(self, agent_task_id: Optional[str], message: Dict[str, Any]) -> bool:
        """Broadcast unless this task has already been canceled."""
        if agent_task_id and self._is_canceled(agent_task_id):
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


__all__ = ["AgentTaskRoutingService"]
