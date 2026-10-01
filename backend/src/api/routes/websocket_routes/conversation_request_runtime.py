"""Ownership and cancellation state for BasilBoard Conversation requests."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ConversationRequestState:
    websocket: object
    request_id: str
    conversation_id: Optional[str]
    task: Optional[asyncio.Task] = None
    user_message_id: Optional[str] = None
    assistant_message_id: Optional[str] = None
    persistence_ready: bool = False
    cancel_requested: bool = False
    conversation_reservation_transferred: bool = False


ConversationWorker = Callable[[ConversationRequestState], Awaitable[None]]


class ConversationRequestRuntime:
    """Track in-flight Conversation requests and their durable-conversation ownership."""

    def __init__(self) -> None:
        self._requests: Dict[Tuple[int, str], ConversationRequestState] = {}
        self._agent_task_links: Dict[Tuple[int, str], str] = {}
        self._agent_task_link_keys: Dict[str, Tuple[int, str]] = {}
        self._conversation_owners: Dict[str, Tuple[int, str]] = {}
        self._conversation_agent_tasks: Dict[str, str] = {}
        self._agent_task_conversation: Dict[str, str] = {}

    @staticmethod
    def _key(websocket: object, request_id: str) -> Tuple[int, str]:
        return (id(websocket), request_id)

    def start(
        self,
        websocket: object,
        request_id: str,
        conversation_id: Optional[str],
        worker: ConversationWorker,
    ) -> bool:
        """Admit one request, atomically reserving its conversation ID if supplied."""
        key = self._key(websocket, request_id)
        if key in self._requests:
            return False
        if conversation_id is not None and conversation_id in self._conversation_owners:
            return False

        state = ConversationRequestState(
            websocket=websocket,
            request_id=request_id,
            conversation_id=conversation_id,
        )
        if conversation_id is not None:
            self._conversation_owners[conversation_id] = key

        async def run() -> None:
            try:
                await worker(state)
            except asyncio.CancelledError:
                logger.debug("Conversation request task canceled: %s", request_id)
            except Exception:
                logger.exception("Unhandled Conversation request failure: %s", request_id)
            finally:
                if self._requests.get(key) is state:
                    self._requests.pop(key, None)
                self._release_conversation_reservation(state)

        state.task = asyncio.create_task(run())
        self._requests[key] = state
        return True

    def _release_conversation_reservation(self, state: ConversationRequestState) -> None:
        """Free a direct request's conversation reservation unless it was transferred."""
        if state.conversation_reservation_transferred:
            return
        conversation_id = state.conversation_id
        if conversation_id is None:
            return
        key = self._key(state.websocket, state.request_id)
        if self._conversation_owners.get(conversation_id) == key:
            self._conversation_owners.pop(conversation_id, None)

    def is_conversation_active(self, conversation_id: str) -> bool:
        """Return whether a durable conversation currently has a reserved owner."""
        return conversation_id in self._conversation_owners

    def associate_conversation(
        self,
        state: ConversationRequestState,
        conversation_id: str,
    ) -> bool:
        """Reserve a newly known conversation ID exclusively for this request."""
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise ValueError("conversation_id must be a non-empty string")
        key = self._key(state.websocket, state.request_id)
        existing_owner = self._conversation_owners.get(conversation_id)
        if existing_owner is not None and existing_owner != key:
            return False
        state.conversation_id = conversation_id
        self._conversation_owners[conversation_id] = key
        return True

    def mark_persistence_ready(
        self,
        state: ConversationRequestState,
        user_message_id: str,
        assistant_message_id: str,
    ) -> None:
        state.user_message_id = user_message_id
        state.assistant_message_id = assistant_message_id
        state.persistence_ready = True
        if state.cancel_requested and state.task and not state.task.done():
            state.task.cancel()

    def request_cancel(
        self,
        websocket: object,
        request_id: str,
    ) -> Optional[ConversationRequestState]:
        state = self._requests.get(self._key(websocket, request_id))
        if state is None:
            return None
        state.cancel_requested = True
        if state.persistence_ready and state.task and not state.task.done():
            state.task.cancel()
        return state

    def request_cancel_for_conversation(
        self,
        conversation_id: str,
    ) -> Tuple[Optional[ConversationRequestState], Optional[str]]:
        """Resolve and cancel the active owner of one durable conversation, if any."""
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise ValueError("conversation_id must be a non-empty string")
        key = self._conversation_owners.get(conversation_id)
        state: Optional[ConversationRequestState] = None
        if key is not None:
            candidate = self._requests.get(key)
            if candidate is not None and candidate.conversation_id == conversation_id:
                candidate.cancel_requested = True
                if candidate.persistence_ready and candidate.task and not candidate.task.done():
                    candidate.task.cancel()
                state = candidate
        agent_task_id = self._conversation_agent_tasks.get(conversation_id)
        return state, agent_task_id

    async def cancel_for_websocket(self, websocket: object) -> None:
        states = [
            state
            for (websocket_id, _), state in list(self._requests.items())
            if websocket_id == id(websocket)
        ]
        tasks = []
        for state in states:
            state.cancel_requested = True
            if state.persistence_ready and state.task and not state.task.done():
                state.task.cancel()
                tasks.append(state.task)
            elif state.task and not state.task.done():
                tasks.append(state.task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def bind_agent_task(self, websocket: object, request_id: str, agent_task_id: str) -> None:
        """Record a durable Agent Task mapping that outlives this request's worker task."""
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id must be a non-empty string")
        if not isinstance(agent_task_id, str) or not agent_task_id.strip():
            raise ValueError("agent_task_id must be a non-empty string")
        key = self._key(websocket, request_id)
        previous_agent_task_id = self._agent_task_links.get(key)
        if previous_agent_task_id is not None:
            self._agent_task_link_keys.pop(previous_agent_task_id, None)
        previous_key = self._agent_task_link_keys.get(agent_task_id)
        if previous_key is not None:
            self._agent_task_links.pop(previous_key, None)
        self._agent_task_links[key] = agent_task_id
        self._agent_task_link_keys[agent_task_id] = key

        state = self._requests.get(key)
        conversation_id = state.conversation_id if state is not None else None
        if conversation_id is not None:
            if state is not None:
                state.conversation_reservation_transferred = True
            self._conversation_owners[conversation_id] = key
            self._conversation_agent_tasks[conversation_id] = agent_task_id
            self._agent_task_conversation[agent_task_id] = conversation_id

    def claim_agent_task_cancellation(self, websocket: object, request_id: str) -> Optional[str]:
        """Remove and return the Agent Task ID mapped to this socket/request pair, if any."""
        agent_task_id = self._agent_task_links.pop(self._key(websocket, request_id), None)
        if agent_task_id is not None:
            self._agent_task_link_keys.pop(agent_task_id, None)
        return agent_task_id

    def claim_agent_task_cancellation_for_conversation(self, conversation_id: str) -> Optional[str]:
        """Claim one Agent Task cancellation without releasing its conversation reservation."""
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise ValueError("conversation_id must be a non-empty string")
        agent_task_id = self._conversation_agent_tasks.get(conversation_id)
        if agent_task_id is None:
            return None
        key = self._agent_task_link_keys.pop(agent_task_id, None)
        if key is not None:
            self._agent_task_links.pop(key, None)
        return agent_task_id

    def agent_task_for_request(self, websocket: object, request_id: str) -> Optional[str]:
        """Return the linked Agent Task without releasing its narration ownership."""
        return self._agent_task_links.get(self._key(websocket, request_id))

    def release_agent_task(self, agent_task_id: str) -> None:
        """Drop a durable Agent Task mapping once its lifecycle reaches a terminal state."""
        key = self._agent_task_link_keys.pop(agent_task_id, None)
        if key is not None:
            self._agent_task_links.pop(key, None)
        conversation_id = self._agent_task_conversation.pop(agent_task_id, None)
        if conversation_id is not None:
            self._conversation_agent_tasks.pop(conversation_id, None)
            self._conversation_owners.pop(conversation_id, None)


conversation_request_runtime = ConversationRequestRuntime()
