"""Durably project linked Agent Task lifecycle into Conversation placeholders."""

from __future__ import annotations

import asyncio
from hashlib import sha256
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from api.core.knowledge.sqlite.conversation_repository import ConversationRepository
from api.dependencies import get_sqlite_knowledge_service
from api.services.websocket_connection_manager import active_connections

from .conversation_agent_activity_contract import build_conversation_agent_activity_payload
from .conversation_agent_status_contract import (
    build_conversation_agent_status_payload,
    truncate_conversation_agent_status_text,
)
from .conversation_turn_contract import (
    CONVERSATION_TURN_METADATA_KEY,
    ConversationTurnLifecycle,
    ConversationTurnNarrationLifecycle,
    ConversationTurnRoute,
    is_terminal_conversation_turn_lifecycle,
    parse_conversation_turn_metadata,
)

logger = logging.getLogger(__name__)
_callback_registered = False
_registered_lifecycle: Optional["ConversationAgentTurnLifecycle"] = None


@dataclass(frozen=True)
class ConversationAgentTurnLink:
    """Durable identifiers connecting one Conversation placeholder to an Agent Task."""

    conversation_id: str
    user_message_id: str
    assistant_message_id: str
    agent_task_id: str
    route: ConversationTurnRoute
    model_id: str | None


_STATUS_TEXT_BY_AGENT_TASK_STATUS = {
    "capturing": "Agent task is gathering context.",
    "routing": "Agent task is selecting an approach.",
    "routed": "Agent task is ready to begin.",
    "processing": "Agent task is working.",
    "awaiting_user_input": "Agent task needs your input.",
    "needs_clarification": "Agent task needs clarification.",
    "clarification_added": "Agent task received your clarification.",
    "completed": "Agent task completed. Preparing a conversation response.",
    "failed": "Agent task failed. Preparing a conversation response.",
    "canceled": "Agent task was canceled. Preparing a conversation response.",
}


def _status_text_for_agent_task_status(raw_status: str | None) -> str:
    normalized = raw_status.strip().lower() if isinstance(raw_status, str) else ""
    return _STATUS_TEXT_BY_AGENT_TASK_STATUS.get(normalized, "Agent task is in progress.")


async def broadcast_conversation_agent_status(payload: dict[str, Any]) -> None:
    """Broadcast a constrained Conversation status event to connected clients."""
    for connection in tuple(active_connections):
        try:
            await connection.send_json(payload)
        except Exception as exc:
            logger.warning("Conversation AgentTask status broadcast failed: %s", exc)


async def broadcast_conversation_agent_activity(payload: dict[str, Any]) -> None:
    """Broadcast a constrained Conversation activity event to connected clients."""
    for connection in tuple(active_connections):
        try:
            await connection.send_json(payload)
        except Exception as exc:
            logger.warning("Conversation AgentTask activity broadcast failed: %s", exc)


def _activity_summary_fingerprint(summary: dict[str, Any]) -> str:
    """Return a stable durable duplicate key for a selected activity summary."""
    encoded = json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return sha256(encoded.encode("utf-8")).hexdigest()


class ConversationAgentTurnLifecycle:
    """Projects Agent Task events for Conversation-linked placeholders only."""

    def __init__(
        self,
        *,
        repository: ConversationRepository,
        get_agent_task: Callable[[str], Awaitable[Any]],
        broadcast_status: Callable[[dict[str, Any]], Awaitable[None]] = broadcast_conversation_agent_status,
        broadcast_activity: Callable[[dict[str, Any]], Awaitable[None]] = broadcast_conversation_agent_activity,
        start_narration: Optional[Callable[[str], None]] = None,
        release_agent_task: Callable[[str], None] = lambda _agent_task_id: None,
    ) -> None:
        self._repository = repository
        self._get_agent_task = get_agent_task
        self._broadcast_status = broadcast_status
        self._broadcast_activity = broadcast_activity
        self._start_narration = start_narration
        self._release_agent_task = release_agent_task
        self._links: dict[str, ConversationAgentTurnLink] = {}
        self._projection_lock = asyncio.Lock()

    def register_link(self, link: ConversationAgentTurnLink) -> None:
        """Cache a link after its durable placeholder metadata has been updated."""
        self._links[link.agent_task_id] = link

    async def publish_preparing_agent_task(self, link: ConversationAgentTurnLink) -> None:
        """Publish the visible delegated-turn state before Agent Task submission starts."""
        await self._broadcast_status(
            build_conversation_agent_status_payload(
                conversation_id=link.conversation_id,
                placeholder_message_id=link.assistant_message_id,
                agent_task_id=link.agent_task_id,
                lifecycle=ConversationTurnLifecycle.PENDING,
                status_text="Preparing agent task",
                terminal_outcome=None,
                agent_status="pending",
                narration_state="pending",
            )
        )

    async def record_submission_failure(
        self,
        link: ConversationAgentTurnLink,
        terminal_outcome: str,
    ) -> None:
        """Persist and publish a submission failure not represented by an Agent Task event."""
        projected = await self._project(
            link=link,
            lifecycle=ConversationTurnLifecycle.FAILED,
            terminal_outcome=terminal_outcome,
            raw_status="failed",
            narration_lifecycle=ConversationTurnNarrationLifecycle.READY,
        )
        if projected:
            if self._start_narration is not None:
                self._start_narration(link.agent_task_id)

    async def handle_agent_task_event(self, event: Any) -> None:
        """Project one Agent Task event when it belongs to a Conversation placeholder."""
        event_type = getattr(event, "event_type", None)
        if event_type not in {"created", "status_changed", "clarification_added", "updated"}:
            return
        agent_task_id = getattr(event, "agent_task_id", None)
        if not isinstance(agent_task_id, str) or not agent_task_id.strip():
            return
        raw_status = getattr(event, "new_status", None)
        event_data = getattr(event, "agent_task_data", None)
        if not isinstance(raw_status, str) or not raw_status.strip():
            raw_status = event_data.get("status") if isinstance(event_data, dict) else None
        if (not isinstance(raw_status, str) or not raw_status.strip()) and event_type == "clarification_added":
            raw_status = "clarification_added"
        if not isinstance(raw_status, str) or not raw_status.strip():
            return
        link = await self._resolve_link(agent_task_id)
        if link is None:
            return
        lifecycle = self._map_lifecycle(raw_status)
        terminal_outcome: str | None = None
        narration_lifecycle: ConversationTurnNarrationLifecycle | None = None
        if lifecycle is ConversationTurnLifecycle.COMPLETED:
            terminal_outcome = "Agent task completed."
            narration_lifecycle = ConversationTurnNarrationLifecycle.READY
        elif lifecycle in {ConversationTurnLifecycle.FAILED, ConversationTurnLifecycle.CANCELED}:
            terminal_outcome = _status_text_for_agent_task_status(raw_status)
            narration_lifecycle = ConversationTurnNarrationLifecycle.READY
        requires_user_attention = (
            isinstance(raw_status, str)
            and raw_status.strip().lower() in {"awaiting_user_input", "needs_clarification"}
        )
        attention_id = (
            self._attention_id_for_event(agent_task_id, raw_status, event_data)
            if requires_user_attention
            else None
        )
        projected = await self._project(
            link=link,
            lifecycle=lifecycle,
            terminal_outcome=terminal_outcome,
            raw_status=raw_status,
            narration_lifecycle=narration_lifecycle,
            requires_user_attention=requires_user_attention,
            attention_id=attention_id,
        )
        await self.publish_agent_task_activity_summary(
            link=link,
            expected_lifecycle=lifecycle,
        )
        if is_terminal_conversation_turn_lifecycle(lifecycle):
            if projected and self._start_narration is not None:
                self._start_narration(link.agent_task_id)

    async def handle_agent_task_progress(
        self,
        agent_task_id: str,
        status_text: str | None,
    ) -> None:
        """Project one live Agent Task step into its linked Conversation placeholder."""
        normalized_status_text = truncate_conversation_agent_status_text(status_text)
        if not isinstance(agent_task_id, str) or not agent_task_id.strip() or normalized_status_text is None:
            return
        link = await self._resolve_link(agent_task_id)
        if link is None:
            return
        await self._project(
            link=link,
            lifecycle=ConversationTurnLifecycle.RUNNING,
            terminal_outcome=None,
            raw_status="processing",
            narration_lifecycle=None,
            status_text_override=normalized_status_text,
            attention_action="preserve",
        )
        await self.publish_agent_task_activity_summary(
            link=link,
            expected_lifecycle=ConversationTurnLifecycle.RUNNING,
            latest_activity_override=normalized_status_text,
        )

    async def handle_agent_task_attention(
        self,
        agent_task_id: str,
        attention_id: str,
    ) -> None:
        link = await self._resolve_link(agent_task_id)
        if link is None:
            return
        await self._project(
            link=link,
            lifecycle=ConversationTurnLifecycle.RUNNING,
            terminal_outcome=None,
            raw_status="awaiting_user_input",
            narration_lifecycle=None,
            status_text_override="Agent task needs your input.",
            requires_user_attention=True,
            attention_id=attention_id,
            attention_action="append",
        )
        await self.publish_agent_task_activity_summary(
            link=link,
            expected_lifecycle=ConversationTurnLifecycle.RUNNING,
            requires_user_attention_override=True,
        )

    async def clear_agent_task_attention(
        self,
        agent_task_id: str,
        attention_id: str,
    ) -> None:
        link = await self._resolve_link(agent_task_id)
        if link is None:
            return
        row = await self._repository.find_conversation_turn_by_agent_task_id(agent_task_id)
        current_turn = (
            row.get("metadata", {}).get(CONVERSATION_TURN_METADATA_KEY)
            if isinstance(row, dict) and isinstance(row.get("metadata"), dict)
            else None
        )
        if not isinstance(current_turn, dict):
            return
        current_attention_ids = self._attention_ids_from_turn(current_turn)
        if attention_id not in current_attention_ids:
            return
        await self._project(
            link=link,
            lifecycle=ConversationTurnLifecycle.RUNNING,
            terminal_outcome=None,
            raw_status="processing",
            narration_lifecycle=None,
            requires_user_attention=len(current_attention_ids) > 1,
            attention_id=attention_id,
            attention_action="remove",
        )
        await self.publish_agent_task_activity_summary(
            link=link,
            expected_lifecycle=ConversationTurnLifecycle.RUNNING,
            requires_user_attention_override=len(current_attention_ids) > 1,
        )

    @staticmethod
    def _build_activity_source_summary(
        task: Any,
        *,
        latest_activity_override: str | None,
        requires_user_attention_override: bool | None,
    ) -> dict[str, Any] | None:
        """Rebuild the existing Package 0 summary from a durable Agent Task record."""
        from api.routes.agent_tasks.projections.artifact_presentation import build_agent_task_presentation_summary
        from api.routes.agent_tasks.utils import extract_result_data

        agent_task_id = getattr(task, "id", None)
        lifecycle = getattr(task, "status", None)
        result_data = getattr(task, "result_data", None)
        if not isinstance(agent_task_id, str) or not agent_task_id.strip():
            return None
        if not isinstance(lifecycle, str) or not lifecycle.strip():
            return None
        _result_message, files, _reference_paths, _error_message, timeline = extract_result_data(task)
        summary = build_agent_task_presentation_summary(
            agent_task_id=agent_task_id,
            lifecycle=lifecycle,
            result_data=result_data if isinstance(result_data, dict) else None,
            execution_timeline=timeline if isinstance(timeline, list) else None,
            files=files,
        )
        if latest_activity_override is not None:
            summary["latest_activity"] = latest_activity_override
        if requires_user_attention_override is not None:
            summary["requires_user_attention"] = requires_user_attention_override
        return summary

    async def handle_agent_task_artifact(
        self,
        agent_task_id: str,
        artifact_id: str,
    ) -> bool:
        """Project one already-persisted direct-write artifact for a linked Conversation turn."""
        if (
            not isinstance(agent_task_id, str)
            or not agent_task_id.strip()
            or not isinstance(artifact_id, str)
            or not artifact_id.strip()
        ):
            return False
        link = await self._resolve_link(agent_task_id)
        if link is None:
            return False
        row = await self._repository.find_conversation_turn_by_agent_task_id(agent_task_id)
        current = parse_conversation_turn_metadata(row.get("metadata")) if row else None
        if current is None or current.agent_task_id != agent_task_id:
            return False
        return await self.publish_agent_task_activity_summary(
            link=link,
            expected_lifecycle=current.lifecycle,
            required_artifact_id=artifact_id,
        )

    async def publish_agent_task_activity_summary(
        self,
        *,
        link: ConversationAgentTurnLink,
        expected_lifecycle: ConversationTurnLifecycle,
        latest_activity_override: str | None = None,
        requires_user_attention_override: bool | None = None,
        required_artifact_id: str | None = None,
    ) -> bool:
        """Persist and then publish one compact activity projection for a linked task."""
        task = await self._load_agent_task_or_none(link.agent_task_id)
        try:
            summary = self._build_activity_source_summary(
                task,
                latest_activity_override=latest_activity_override,
                requires_user_attention_override=requires_user_attention_override,
            )
        except Exception:
            logger.warning(
                "Conversation AgentTask activity projection could not build summary for %s",
                link.agent_task_id,
                exc_info=True,
            )
            return False
        if summary is None:
            return False
        if required_artifact_id is not None and not any(
            isinstance(artifact, dict) and artifact.get("artifact_id") == required_artifact_id
            for artifact in summary.get("artifacts", [])
        ):
            return False
        try:
            payload = build_conversation_agent_activity_payload(
                conversation_id=link.conversation_id,
                placeholder_message_id=link.assistant_message_id,
                agent_task_id=link.agent_task_id,
                summary=summary,
            )
        except (TypeError, ValueError):
            logger.warning(
                "Conversation AgentTask activity projection rejected malformed summary for %s",
                link.agent_task_id,
                exc_info=True,
            )
            return False
        projected_summary = payload["summary"]
        fingerprint = _activity_summary_fingerprint(projected_summary)
        async with self._projection_lock:
            row = await self._repository.find_conversation_turn_by_agent_task_id(link.agent_task_id)
            current = parse_conversation_turn_metadata(row.get("metadata")) if row else None
            current_turn = (
                row.get("metadata", {}).get(CONVERSATION_TURN_METADATA_KEY)
                if isinstance(row, dict) and isinstance(row.get("metadata"), dict)
                else None
            )
            if (
                current is None
                or current.agent_task_id != link.agent_task_id
                or current.lifecycle is not expected_lifecycle
                or not isinstance(current_turn, dict)
            ):
                return False
            if current_turn.get("activity_summary_fingerprint") == fingerprint:
                return False
            try:
                await self._repository.merge_message_metadata(
                    link.assistant_message_id,
                    {
                        CONVERSATION_TURN_METADATA_KEY: {
                            "activity_summary": projected_summary,
                            "activity_summary_fingerprint": fingerprint,
                        }
                    },
                )
            except Exception:
                logger.warning(
                    "Conversation AgentTask activity projection could not persist summary for %s",
                    link.agent_task_id,
                    exc_info=True,
                )
                return False
        await self._broadcast_activity(payload)
        return True

    async def _load_agent_task_or_none(self, agent_task_id: str) -> Any | None:
        """Load a task when available without losing a durable terminal projection."""
        try:
            return await self._get_agent_task(agent_task_id)
        except Exception:
            logger.warning(
                "Conversation AgentTask projection could not load task %s",
                agent_task_id,
                exc_info=True,
            )
            return None

    async def _resolve_link(self, agent_task_id: str) -> ConversationAgentTurnLink | None:
        cached = self._links.get(agent_task_id)
        if cached is not None:
            return cached
        row = await self._repository.find_conversation_turn_by_agent_task_id(agent_task_id)
        if row is None:
            return None
        parsed = parse_conversation_turn_metadata(row.get("metadata"))
        if parsed is None or parsed.agent_task_id != agent_task_id:
            return None
        link = ConversationAgentTurnLink(
            conversation_id=row["conversation_id"],
            user_message_id=parsed.user_message_id or "",
            assistant_message_id=row["assistant_message_id"],
            agent_task_id=agent_task_id,
            route=parsed.route,
            model_id=row.get("assistant_model_id"),
        )
        self.register_link(link)
        return link

    @staticmethod
    def _attention_id_for_event(
        agent_task_id: str,
        raw_status: str,
        event_data: Any,
    ) -> str | None:
        normalized_status = raw_status.strip().lower()
        if normalized_status not in {"awaiting_user_input", "needs_clarification"}:
            return None
        if isinstance(event_data, dict):
            result_data = event_data.get("result_data")
            if isinstance(result_data, dict):
                checkpoint_data = result_data.get("checkpoint_data")
                checkpoint_id = (
                    checkpoint_data.get("checkpoint_id")
                    if isinstance(checkpoint_data, dict)
                    else None
                )
                if isinstance(checkpoint_id, str) and checkpoint_id.strip():
                    return checkpoint_id.strip()
            updated_at = event_data.get("updated_at")
            if isinstance(updated_at, str) and updated_at.strip():
                return f"{agent_task_id}:{updated_at.strip()}"
        return agent_task_id

    @staticmethod
    def _attention_ids_from_turn(current_turn: dict[str, Any] | None) -> list[str]:
        if not isinstance(current_turn, dict):
            return []
        raw_ids = current_turn.get("attention_ids")
        if not isinstance(raw_ids, list):
            raw_ids = [current_turn.get("attention_id")]
        attention_ids = []
        for value in raw_ids:
            if isinstance(value, str) and value.strip() and value not in attention_ids:
                attention_ids.append(value)
        return attention_ids

    @staticmethod
    def _map_lifecycle(raw_status: str) -> ConversationTurnLifecycle:
        normalized = raw_status.strip().lower()
        if normalized == "completed":
            return ConversationTurnLifecycle.COMPLETED
        if normalized == "failed":
            return ConversationTurnLifecycle.FAILED
        if normalized == "canceled":
            return ConversationTurnLifecycle.CANCELED
        return ConversationTurnLifecycle.RUNNING

    async def _project(
        self,
        *,
        link: ConversationAgentTurnLink,
        lifecycle: ConversationTurnLifecycle,
        terminal_outcome: str | None,
        raw_status: str,
        narration_lifecycle: ConversationTurnNarrationLifecycle | None,
        status_text_override: str | None = None,
        requires_user_attention: bool = False,
        attention_id: str | None = None,
        attention_action: str = "replace",
    ) -> bool:
        terminal_outcome = truncate_conversation_agent_status_text(terminal_outcome)
        status_text = (
            truncate_conversation_agent_status_text(status_text_override)
            or _status_text_for_agent_task_status(raw_status)
        )
        async with self._projection_lock:
            row = await self._repository.find_conversation_turn_by_agent_task_id(link.agent_task_id)
            current = parse_conversation_turn_metadata(row.get("metadata")) if row else None
            current_turn = (
                row.get("metadata", {}).get(CONVERSATION_TURN_METADATA_KEY)
                if isinstance(row, dict) and isinstance(row.get("metadata"), dict)
                else None
            )
            current_status_text = (
                current_turn.get("status_text")
                if isinstance(current_turn, dict)
                else None
            )
            current_attention_required = (
                current_turn.get("requires_user_attention") is True
                if isinstance(current_turn, dict)
                else False
            )
            current_attention_ids = self._attention_ids_from_turn(current_turn)
            if attention_action == "append":
                attention_ids = [
                    *current_attention_ids,
                    *(
                        [attention_id]
                        if isinstance(attention_id, str)
                        and attention_id.strip()
                        and attention_id not in current_attention_ids
                        else []
                    ),
                ]
            elif attention_action == "remove":
                attention_ids = [
                    current_id
                    for current_id in current_attention_ids
                    if current_id != attention_id
                ]
            elif attention_action == "preserve":
                attention_ids = current_attention_ids
            elif requires_user_attention:
                attention_ids = [attention_id] if attention_id else []
            else:
                attention_ids = []
            effective_requires_attention = bool(attention_ids)
            effective_attention_id = attention_ids[0] if attention_ids else None
            if (
                current
                and current.lifecycle is lifecycle
                and current.terminal_outcome == terminal_outcome
                and (
                    status_text_override is None
                    or current_status_text == status_text
                )
                and (
                    narration_lifecycle is None
                    or current.narration.lifecycle is narration_lifecycle
                )
                and current_attention_required is effective_requires_attention
                and current_attention_ids == attention_ids
            ):
                return False
            if current and is_terminal_conversation_turn_lifecycle(current.lifecycle):
                if current.lifecycle is not lifecycle:
                    logger.warning(
                        "Conversation AgentTask projection ignored stale %s event for terminal %s turn %s",
                        lifecycle.value,
                        current.lifecycle.value,
                        link.agent_task_id,
                    )
                    return False
            await self._repository.merge_message_metadata(
                link.assistant_message_id,
                {
                    CONVERSATION_TURN_METADATA_KEY: {
                        "lifecycle": lifecycle.value,
                        "status_text": status_text,
                        "terminal_outcome": terminal_outcome,
                        "requires_user_attention": effective_requires_attention,
                        "attention_id": effective_attention_id,
                        **(
                            {"attention_ids": attention_ids}
                            if len(attention_ids) > 1 or len(current_attention_ids) > 1
                            else {}
                        ),
                        **(
                            {
                                "narration": {
                                    "lifecycle": narration_lifecycle.value,
                                }
                            }
                            if narration_lifecycle is not None
                            else {}
                        ),
                    }
                },
            )
        await self._broadcast_status(
            build_conversation_agent_status_payload(
                conversation_id=link.conversation_id,
                placeholder_message_id=link.assistant_message_id,
                agent_task_id=link.agent_task_id,
                lifecycle=lifecycle,
                status_text=status_text,
                terminal_outcome=terminal_outcome,
                agent_status=raw_status,
                narration_state=(
                    narration_lifecycle.value if narration_lifecycle is not None else None
                ),
                requires_user_attention=effective_requires_attention,
                attention_id=effective_attention_id,
                attention_ids=attention_ids,
            )
        )
        return True


def ensure_conversation_agent_turn_callback_registered() -> None:
    """Register the Conversation projection callback with the shared event stream once."""
    global _callback_registered, _registered_lifecycle
    if _callback_registered:
        return
    from .conversation_agent_narration_service import (
        ensure_conversation_agent_narration_service_registered,
    )
    from api.routes.websocket_routes.conversation_request_runtime import (
        conversation_request_runtime,
    )

    database = get_sqlite_knowledge_service()
    narration_service = ensure_conversation_agent_narration_service_registered()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=ConversationRepository(sqlite_service=database),
        get_agent_task=database.get_agent_task,
        start_narration=narration_service.start_narration,
        release_agent_task=conversation_request_runtime.release_agent_task,
    )
    database.register_agent_task_callback(lifecycle.handle_agent_task_event)
    _registered_lifecycle = lifecycle
    _callback_registered = True
    logger.info("Registered Conversation AgentTask lifecycle projection callback")


def get_registered_conversation_agent_turn_lifecycle() -> ConversationAgentTurnLifecycle:
    """Return the registered shared-stream projection for later router injection."""
    if _registered_lifecycle is None:
        raise RuntimeError("Conversation AgentTask lifecycle projection callback is not registered")
    return _registered_lifecycle


async def publish_conversation_agent_attention(
    agent_task_id: str,
    attention_id: str,
) -> None:
    lifecycle = _registered_lifecycle
    if lifecycle is None:
        return
    await lifecycle.handle_agent_task_attention(agent_task_id, attention_id)


async def clear_conversation_agent_attention(
    agent_task_id: str,
    attention_id: str,
) -> None:
    lifecycle = _registered_lifecycle
    if lifecycle is None:
        return
    await lifecycle.clear_agent_task_attention(agent_task_id, attention_id)


async def project_conversation_agent_task_progress(
    agent_task_id: str,
    status_text: str | None,
) -> None:
    """Persist and publish a live step when it belongs to a delegated Conversation turn."""
    lifecycle = _registered_lifecycle
    if lifecycle is None:
        return
    await lifecycle.handle_agent_task_progress(agent_task_id, status_text)


async def project_conversation_agent_task_artifact(
    agent_task_id: str,
    artifact_id: str,
) -> None:
    """Persist and emit direct-write activity only after its task timeline contains it."""
    lifecycle = _registered_lifecycle
    if lifecycle is None:
        return
    await lifecycle.handle_agent_task_artifact(agent_task_id, artifact_id)
