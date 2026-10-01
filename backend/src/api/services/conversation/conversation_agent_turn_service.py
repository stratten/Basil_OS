"""Submit persisted non-direct Conversation turns to the normal Agent Task runtime."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Awaitable, Callable, Optional, Sequence

from .conversation_agent_turn_lifecycle import ConversationAgentTurnLifecycle, ConversationAgentTurnLink
from .conversation_turn_contract import (
    CONVERSATION_TURN_METADATA_KEY,
    ConversationTaskContinuationCandidate,
    ConversationTurnLifecycle,
    ConversationTurnRoute,
)

_CONVERSATION_AGENT_TASK_INSTRUCTION = """You are handling a request delegated from Basil Conversation. Use relevant conversation and durable task context when it is available. Work through the request using normal approval-governed Agent Task capabilities when needed, then leave a durable result that Basil Conversation can evaluate and explain to the user."""
_FAILURE_STATUSES = frozenset({"failed", "error", "canceled"})
TERMINAL_AGENT_TASK_STATUSES = frozenset({"completed", "failed", "canceled"})

logger = logging.getLogger(__name__)


class ConversationAgentTurnService:
    """Submit an already-persisted Conversation Agent Task turn."""

    def __init__(
        self,
        *,
        repository: Any,
        submission_service: Any,
        agent_task_service: Any,
        lifecycle: ConversationAgentTurnLifecycle,
    ) -> None:
        self._repository = repository
        self._submission_service = submission_service
        self._agent_task_service = agent_task_service
        self._lifecycle = lifecycle

    async def list_continuation_candidates(
        self,
        conversation_id: str,
    ) -> list[ConversationTaskContinuationCandidate]:
        """Return bounded, server-authorized continuation candidates for one Conversation."""
        try:
            summaries = await self._agent_task_service.list_recent_conversation_task_summaries(
                conversation_id,
                limit=3,
            )
        except Exception as exc:
            logger.warning("Conversation continuation candidate lookup failed: %s", exc)
            return []
        candidates: list[ConversationTaskContinuationCandidate] = []
        for summary in summaries:
            if len(candidates) == 3:
                break
            if not isinstance(summary, dict):
                continue
            root_task_id = summary.get("root_task_id")
            previous_task_id = summary.get("previous_task_id")
            request_text = summary.get("request_text")
            outcome_text = summary.get("outcome_text")
            terminal_status = summary.get("status")
            if (
                not isinstance(root_task_id, str)
                or not root_task_id.strip()
                or not isinstance(previous_task_id, str)
                or not previous_task_id.strip()
                or not isinstance(request_text, str)
                or not isinstance(outcome_text, str)
                or terminal_status not in TERMINAL_AGENT_TASK_STATUSES
            ):
                continue
            candidates.append(
                ConversationTaskContinuationCandidate(
                    candidate_id=len(candidates) + 1,
                    root_task_id=root_task_id,
                    previous_task_id=previous_task_id,
                    request_text=request_text.strip()[:600],
                    outcome_text=outcome_text.strip()[:600],
                    terminal_status=terminal_status,
                )
            )
        return candidates

    async def _validated_continuation_target(
        self,
        conversation_id: str,
        candidate: ConversationTaskContinuationCandidate | None,
    ) -> tuple[str, str] | None:
        """Return current chain identity only when the selected candidate remains valid."""
        if candidate is None:
            return None
        try:
            root = await self._agent_task_service.get_agent_task(candidate.root_task_id)
            if (
                root is None
                or root.id != candidate.root_task_id
                or root.root_task_id not in {None, "", root.id}
                or root.origin_type != "conversation"
                or root.origin_id != conversation_id
            ):
                return None
            chain: Sequence[Any] = await self._agent_task_service.get_agent_task_chain(root.id)
            if not chain:
                return None
            latest = chain[-1]
            if (
                latest.id != candidate.previous_task_id
                or latest.status not in TERMINAL_AGENT_TASK_STATUSES
            ):
                return None
            return root.id, latest.id
        except Exception as exc:
            logger.warning("Conversation continuation candidate revalidation failed: %s", exc)
            return None

    async def submit_turn(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        route: ConversationTurnRoute,
        content: str,
        display_prompt_markdown: Optional[str],
        reference_paths: Optional[list[str]],
        model_id: Optional[str],
        continuation_candidate: ConversationTaskContinuationCandidate | None = None,
        on_link_persisted: Optional[Callable[[ConversationAgentTurnLink], Awaitable[None]]] = None,
    ) -> ConversationAgentTurnLink:
        """Persist the task link before submitting a non-direct Agent Task."""
        if route is not ConversationTurnRoute.AGENT_TASK:
            raise ValueError("ConversationAgentTurnService only accepts the agent_task route")
        for field_name, value in {
            "conversation_id": conversation_id,
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message_id,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        continuation_target = await self._validated_continuation_target(
            conversation_id,
            continuation_candidate,
        )
        agent_task_id = str(uuid.uuid4())
        link = ConversationAgentTurnLink(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            agent_task_id=agent_task_id,
            route=route,
            model_id=model_id,
        )
        await self._repository.merge_message_metadata(
            assistant_message_id,
            {
                CONVERSATION_TURN_METADATA_KEY: {
                    "agent_task_id": agent_task_id,
                    "lifecycle": ConversationTurnLifecycle.PENDING.value,
                    "terminal_outcome": None,
                    "user_message_id": user_message_id,
                    "narration": {
                        "lifecycle": "pending",
                    },
                }
            },
        )
        self._lifecycle.register_link(link)
        publish_preparing_agent_task = getattr(self._lifecycle, "publish_preparing_agent_task", None)
        if callable(publish_preparing_agent_task):
            await publish_preparing_agent_task(link)
        task_text = self._task_text(route, content)
        try:
            if on_link_persisted is not None:
                await on_link_persisted(link)
            submission_kwargs = {
                "agent_task": task_text,
                "display_prompt_markdown": display_prompt_markdown,
                "agent_task_id": agent_task_id,
                "reference_paths": reference_paths,
                "model_id": model_id,
                "conversation_id": conversation_id,
                "origin_type": "conversation",
                "origin_id": conversation_id,
            }
            if continuation_target is not None:
                submission_kwargs.update(
                    root_task_id=continuation_target[0],
                    previous_task_id=continuation_target[1],
                )
            submission_result = await self._submission_service.process_agent_task_direct(
                **submission_kwargs,
            )
        except Exception as exc:
            await self._lifecycle.record_submission_failure(link, str(exc))
            return link
        failure_reason = self._submission_failure_reason(submission_result)
        if failure_reason:
            await self._lifecycle.record_submission_failure(link, failure_reason)
        return link

    @staticmethod
    def _task_text(route: ConversationTurnRoute, content: str) -> str:
        if route is not ConversationTurnRoute.AGENT_TASK:
            raise ValueError("ConversationAgentTurnService only accepts the agent_task route")
        return f"{_CONVERSATION_AGENT_TASK_INSTRUCTION}\n\nUser request:\n{content}"

    @staticmethod
    def _submission_failure_reason(result: Any) -> str | None:
        if not isinstance(result, dict):
            return "Agent Task submission returned an invalid response."
        if result.get("success") is False:
            return str(result.get("error") or result.get("message") or "Agent Task submission failed.")
        status = result.get("status")
        if isinstance(status, str) and status.strip().lower() in _FAILURE_STATUSES:
            return str(result.get("error") or result.get("message") or "Agent Task submission failed.")
        return None
