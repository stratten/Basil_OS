"""Public execution entry point selecting Conversation turn routes."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, NotRequired, Optional, TypedDict

from .conversation_agent_turn_lifecycle import ConversationAgentTurnLink
from .conversation_agent_turn_service import ConversationAgentTurnService
from .conversation_models import ConversationError, MessageRole
from .conversation_route_selector import ConversationRouteSelector
from .conversation_service import ConversationService
from .conversation_turn_contract import (
    ConversationTaskContinuationCandidate,
    ConversationTurnRoute,
    build_conversation_turn_placeholder_metadata,
)
from .document_processing_service import DocumentProcessingService
from api.core.knowledge.sqlite.conversation_repository import ConversationTurnAdmissionConflict

logger = logging.getLogger(__name__)

DEFAULT_CONVERSATION_SYSTEM_MESSAGE = "You are Basil, an intelligent assistant designed to be genuinely helpful, conversational, and insightful. You can engage in natural conversation while also providing practical assistance. When users ask casual questions like 'How are you?', respond naturally. When they need help with tasks, provide clear, actionable guidance. Adapt your communication style to match the context - be concise when brevity is needed, detailed when complexity requires it, and always aim to be more helpful than a standard LLM interaction.\n\nIMPORTANT: Match your thinking depth to the question complexity:\n- Simple factual questions (capitals, dates, definitions): Answer directly without extended reasoning\n- Complex problems or multi-step tasks: Use deeper analysis when genuinely needed\n- Avoid overthinking straightforward queries"

_RECENT_MESSAGE_LIMIT = 30
_RECENT_CHARACTER_LIMIT = 6000


class ConversationTurnAlreadyActiveError(ConversationError):
    """Raised when a durable turn is already active for the target conversation."""

    def __init__(self, conversation_id: str) -> None:
        super().__init__(f"A response is already active for conversation {conversation_id}")
        self.conversation_id = conversation_id

@dataclass(frozen=True)
class ConversationTurnRequest:
    """One inbound public Conversation turn awaiting route selection."""

    content: str
    conversation_id: Optional[str]
    model_id: Optional[str]
    file_paths: Optional[list[str]]
    message_metadata: dict[str, Any]
    display_prompt_markdown: Optional[str]
    delegation_opt_out: bool
    use_streaming: bool


@dataclass(frozen=True)
class DirectConversationTurn:
    """A turn routed to unchanged direct Conversation execution."""

    conversation_id: str
    content: str
    model_id: Optional[str]
    file_paths: Optional[list[str]]
    message_metadata: dict[str, Any]
    use_streaming: bool


@dataclass(frozen=True)
class AgentTaskConversationTurn:
    """A turn already bridged to a durable Agent Task."""

    conversation_id: str
    user_message_id: str
    assistant_message_id: str
    agent_task_id: str


class AgentTaskPairKwargs(TypedDict):
    """Typed arguments for durable Conversation Agent Task pair admission."""

    conversation_id: str
    user_content: str
    user_metadata: dict[str, Any] | None
    assistant_metadata: dict[str, Any]
    assistant_model_id: str | None


class AgentTaskSubmissionKwargs(TypedDict):
    """Typed arguments forwarded to the Conversation Agent Task submission service."""

    conversation_id: str
    user_message_id: str
    assistant_message_id: str
    route: ConversationTurnRoute
    content: str
    display_prompt_markdown: str | None
    reference_paths: list[str] | None
    model_id: str | None
    continuation_candidate: ConversationTaskContinuationCandidate | None
    on_link_persisted: NotRequired[Callable[[ConversationAgentTurnLink], Awaitable[None]]]


class ConversationTurnRouter:
    """Select and execute the durable route for one public Conversation turn."""

    def __init__(
        self,
        *,
        conversation_service: ConversationService,
        route_selector: ConversationRouteSelector,
        agent_turn_service: ConversationAgentTurnService,
    ) -> None:
        self._conversation_service = conversation_service
        self._route_selector = route_selector
        self._agent_turn_service = agent_turn_service

    async def route_turn(
        self,
        request: ConversationTurnRequest,
        *,
        on_link_persisted: Optional[Callable[[ConversationAgentTurnLink], Awaitable[None]]] = None,
    ) -> "DirectConversationTurn | AgentTaskConversationTurn":
        """Resolve one turn to its direct or Agent Task execution shape."""
        conversation_repository = self._conversation_service.conversation_repository
        if request.conversation_id:
            conversation = await self._conversation_service.get_conversation(request.conversation_id)
            if conversation is None:
                raise ConversationError(f"Conversation {request.conversation_id} not found")
            conversation_id = request.conversation_id
        else:
            conversation = await self._conversation_service.create_conversation(
                system_message=DEFAULT_CONVERSATION_SYSTEM_MESSAGE,
            )
            conversation_id = conversation.id

        bounded_recent_messages = await conversation_repository.get_bounded_recent_messages(
            conversation_id,
            message_limit=_RECENT_MESSAGE_LIMIT,
            character_limit=_RECENT_CHARACTER_LIMIT,
        )
        continuation_candidates = await self._agent_turn_service.list_continuation_candidates(
            conversation_id,
        )
        decision = await self._route_selector.select_route(
            content=request.content,
            bounded_recent_messages=bounded_recent_messages,
            selected_model_id=request.model_id,
            delegation_opt_out=request.delegation_opt_out,
            continuation_candidates=continuation_candidates,
        )

        if decision.route is ConversationTurnRoute.DIRECT:
            return DirectConversationTurn(
                conversation_id=conversation_id,
                content=request.content,
                model_id=request.model_id,
                file_paths=request.file_paths,
                message_metadata=request.message_metadata,
                use_streaming=request.use_streaming,
            )

        user_metadata: dict[str, Any] = dict(request.message_metadata)
        if request.file_paths:
            user_metadata["attached_files"] = DocumentProcessingService.build_file_metadata(
                request.file_paths,
            )
        pair_kwargs: AgentTaskPairKwargs = {
            "conversation_id": conversation_id,
            "user_content": request.content,
            "user_metadata": user_metadata or None,
            "assistant_metadata": build_conversation_turn_placeholder_metadata(
                ConversationTurnRoute.AGENT_TASK,
            ),
            "assistant_model_id": request.model_id,
        }
        if request.conversation_id:
            try:
                pair = await conversation_repository.admit_and_create_message_pair(**pair_kwargs)
            except ConversationTurnAdmissionConflict as exc:
                raise ConversationTurnAlreadyActiveError(exc.conversation_id) from exc
        else:
            pair = await conversation_repository.create_message_pair(**pair_kwargs)

        if not any(message.role == MessageRole.USER for message in conversation.messages):
            self._conversation_service._schedule_background_task(
                self._conversation_service._auto_title_conversation(conversation_id, request.content),
                f"conversation-auto-title-{conversation_id}",
            )
        continuation_candidate = next(
            (
                candidate
                for candidate in continuation_candidates
                if candidate.candidate_id == decision.continuation_candidate_id
            ),
            None,
        )
        submission_kwargs: AgentTaskSubmissionKwargs = {
            "conversation_id": conversation_id,
            "user_message_id": pair.user_message_id,
            "assistant_message_id": pair.assistant_message_id,
            "route": ConversationTurnRoute.AGENT_TASK,
            "content": request.content,
            "display_prompt_markdown": request.display_prompt_markdown,
            "reference_paths": request.file_paths,
            "model_id": request.model_id,
            "continuation_candidate": continuation_candidate,
        }
        if on_link_persisted is not None:
            submission_kwargs["on_link_persisted"] = on_link_persisted
        link = await self._agent_turn_service.submit_turn(
            **submission_kwargs,
        )
        return AgentTaskConversationTurn(
            conversation_id=conversation_id,
            user_message_id=pair.user_message_id,
            assistant_message_id=pair.assistant_message_id,
            agent_task_id=link.agent_task_id,
        )
