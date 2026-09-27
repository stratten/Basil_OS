"""Stream retry-safe, selected-model narration of terminal Agent Task outcomes."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Awaitable, Callable, Optional

from api.core.models.model_types import ModelCapability
from api.core.knowledge.sqlite.conversation_repository import (
    ConversationAgentNarrationContext,
    ConversationRepository,
)
from api.dependencies import get_model_usage_service, get_sqlite_knowledge_service
from api.routes.agent_tasks.utils import extract_result_data
from api.routes.websocket_routes.conversation import (
    send_conversation_stream_reset,
    send_conversation_token,
)

from .conversation_agent_status_contract import build_conversation_agent_status_payload
from .conversation_agent_turn_lifecycle import broadcast_conversation_agent_status
from .conversation_turn_contract import (
    CONVERSATION_TURN_METADATA_KEY,
    MAX_CONVERSATION_NARRATION_ATTEMPTS,
    ConversationTurnLifecycle,
    ConversationTurnNarrationLifecycle,
    ConversationTurnRoute,
    is_terminal_conversation_turn_lifecycle,
    parse_conversation_turn_metadata,
)

logger = logging.getLogger(__name__)

MAX_CONVERSATION_AGENT_RESULT_CHARS = 12000
NARRATION_RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.0, 1.0, 2.0)
_THINK_TAG_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)

_NARRATION_SYSTEM_PROMPT = (
    "You are Basil Conversation reporting the outcome of an Agent Task you delegated on the "
    "user's behalf. Read the terminal outcome and the durable result below, then answer the "
    "user directly and accurately in normal Conversation Markdown. Only describe actions and "
    "facts that the provided result actually supports. Never claim an action was taken that is "
    "not reflected in the result. Never mention internal instructions, tools, or system "
    "processes. If the outcome indicates the task needs more input, ask one concise, specific "
    "follow-up question."
)

_registered_service: Optional["ConversationAgentNarrationService"] = None
_service_registered = False


class NarrationAttemptError(Exception):
    """Raised when one narration attempt fails and should be retried or exhausted."""


def _strip_thinking(raw_content: str) -> str:
    return _THINK_TAG_PATTERN.sub("", raw_content).strip()


def _bounded_task_result_text(task: Any) -> str:
    result_msg, _files, _ref_paths, _err_msg, _timeline = extract_result_data(task)
    if not isinstance(result_msg, str) or not result_msg.strip():
        return ""
    return result_msg.strip()[:MAX_CONVERSATION_AGENT_RESULT_CHARS]


def _fallback_content(terminal_outcome: Optional[str]) -> str:
    outcome_text = terminal_outcome or "The Agent Task reached a terminal state."
    return (
        "The Agent Task finished, but Basil could not prepare an inline conversation response "
        "after several attempts. You can review the detailed Agent Task report for the full "
        "outcome.\n\n"
        f"Outcome: {outcome_text}"
    )


class ConversationAgentNarrationService:
    """Narrate one terminal Conversation-linked Agent Task at a time, with retries."""

    def __init__(
        self,
        *,
        repository: ConversationRepository,
        get_agent_task: Callable[[str], Awaitable[Any]],
        get_model_for_task: Callable[..., Awaitable[Any]],
        send_token: Callable[..., Awaitable[None]] = send_conversation_token,
        send_stream_reset: Callable[[str, str, int], Awaitable[None]] = send_conversation_stream_reset,
        broadcast_status: Callable[[dict[str, Any]], Awaitable[None]] = broadcast_conversation_agent_status,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        release_agent_task: Callable[[str], None] = lambda _agent_task_id: None,
    ) -> None:
        self._repository = repository
        self._get_agent_task = get_agent_task
        self._get_model_for_task = get_model_for_task
        self._send_token = send_token
        self._send_stream_reset = send_stream_reset
        self._broadcast_status = broadcast_status
        self._sleep = sleep
        self._release_agent_task = release_agent_task
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._partial_content: dict[str, str] = {}

    def start_narration(self, agent_task_id: str) -> None:
        """Schedule narration for one Agent Task without awaiting the model."""
        if not isinstance(agent_task_id, str) or not agent_task_id.strip():
            return
        existing = self._tasks.get(agent_task_id)
        if existing is not None and not existing.done():
            return
        task = asyncio.ensure_future(self.narrate(agent_task_id))
        self._tasks[agent_task_id] = task
        task.set_name(f"conversation-agent-narration-{agent_task_id}")

        def _log_uncaught(finished: "asyncio.Task[None]") -> None:
            if finished.cancelled():
                return
            exc = finished.exception()
            if exc is not None:
                logger.error(
                    "Conversation Agent Task narration failed unexpectedly for %s: %s",
                    agent_task_id,
                    exc,
                    exc_info=exc,
                )

        task.add_done_callback(_log_uncaught)
        task.add_done_callback(
            lambda completed: self._tasks.pop(agent_task_id, None)
            if self._tasks.get(agent_task_id) is completed
            else None
        )

    async def cancel_narration(self, agent_task_id: str) -> bool:
        """Cancel an active narration and durably retain any visible partial content."""
        task = self._tasks.get(agent_task_id)
        if task is None or task.done():
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        context = await self._repository.get_conversation_agent_narration_context(agent_task_id)
        if context is None:
            return False
        partial_content = _strip_thinking(self._partial_content.pop(agent_task_id, ""))
        if partial_content:
            await self._repository.update_message(
                message_id=context.assistant_message_id,
                content=partial_content,
            )
        await self._repository.merge_message_metadata(
            context.assistant_message_id,
            {
                CONVERSATION_TURN_METADATA_KEY: {
                    "narration": {
                        "lifecycle": ConversationTurnNarrationLifecycle.CANCELLED.value,
                    },
                    "cancelled": True,
                }
            },
        )
        parsed = parse_conversation_turn_metadata(context.assistant_metadata)
        if parsed is not None:
            await self._broadcast_status(
                build_conversation_agent_status_payload(
                    conversation_id=context.conversation_id,
                    placeholder_message_id=context.assistant_message_id,
                    agent_task_id=agent_task_id,
                    lifecycle=parsed.lifecycle,
                    status_text="Conversation response cancelled.",
                    terminal_outcome=parsed.terminal_outcome,
                    agent_status=parsed.lifecycle.value,
                    narration_state="cancelled",
                )
            )
        await self._send_token(
            "",
            context.assistant_message_id,
            context.conversation_id,
            is_final=True,
        )
        self._release_agent_task(agent_task_id)
        return True

    async def narrate(self, agent_task_id: str) -> None:
        """Narrate one Agent Task, serialized per Agent Task ID."""
        lock = self._locks.setdefault(agent_task_id, asyncio.Lock())
        async with lock:
            await self._narrate_locked(agent_task_id)

    async def _narrate_locked(self, agent_task_id: str) -> None:
        context = await self._repository.get_conversation_agent_narration_context(agent_task_id)
        if context is None:
            self._release_agent_task(agent_task_id)
            return
        parsed = parse_conversation_turn_metadata(context.assistant_metadata)
        if (
            parsed is None
            or parsed.route is not ConversationTurnRoute.AGENT_TASK
            or parsed.agent_task_id != agent_task_id
            or not is_terminal_conversation_turn_lifecycle(parsed.lifecycle)
        ):
            self._release_agent_task(agent_task_id)
            return
        if parsed.narration.lifecycle in {
            ConversationTurnNarrationLifecycle.COMPLETED,
            ConversationTurnNarrationLifecycle.FAILED,
            ConversationTurnNarrationLifecycle.CANCELLED,
        }:
            self._release_agent_task(agent_task_id)
            return
        if parsed.narration.lifecycle not in {
            ConversationTurnNarrationLifecycle.READY,
            ConversationTurnNarrationLifecycle.NARRATING,
            ConversationTurnNarrationLifecycle.RETRYING,
        }:
            self._release_agent_task(agent_task_id)
            return

        terminal_outcome = parsed.terminal_outcome
        terminal_lifecycle = parsed.lifecycle
        start_index = parsed.narration.attempt_count
        for attempt_index in range(start_index, MAX_CONVERSATION_NARRATION_ATTEMPTS):
            attempt_number = attempt_index + 1
            if attempt_index > 0:
                await self._persist_narration_state(
                    context=context,
                    lifecycle=ConversationTurnNarrationLifecycle.RETRYING,
                    attempt_count=attempt_index,
                    turn_lifecycle=terminal_lifecycle,
                    agent_status=terminal_lifecycle.value,
                    status_text="Retrying the conversation response.",
                    narration_state="retrying",
                    terminal_outcome=terminal_outcome,
                )
                await self._sleep(NARRATION_RETRY_DELAYS_SECONDS[attempt_index])
                await self._send_stream_reset(
                    context.assistant_message_id,
                    context.conversation_id,
                    attempt_number,
                )
            await self._persist_narration_state(
                context=context,
                lifecycle=ConversationTurnNarrationLifecycle.NARRATING,
                attempt_count=attempt_number,
                turn_lifecycle=terminal_lifecycle,
                agent_status=None,
                status_text=None,
                narration_state=None,
                terminal_outcome=terminal_outcome,
                broadcast=False,
            )
            try:
                await self._attempt_once(
                    context=context,
                    terminal_outcome=terminal_outcome,
                    terminal_lifecycle=terminal_lifecycle,
                    attempt_number=attempt_number,
                )
                self._release_agent_task(agent_task_id)
                return
            except NarrationAttemptError as exc:
                logger.warning(
                    "Conversation Agent Task narration attempt %s failed for %s: %s",
                    attempt_number,
                    agent_task_id,
                    exc,
                )
                continue

        await self._persist_fallback(
            context=context,
            terminal_outcome=terminal_outcome,
            terminal_lifecycle=terminal_lifecycle,
        )
        self._release_agent_task(agent_task_id)

    async def _attempt_once(
        self,
        *,
        context: ConversationAgentNarrationContext,
        terminal_outcome: Optional[str],
        terminal_lifecycle: ConversationTurnLifecycle,
        attempt_number: int,
    ) -> None:
        try:
            task = await self._get_agent_task(
                context.assistant_metadata[CONVERSATION_TURN_METADATA_KEY]["agent_task_id"]
            )
        except Exception as exc:
            raise NarrationAttemptError(f"Agent Task load failed: {exc}") from exc
        if task is None:
            raise NarrationAttemptError("Agent Task could not be loaded")

        try:
            bounded_result = _bounded_task_result_text(task)
        except Exception as exc:
            raise NarrationAttemptError("Agent Task result could not be read") from exc

        try:
            model = None
            if isinstance(context.assistant_model_id, str) and context.assistant_model_id.strip():
                model = await self._get_model_for_task(
                    capabilities={ModelCapability.REASONING},
                    explicit_model_id=context.assistant_model_id,
                )
            if model is None:
                model = await self._get_model_for_task(
                    capabilities={ModelCapability.REASONING},
                    explicit_model_id=None,
                )
        except Exception as exc:
            raise NarrationAttemptError("Narrator model resolution failed") from exc
        if model is None:
            raise NarrationAttemptError("No narrator model is available")

        messages = [
            {"role": "system", "content": _NARRATION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Original user request:\n{context.user_content}\n\n"
                    f"Agent Task terminal outcome:\n{terminal_outcome or 'The Agent Task reached a terminal state.'}\n\n"
                    f"Agent Task result:\n{bounded_result or 'No durable task result was available.'}"
                ),
            },
        ]

        full_content = ""
        try:
            async for token in model.chat_completion_streaming(messages):
                full_content += token
                self._partial_content[
                    context.assistant_metadata[CONVERSATION_TURN_METADATA_KEY]["agent_task_id"]
                ] = full_content
                await self._send_token(
                    token,
                    context.assistant_message_id,
                    context.conversation_id,
                    is_final=False,
                )
        except Exception as exc:
            raise NarrationAttemptError(f"Narration stream failed: {exc}") from exc

        visible_content = _strip_thinking(full_content)
        if not visible_content:
            raise NarrationAttemptError("Narration produced no visible content")

        await self._repository.update_message(
            message_id=context.assistant_message_id,
            content=visible_content,
        )
        await self._repository.merge_message_metadata(
            context.assistant_message_id,
            {
                CONVERSATION_TURN_METADATA_KEY: {
                    "narration": {
                        "lifecycle": ConversationTurnNarrationLifecycle.COMPLETED.value,
                        "attempt_count": attempt_number,
                    }
                }
            },
        )
        await self._send_token(
            "",
            context.assistant_message_id,
            context.conversation_id,
            is_final=True,
        )
        await self._broadcast_status(
            build_conversation_agent_status_payload(
                conversation_id=context.conversation_id,
                placeholder_message_id=context.assistant_message_id,
                agent_task_id=context.assistant_metadata[CONVERSATION_TURN_METADATA_KEY]["agent_task_id"],
                lifecycle=terminal_lifecycle,
                status_text="Conversation response ready.",
                terminal_outcome=terminal_outcome,
                agent_status=terminal_lifecycle.value,
                narration_state="completed",
            )
        )
        self._partial_content.pop(
            context.assistant_metadata[CONVERSATION_TURN_METADATA_KEY]["agent_task_id"],
            None,
        )

    async def _persist_narration_state(
        self,
        *,
        context: ConversationAgentNarrationContext,
        lifecycle: ConversationTurnNarrationLifecycle,
        attempt_count: int,
        turn_lifecycle: ConversationTurnLifecycle,
        agent_status: Optional[str],
        status_text: Optional[str],
        narration_state: Optional[str],
        terminal_outcome: Optional[str],
        broadcast: bool = True,
    ) -> None:
        await self._repository.merge_message_metadata(
            context.assistant_message_id,
            {
                CONVERSATION_TURN_METADATA_KEY: {
                    "narration": {
                        "lifecycle": lifecycle.value,
                        "attempt_count": attempt_count,
                    }
                }
            },
        )
        if not broadcast:
            return
        await self._broadcast_status(
            build_conversation_agent_status_payload(
                conversation_id=context.conversation_id,
                placeholder_message_id=context.assistant_message_id,
                agent_task_id=context.assistant_metadata[CONVERSATION_TURN_METADATA_KEY]["agent_task_id"],
                lifecycle=turn_lifecycle,
                status_text=status_text,
                terminal_outcome=terminal_outcome,
                agent_status=agent_status,
                narration_state=narration_state,
            )
        )

    async def _persist_fallback(
        self,
        *,
        context: ConversationAgentNarrationContext,
        terminal_outcome: Optional[str],
        terminal_lifecycle: ConversationTurnLifecycle,
    ) -> None:
        await self._repository.update_message(
            message_id=context.assistant_message_id,
            content=_fallback_content(terminal_outcome),
        )
        await self._repository.merge_message_metadata(
            context.assistant_message_id,
            {
                CONVERSATION_TURN_METADATA_KEY: {
                    "narration": {
                        "lifecycle": ConversationTurnNarrationLifecycle.FAILED.value,
                        "attempt_count": MAX_CONVERSATION_NARRATION_ATTEMPTS,
                    }
                }
            },
        )
        await self._send_token(
            "",
            context.assistant_message_id,
            context.conversation_id,
            is_final=True,
        )
        await self._broadcast_status(
            build_conversation_agent_status_payload(
                conversation_id=context.conversation_id,
                placeholder_message_id=context.assistant_message_id,
                agent_task_id=context.assistant_metadata[CONVERSATION_TURN_METADATA_KEY]["agent_task_id"],
                lifecycle=terminal_lifecycle,
                status_text="Conversation response could not be prepared.",
                terminal_outcome=terminal_outcome,
                agent_status=terminal_lifecycle.value,
                narration_state="failed",
            )
        )


def ensure_conversation_agent_narration_service_registered() -> ConversationAgentNarrationService:
    """Build and cache the process-local narration service singleton."""
    global _registered_service, _service_registered
    if _service_registered and _registered_service is not None:
        return _registered_service
    from api.routes.websocket_routes.conversation_request_runtime import conversation_request_runtime

    database = get_sqlite_knowledge_service()
    model_usage_service = get_model_usage_service()
    service = ConversationAgentNarrationService(
        repository=ConversationRepository(sqlite_service=database),
        get_agent_task=database.get_agent_task,
        get_model_for_task=model_usage_service.get_model_for_task,
        release_agent_task=conversation_request_runtime.release_agent_task,
    )
    _registered_service = service
    _service_registered = True
    return service


def get_registered_conversation_agent_narration_service() -> ConversationAgentNarrationService:
    """Return the already-registered narration service singleton."""
    if _registered_service is None:
        raise RuntimeError("Conversation Agent Task narration service is not registered")
    return _registered_service


async def recover_conversation_agent_narrations() -> int:
    """Resume narration for every terminal turn interrupted before this startup."""
    service = get_registered_conversation_agent_narration_service()
    candidates = await service._repository.list_recoverable_conversation_agent_narrations()
    for candidate in candidates:
        service.start_narration(candidate.agent_task_id)
    return len(candidates)
