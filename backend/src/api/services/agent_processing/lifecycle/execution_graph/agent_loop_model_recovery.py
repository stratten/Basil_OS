"""Model-call recovery for the inner agent loop: transient retries, empty generations, and context overflow."""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from api.core.logging.api_logger import api_logger

from ...shared.prompt_context_trimming import trim_oldest_context
from .agent_execution_core import ModelUnavailableBeforeFirstResponse
from .agent_executor_factory import _llm_output_log_fields
from .agent_loop_connection import ConnectionLostPause, ConnectionWait, is_connectivity_error
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

# Routine elision keeps long runs affordable well before the overflow-driven compaction levels apply
ROUTINE_COMPACTION_TRIGGER_TOKENS = 100_000
ROUTINE_KEEP_RECENT_RESULTS = 6
ELIDED_RESULT_HEAD_CHARS = 400
# The tool surface is rebuilt from these results, and a pending question must keep its answer intact
_NEVER_ELIDED_TOOLS = frozenset({"load_tool_family", "request_user_input"})


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


def _elided_text(message: ToolMessage) -> str:
    original = message_text(message.content)
    head = original[:ELIDED_RESULT_HEAD_CHARS]
    omitted = max(0, len(original) - len(head))
    return (
        f"[Earlier result trimmed: first {ELIDED_RESULT_HEAD_CHARS} characters follow]\n{head}\n"
        f"[{omitted} characters omitted; call the tool again if you need them.]"
    )


def apply_routine_elision(messages: list[BaseMessage], elided_call_ids: set[str]) -> list[BaseMessage]:
    """Request-only copy with the already-elided tool results replaced by their heads."""
    if not elided_call_ids:
        return messages
    return [
        message.model_copy(update={"content": _elided_text(message)})
        if isinstance(message, ToolMessage) and message.tool_call_id in elided_call_ids
        else message
        for message in messages
    ]


def _elision_candidates(messages: list[BaseMessage], already_elided: set[str]) -> list[ToolMessage]:
    tool_messages = [message for message in messages if isinstance(message, ToolMessage)]
    older = tool_messages[:-ROUTINE_KEEP_RECENT_RESULTS] if len(tool_messages) > ROUTINE_KEEP_RECENT_RESULTS else []
    return [
        message
        for message in older
        if message.tool_call_id not in already_elided
        and (message.name or "") not in _NEVER_ELIDED_TOOLS
        and len(message_text(message.content)) > ELIDED_RESULT_HEAD_CHARS * 2
    ]


def _system_text(request: Any) -> str:
    system_message = getattr(request, "system_message", None)
    if system_message is not None:
        return message_text(getattr(system_message, "content", ""))
    return str(getattr(request, "system_prompt", None) or "")


def _tool_fingerprint_part(tool: Any) -> str:
    if isinstance(tool, dict):
        return json.dumps(tool, sort_keys=True, default=str)
    schema = getattr(tool, "args_schema", None)
    try:
        schema_text = json.dumps(schema.model_json_schema(), sort_keys=True, default=str) if schema is not None and hasattr(schema, "model_json_schema") else str(schema)
    except Exception:
        schema_text = str(schema)
    return f"{getattr(tool, 'name', '')}|{getattr(tool, 'description', '')}|{schema_text}"


def prefix_fingerprint(request: Any) -> str:
    """Short hash of what the provider caches first: the system prompt and the bound tool definitions."""
    digest = hashlib.sha256()
    digest.update(_system_text(request).encode("utf-8", errors="replace"))
    for tool in list(getattr(request, "tools", None) or []):
        digest.update(b"\x1f")
        digest.update(_tool_fingerprint_part(tool).encode("utf-8", errors="replace"))
    return digest.hexdigest()[:12]


def _cache_read_tokens(message: Any) -> Optional[int]:
    usage = getattr(message, "usage_metadata", None) or {}
    details = usage.get("input_token_details") or {}
    value = details.get("cache_read")
    return value if isinstance(value, int) else None


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
        connection: Optional[ConnectionWait] = None,
        pause_when_connection_lost: bool = False,
    ) -> None:
        super().__init__()
        self.flags = flags
        # With a connection wait, a run that already made model calls waits out a network outage and then pauses with its progress saved, instead of failing
        self.connection = connection
        self.pause_when_connection_lost = pause_when_connection_lost
        self.completed_model_calls = completed_model_calls
        self.prompt_budget_tokens = prompt_budget_tokens
        self.context_window_tokens = context_window_tokens
        self.model_label = model_label
        self.compaction_level = 0
        self.backoff_base_seconds = 1.0
        self._overflow_tokens: tuple[Optional[int], Optional[int]] = (None, None)
        self._tool_chars_cache: dict[str, int] = {}
        self._previous_prefix: Optional[str] = None
        self._elided_call_ids: set[str] = set()

    def _elide_routinely(self, request: ModelRequest) -> None:
        """Once the prompt passes the trigger, elide every older result in one batch so the cached prefix changes rarely."""
        system_text = _system_text(request)
        tools = list(getattr(request, "tools", None) or [])
        messages = list(request.messages)
        tokens_before = estimate_prompt_tokens(
            apply_routine_elision(messages, self._elided_call_ids),
            system_text=system_text,
            tools=tools,
            tool_chars_cache=self._tool_chars_cache,
        )
        if tokens_before <= ROUTINE_COMPACTION_TRIGGER_TOKENS:
            return
        candidates = _elision_candidates(messages, self._elided_call_ids)
        if not candidates:
            return
        self._elided_call_ids.update(message.tool_call_id for message in candidates)
        tokens_after = estimate_prompt_tokens(
            apply_routine_elision(messages, self._elided_call_ids),
            system_text=system_text,
            tools=tools,
            tool_chars_cache=self._tool_chars_cache,
        )
        logger.info(
            "routine-elision count=%s tokens_before=%s tokens_after=%s",
            len(candidates),
            tokens_before,
            tokens_after,
        )

    def _compacted(self, request: ModelRequest) -> ModelRequest:
        elided = apply_routine_elision(list(request.messages), self._elided_call_ids)
        if self.compaction_level == 0:
            return request.override(messages=elided) if self._elided_call_ids else request
        actual_tokens, max_tokens = self._overflow_tokens
        return request.override(
            messages=compact_messages(
                elided,
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

    def _should_wait_for_connection(self, error: BaseException) -> bool:
        return (
            self.connection is not None
            and self.pause_when_connection_lost
            and self.completed_model_calls > 0
            and is_connectivity_error(error)
        )

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> Any:
        try:
            return await self._recovering_model_call(request, handler)
        finally:
            if self.connection is not None:
                self.connection.close()

    async def _recovering_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> Any:
        transient_attempts = 0
        empty_retried = False
        self._elide_routinely(request)
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
                is_transient = classification.kind in (TRANSIENT, TRANSIENT_EXHAUSTED)
                if is_transient and self._should_wait_for_connection(error):
                    if await self.connection.wait_before_retry(error):
                        continue
                    waited_seconds = self.connection.waited_seconds()
                    await self.connection.gave_up()
                    raise ConnectionLostPause(
                        error, model_label=self.model_label, waited_seconds=waited_seconds
                    ) from error
                if is_transient and transient_attempts < TRANSIENT_RETRIES:
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
                if is_transient and self.pause_when_connection_lost and self.completed_model_calls > 0:
                    raise ConnectionLostPause(error, model_label=self.model_label) from error
                raise
            if self.connection is not None:
                await self.connection.restored()
            self.completed_model_calls += 1
            try:
                last_ai = _last_ai_message(response)
                prefix = prefix_fingerprint(request)
                logger.info(
                    f"🔬 PIPELINE: model returned — {_llm_output_log_fields(last_ai)}, prefix={prefix}"
                )
                if self._previous_prefix is not None and _cache_read_tokens(last_ai) == 0:
                    if prefix == self._previous_prefix:
                        logger.warning("Prompt cache miss with an unchanged prefix (likely cache TTL expiry)")
                    else:
                        logger.warning(
                            "Prompt cache miss: prefix changed since the previous call (%s -> %s)",
                            self._previous_prefix,
                            prefix,
                        )
                self._previous_prefix = prefix
            except Exception as log_error:
                logger.debug("Model output logging failed: %s", log_error)
            return response
