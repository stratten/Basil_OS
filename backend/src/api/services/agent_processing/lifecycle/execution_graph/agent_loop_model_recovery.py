"""Model-call recovery for the inner agent loop: transient retries, empty generations, and context overflow."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from api.core.logging.api_logger import api_logger

from ...shared.prompt_context_trimming import trim_oldest_context
from .agent_execution_core import ModelUnavailableBeforeFirstResponse
from .agent_executor_factory import _llm_output_log_fields
from .context_window_budget import context_window_exceeded_message, estimate_prompt_tokens
from .conversation_turns import message_text, render_thread_recap, turn_input_index
from .model_error_policy import (
    CONTEXT_OVERFLOW,
    EMPTY_GENERATION,
    TRANSIENT,
    TRANSIENT_EXHAUSTED,
    classify_model_error,
    overflow_chars_to_remove,
    overflow_token_summary,
)

logger = api_logger.getChild("agent_loop_model_recovery")

EMPTY_GENERATION_MESSAGE = "The agent returned no response after a retry."
COMPACTED_TOOL_RESULT = "[Earlier tool result removed to fit the model's context window.]"
TRANSIENT_RETRIES = 2
MAX_COMPACTION_LEVEL = 2
THREAD_COMPACTION_LEVEL = 3
_RECENT_TOOL_RESULTS_BY_LEVEL = {1: 3, 2: 1, 3: 1}


@dataclass
class AgentRunFlags:
    """Terminal conditions the recovery middleware reports back to the runner."""

    empty_generation_failure: bool = False
    context_window_exceeded: Optional[dict[str, Any]] = None

    def terminal(self) -> bool:
        return self.empty_generation_failure or self.context_window_exceeded is not None

    def as_result_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if self.empty_generation_failure:
            fields["empty_generation_failure"] = True
        if self.context_window_exceeded is not None:
            fields["context_window_exceeded"] = dict(self.context_window_exceeded)
        return fields


def max_compaction_level(messages: list[BaseMessage]) -> int:
    """Level 3 exists only when earlier turns precede the current request."""
    return THREAD_COMPACTION_LEVEL if turn_input_index(messages) else MAX_COMPACTION_LEVEL


def _trim_target_index(messages: list[BaseMessage]) -> Optional[int]:
    index = turn_input_index(messages)
    if index is not None:
        return index if isinstance(messages[index].content, str) else None
    for position, message in enumerate(messages):
        if isinstance(message, HumanMessage) and isinstance(message.content, str):
            return position
    return None


def _condense_prior_turns(messages: list[BaseMessage]) -> list[BaseMessage]:
    index = turn_input_index(messages)
    if not index:
        return messages
    turn_input = messages[index]
    recap = render_thread_recap(messages[:index])
    content = message_text(turn_input.content)
    condensed = turn_input.model_copy(update={"content": f"{recap}\n\n{content}" if recap else content})
    return [condensed, *messages[index + 1:]]


def compact_messages(
    messages: list[BaseMessage],
    level: int,
    *,
    actual_tokens: Optional[int] = None,
    max_tokens: Optional[int] = None,
) -> list[BaseMessage]:
    """Request-only copy: older tool results replaced; level 2 trims the current request; level 3 condenses earlier turns."""
    keep = _RECENT_TOOL_RESULTS_BY_LEVEL[level]
    tool_indexes = [index for index, message in enumerate(messages) if isinstance(message, ToolMessage)]
    stale_indexes = set(tool_indexes[:-keep]) if len(tool_indexes) > keep else set()
    trim_index = _trim_target_index(messages) if level >= 2 else None
    compacted: list[BaseMessage] = []
    for index, message in enumerate(messages):
        if index in stale_indexes:
            compacted.append(message.model_copy(update={"content": COMPACTED_TOOL_RESULT}))
            continue
        if index == trim_index:
            chars_to_remove = overflow_chars_to_remove(message.content, actual_tokens, max_tokens)
            trimmed = trim_oldest_context(message.content, chars_to_remove, logger)
            compacted.append(message.model_copy(update={"content": trimmed}) if trimmed else message)
            continue
        compacted.append(message)
    if level >= THREAD_COMPACTION_LEVEL:
        compacted = _condense_prior_turns(compacted)
    return compacted


def _system_text(request: Any) -> str:
    system_message = getattr(request, "system_message", None)
    if system_message is not None:
        return message_text(getattr(system_message, "content", ""))
    return str(getattr(request, "system_prompt", None) or "")


def _last_ai_message(response: Any) -> Any:
    if isinstance(response, AIMessage):
        return response
    for message in reversed(list(getattr(response, "result", None) or [])):
        if isinstance(message, AIMessage):
            return message
    return None


def _is_model_unreachable(error: BaseException) -> bool:
    from api.services.model_usage_service import is_model_unreachable_error

    return bool(is_model_unreachable_error(error))


class ModelRecoveryMiddleware(AgentMiddleware):
    """Retry, compact, or stop a failing model call without re-running completed tools."""

    def __init__(
        self,
        flags: AgentRunFlags,
        *,
        completed_model_calls: int = 0,
        prompt_budget_tokens: Optional[int] = None,
        context_window_tokens: Optional[int] = None,
        model_label: str = "",
    ) -> None:
        super().__init__()
        self.flags = flags
        self.completed_model_calls = completed_model_calls
        self.prompt_budget_tokens = prompt_budget_tokens
        self.context_window_tokens = context_window_tokens
        self.model_label = model_label
        self.compaction_level = 0
        self.backoff_base_seconds = 1.0
        self._overflow_tokens: tuple[Optional[int], Optional[int]] = (None, None)
        self._tool_chars_cache: dict[str, int] = {}

    def _compacted(self, request: ModelRequest) -> ModelRequest:
        if self.compaction_level == 0:
            return request
        actual_tokens, max_tokens = self._overflow_tokens
        return request.override(
            messages=compact_messages(
                list(request.messages),
                self.compaction_level,
                actual_tokens=actual_tokens,
                max_tokens=max_tokens,
            )
        )

    def _max_level(self, request: ModelRequest) -> int:
        return max_compaction_level(list(request.messages))

    def _compact_proactively(self, request: ModelRequest) -> None:
        if not self.prompt_budget_tokens:
            return
        max_level = self._max_level(request)
        system_text = _system_text(request)
        tools = list(getattr(request, "tools", None) or [])
        while True:
            estimate = estimate_prompt_tokens(
                self._compacted(request).messages,
                system_text=system_text,
                tools=tools,
                tool_chars_cache=self._tool_chars_cache,
            )
            if estimate <= self.prompt_budget_tokens or self.compaction_level >= max_level:
                return
            self.compaction_level += 1
            logger.warning(
                "⚠️ Prompt estimate %s tokens exceeds the %s-token budget; compacting proactively (level %s/%s)",
                estimate,
                self.prompt_budget_tokens,
                self.compaction_level,
                max_level,
            )

    def _backoff_seconds(self, kind: str, attempt: int) -> float:
        seconds = self.backoff_base_seconds * (2 ** attempt)
        if kind == TRANSIENT_EXHAUSTED:
            seconds *= 0.5 + random.random()
        return seconds

    def _context_exceeded_message(self, request: ModelRequest) -> AIMessage:
        actual_tokens, max_tokens = self._overflow_tokens
        window_tokens = max_tokens or self.context_window_tokens
        completed_steps = sum(1 for message in request.messages if isinstance(message, ToolMessage))
        message = context_window_exceeded_message(
            model_label=self.model_label,
            window_tokens=window_tokens,
            actual_tokens=actual_tokens,
            completed_steps=completed_steps,
        )
        self.flags.context_window_exceeded = {
            "actual_tokens": actual_tokens,
            "max_tokens": window_tokens,
            "model": self.model_label,
            "completed_steps": completed_steps,
            "compaction_attempts": self.compaction_level,
            "message": message,
        }
        return AIMessage(content=message)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> Any:
        transient_attempts = 0
        empty_retried = False
        self._compact_proactively(request)
        while True:
            try:
                response = await handler(self._compacted(request))
            except Exception as error:
                classification = classify_model_error(error)
                if classification.kind == EMPTY_GENERATION:
                    if not empty_retried:
                        empty_retried = True
                        logger.warning("⚠️ STREAMING EMPTY: retrying the model call once")
                        continue
                    logger.error("❌ STREAMING EMPTY: the retried model call also returned no generation")
                    self.flags.empty_generation_failure = True
                    return AIMessage(content=EMPTY_GENERATION_MESSAGE)
                if classification.kind == CONTEXT_OVERFLOW:
                    self._overflow_tokens = (classification.actual_tokens, classification.max_tokens)
                    token_summary = overflow_token_summary(*self._overflow_tokens)
                    max_level = self._max_level(request)
                    if self.compaction_level < max_level:
                        self.compaction_level += 1
                        logger.warning(
                            "⚠️ Prompt too long%s; compacting older tool results (level %s/%s)",
                            token_summary,
                            self.compaction_level,
                            max_level,
                        )
                        continue
                    logger.error("❌ Context window exceeded after %s compaction level(s)%s", self.compaction_level, token_summary)
                    return self._context_exceeded_message(request)
                if classification.kind in (TRANSIENT, TRANSIENT_EXHAUSTED) and transient_attempts < TRANSIENT_RETRIES:
                    backoff_seconds = self._backoff_seconds(classification.kind, transient_attempts)
                    transient_attempts += 1
                    logger.warning(
                        "⚠️ Transient model error (attempt %s/%s): %s. Retrying after %.1fs",
                        transient_attempts,
                        TRANSIENT_RETRIES,
                        str(error)[:200],
                        backoff_seconds,
                    )
                    await asyncio.sleep(backoff_seconds)
                    continue
                if self.completed_model_calls == 0 and _is_model_unreachable(error):
                    raise ModelUnavailableBeforeFirstResponse(error) from error
                raise
            self.completed_model_calls += 1
            try:
                logger.info(f"🔬 PIPELINE: model returned — {_llm_output_log_fields(_last_ai_message(response))}")
            except Exception as log_error:
                logger.debug("Model output logging failed: %s", log_error)
            return response
