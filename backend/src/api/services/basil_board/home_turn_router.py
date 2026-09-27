"""Home turn routing for BasilBoard."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from api.core.models.model_types import ModelCapability
from api.services.basil_board.models import (
    HomeTurnRequest,
    HomeTurnResponse,
    HomeTurnRoute,
    HomeTurnRouteKind,
    HomeTurnState,
)
from api.services.basil_board.repository import BasilBoardRepository
from api.services.basil_board.service import BasilBoardService
from api.services.conversation.conversation_models import ConversationError, ModelNotAvailableError
from api.services.conversation.conversation_service import ConversationService

logger = logging.getLogger(__name__)

_CLASSIFIER_PROMPT = """Classify this Basil Home turn. Return JSON only.
Use "conversation" only when a direct answer from the current conversation is sufficient and no tool, retrieval, external state, durable task, file operation, scheduling operation, or user-visible workflow is needed.
Use "agent_task" for every request to search, recall, inspect, create, modify, schedule, act, verify, compare external/current data, or do multi-step work.
When uncertain, choose "agent_task".
JSON schema: {{"route_kind":"conversation"|"agent_task","reason":"<= 160 characters","confidence":number from 0 to 1}}
Turn: {turn}"""

_CONFIDENCE_THRESHOLD = 0.80


class HomeTurnRouteClassifier:
    """Classifies a Home turn into conversation or agent_task."""

    def __init__(self, conversation_service: ConversationService) -> None:
        self._conversation_service = conversation_service

    async def classify(self, content: str, model_id: Optional[str] = None) -> HomeTurnRoute:
        fallback = HomeTurnRoute(
            route_kind=HomeTurnRouteKind.AGENT_TASK,
            reason="Classifier fallback to agent task",
            confidence=None,
        )
        try:
            model = await self._conversation_service._get_model_for_task(
                [ModelCapability.REASONING],
                model_id,
            )
            if not model:
                return fallback

            prompt = _CLASSIFIER_PROMPT.format(turn=content.strip())
            response = await model.chat_completion(
                [{"role": "user", "content": prompt}]
            )
            raw = (response.get("content") or "").strip()
            parsed = self._parse_classifier_json(raw)
            if not parsed:
                return fallback

            route_kind_raw = parsed.get("route_kind")
            confidence = parsed.get("confidence")
            reason = str(parsed.get("reason") or "Model classification")[:160]
            if (
                route_kind_raw == HomeTurnRouteKind.CONVERSATION.value
                and isinstance(confidence, (int, float))
                and float(confidence) >= _CONFIDENCE_THRESHOLD
            ):
                return HomeTurnRoute(
                    route_kind=HomeTurnRouteKind.CONVERSATION,
                    reason=reason,
                    confidence=float(confidence),
                )
            return HomeTurnRoute(
                route_kind=HomeTurnRouteKind.AGENT_TASK,
                reason=reason or fallback.reason,
                confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
            )
        except Exception as exc:
            logger.warning("Home turn classification failed: %s", exc, exc_info=True)
            return fallback

    def _parse_classifier_json(self, raw: str) -> Optional[Dict[str, Any]]:
        candidates = [raw]
        fence_match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if fence_match:
            candidates.append(fence_match.group(0))
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
        return None


class HomeTurnRouter:
    """Routes normalized Home turns to conversation or agent task execution."""

    def __init__(
        self,
        *,
        basil_board_service: BasilBoardService,
        conversation_service: ConversationService,
        agent_task_submission_service: Any,
        repository: Optional[BasilBoardRepository] = None,
    ) -> None:
        self._board = basil_board_service
        self._conversation_service = conversation_service
        self._submission_service = agent_task_submission_service
        self._repo = repository or basil_board_service._repo
        self._classifier = HomeTurnRouteClassifier(conversation_service)

    async def submit_turn(self, request: HomeTurnRequest) -> HomeTurnResponse:
        content = request.content.strip()
        if not content:
            raise ValueError("Home turn content must not be blank")

        reference_paths = request.reference_paths or None
        display_prompt_markdown = request.display_prompt_markdown or None
        message_metadata: Dict[str, Any] = {
            "surface": "basil_board_home",
            "reference_paths": list(reference_paths or []),
        }
        if display_prompt_markdown:
            message_metadata["display_prompt_markdown"] = display_prompt_markdown

        inquiry = await self._board.create_inquiry(
            prompt_text=content,
            display_prompt_markdown=display_prompt_markdown,
            reference_paths=list(reference_paths or []),
        )
        try:
            conversation_id = await self._board.create_inquiry_conversation(content)
        except Exception:
            await self._board.update_inquiry(inquiry.id, state=HomeTurnState.FAILED)
            raise
        await self._board.update_inquiry(inquiry.id, conversation_id=conversation_id)
        route = await self._classifier.classify(content, request.model_id)

        if route.route_kind == HomeTurnRouteKind.CONVERSATION:
            return await self._route_conversation(
                inquiry_id=inquiry.id,
                conversation_id=conversation_id,
                content=content,
                model_id=request.model_id,
                route=route,
                reference_paths=reference_paths,
                message_metadata=message_metadata,
            )
        return await self._route_agent_task(
            inquiry_id=inquiry.id,
            conversation_id=conversation_id,
            content=content,
            model_id=request.model_id,
            route=route,
            reference_paths=reference_paths,
            display_prompt_markdown=display_prompt_markdown,
            message_metadata=message_metadata,
        )

    async def _route_conversation(
        self,
        *,
        inquiry_id: str,
        conversation_id: str,
        content: str,
        model_id: Optional[str],
        route: HomeTurnRoute,
        reference_paths: Optional[List[str]],
        message_metadata: Dict[str, Any],
    ) -> HomeTurnResponse:
        try:
            response = await self._conversation_service.send_message(
                conversation_id,
                content,
                model_id=model_id,
                file_paths=reference_paths,
                message_metadata=message_metadata,
            )
        except ModelNotAvailableError as exc:
            if exc.user_message_id and exc.error_message_id:
                await self._board.update_inquiry(
                    inquiry_id,
                    route_kind=route.route_kind,
                    route_reason=route.reason,
                    route_confidence=route.confidence,
                    state=HomeTurnState.FAILED,
                    user_message_id=exc.user_message_id,
                    assistant_message_id=exc.error_message_id,
                )
                return HomeTurnResponse(
                    inquiry_id=inquiry_id,
                    user_message_id=exc.user_message_id,
                    route_kind=route.route_kind,
                    route_reason=route.reason,
                    route_confidence=route.confidence,
                    state=HomeTurnState.FAILED,
                    assistant_message_id=exc.error_message_id,
                    assistant_content=str(exc),
                )
            await self._board.update_inquiry(
                inquiry_id,
                route_kind=route.route_kind,
                route_reason=route.reason,
                route_confidence=route.confidence,
                state=HomeTurnState.FAILED,
            )
            raise ValueError(str(exc)) from exc
        except ConversationError as exc:
            await self._board.update_inquiry(
                inquiry_id,
                route_kind=route.route_kind,
                route_reason=route.reason,
                route_confidence=route.confidence,
                state=HomeTurnState.FAILED,
            )
            raise ValueError(str(exc)) from exc
        except Exception:
            await self._board.update_inquiry(
                inquiry_id,
                route_kind=route.route_kind,
                route_reason=route.reason,
                route_confidence=route.confidence,
                state=HomeTurnState.FAILED,
            )
            raise

        user_message_id = response.user_message_id
        if not user_message_id:
            raise ValueError("Conversation route did not return a user_message_id")

        state = (
            HomeTurnState.FAILED
            if response.message.role.value == "error"
            else HomeTurnState.COMPLETED
        )
        await self._board.update_inquiry(
            inquiry_id,
            route_kind=route.route_kind,
            route_reason=route.reason,
            route_confidence=route.confidence,
            state=state,
            user_message_id=user_message_id,
            assistant_message_id=response.message.id,
        )

        return HomeTurnResponse(
            inquiry_id=inquiry_id,
            user_message_id=user_message_id,
            route_kind=route.route_kind,
            route_reason=route.reason,
            route_confidence=route.confidence,
            state=state,
            assistant_message_id=response.message.id,
            assistant_content=response.message.content,
        )

    async def _route_agent_task(
        self,
        *,
        inquiry_id: str,
        conversation_id: str,
        content: str,
        model_id: Optional[str],
        route: HomeTurnRoute,
        reference_paths: Optional[List[str]],
        display_prompt_markdown: Optional[str],
        message_metadata: Dict[str, Any],
    ) -> HomeTurnResponse:
        try:
            user_message_id = await self._conversation_service.conversation_repository.add_message(
                conversation_id=conversation_id,
                role="user",
                content=content,
                metadata=message_metadata,
            )
        except Exception:
            await self._board.update_inquiry(
                inquiry_id,
                route_kind=route.route_kind,
                route_reason=route.reason,
                route_confidence=route.confidence,
                state=HomeTurnState.FAILED,
            )
            raise
        await self._board.update_inquiry(
            inquiry_id,
            route_kind=route.route_kind,
            route_reason=route.reason,
            route_confidence=route.confidence,
            state=HomeTurnState.ROUTING,
            user_message_id=user_message_id,
        )

        agent_task_id = str(uuid.uuid4())
        await self._board.update_inquiry(inquiry_id, agent_task_id=agent_task_id)

        try:
            result = await self._submission_service.process_agent_task_direct(
                agent_task=content,
                agent_task_id=agent_task_id,
                model_id=model_id,
                display_prompt_markdown=display_prompt_markdown,
                reference_paths=reference_paths,
                conversation_id=conversation_id,
                origin_type="conversation",
                origin_id=conversation_id,
            )
        except Exception:
            await self._board.update_inquiry(inquiry_id, state=HomeTurnState.FAILED)
            raise

        accepted = bool(result.get("success", True)) and result.get("operation") != "cancelled"
        next_state = HomeTurnState.RUNNING if accepted else HomeTurnState.FAILED
        await self._board.update_inquiry(inquiry_id, state=next_state)

        return HomeTurnResponse(
            inquiry_id=inquiry_id,
            user_message_id=user_message_id,
            route_kind=route.route_kind,
            route_reason=route.reason,
            route_confidence=route.confidence,
            state=next_state,
            agent_task_id=agent_task_id,
        )
