"""Estimate prompt size against a model's context window so compaction can run before an overflow."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Sequence

from langchain_core.messages import BaseMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from api.core.logging.api_logger import api_logger

from .conversation_turns import message_text

logger = api_logger.getChild("context_window_budget")

CHARS_PER_TOKEN_ESTIMATE = 3.0
DEFAULT_OUTPUT_RESERVE_TOKENS = 4096
MIN_SAFETY_MARGIN_TOKENS = 512
SAFETY_MARGIN_RATIO = 0.05
MIN_PROMPT_BUDGET_TOKENS = 1024


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


async def resolve_context_window_tokens(llm: Any, context: Optional[Dict[str, Any]]) -> Optional[int]:
    """Best known context window for this run: the adapter's live answer, llama.cpp's n_ctx, then the registry."""
    resolver = getattr(llm, "aresolve_effective_context_window", None)
    if callable(resolver):
        try:
            window = _positive_int(await resolver())
        except Exception as exc:
            logger.debug("Context window lookup on the model adapter failed: %s", exc)
            window = None
        if window:
            return window
    llama = getattr(llm, "_llama_instance", None)
    n_ctx = getattr(llama, "n_ctx", None)
    if callable(n_ctx):
        try:
            window = _positive_int(n_ctx())
        except Exception:
            window = None
        if window:
            return window
    model_id = (context or {}).get("model_id") if isinstance(context, dict) else None
    if model_id:
        try:
            from api.core.models.models_registry.schema import get_model

            entry = get_model(str(model_id)) or {}
        except Exception as exc:
            logger.debug("Registry context window lookup failed for %s: %s", model_id, exc)
            entry = {}
        window = _positive_int(entry.get("context_window"))
        if window:
            return window
    return None


def model_display_label(llm: Any, context: Optional[Dict[str, Any]]) -> str:
    """The registry display name when known, so context-length messages name the model the user picked."""
    model_id = (context or {}).get("model_id") if isinstance(context, dict) else None
    if model_id:
        try:
            from api.core.models.models_registry.schema import get_model

            display_name = (get_model(str(model_id)) or {}).get("display_name")
        except Exception:
            display_name = None
        if display_name:
            return str(display_name)
        return str(model_id)
    return str(getattr(llm, "model_name", "") or getattr(llm, "model_identifier", "") or "")


CONTEXT_WINDOW_FIX_HINT = (
    "To continue, choose a model with a larger context window, or, for a custom model, raise its context window in Settings to match what its server can load."
)


def _context_window_shortfall(model_label: str, window_tokens: Any, actual_tokens: Any) -> str:
    model = model_label or "the selected model"
    window = _positive_int(window_tokens)
    actual = _positive_int(actual_tokens)
    window_text = f"{model}'s {window:,}-token context window" if window else f"{model}'s context window"
    needed_text = f" (it needed about {actual:,} tokens)" if actual else ""
    return f"this task needed more context than {window_text} holds{needed_text}"


def context_window_exceeded_message(
    *,
    model_label: str,
    window_tokens: Optional[int],
    actual_tokens: Optional[int],
    completed_steps: int,
) -> str:
    shortfall = _context_window_shortfall(model_label, window_tokens, actual_tokens)
    return (
        f"Stopped: {shortfall}, even after Basil removed older tool results. "
        f"{completed_steps} tool step(s) completed before it stopped. {CONTEXT_WINDOW_FIX_HINT}"
    )


def context_window_exceeded_reason(details: Dict[str, Any]) -> str:
    """The finalizer's outcome reason for a run the recovery middleware stopped on context overflow."""
    shortfall = _context_window_shortfall(
        str(details.get("model") or ""),
        details.get("max_tokens"),
        details.get("actual_tokens"),
    )
    return f"{shortfall[0].upper()}{shortfall[1:]}. {CONTEXT_WINDOW_FIX_HINT}"


def output_reserve_tokens(llm: Any, window: int) -> int:
    configured = _positive_int(getattr(llm, "max_tokens", None)) or DEFAULT_OUTPUT_RESERVE_TOKENS
    return max(0, min(configured, window // 4))


def prompt_budget_tokens(llm: Any, window: Optional[int]) -> Optional[int]:
    """Tokens the prompt may use: window minus the output reserve minus a safety margin."""
    window = _positive_int(window)
    if not window:
        return None
    margin = max(MIN_SAFETY_MARGIN_TOKENS, int(window * SAFETY_MARGIN_RATIO))
    return max(MIN_PROMPT_BUDGET_TOKENS, window - output_reserve_tokens(llm, window) - margin)


def _tool_schema_chars(tool: Any, cache: Optional[Dict[str, int]]) -> int:
    key = str(tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", "") or "")
    if cache is not None and key and key in cache:
        return cache[key]
    try:
        size = len(json.dumps(convert_to_openai_tool(tool), default=str))
    except Exception:
        size = len(str(getattr(tool, "description", "") or "")) + 200
    if cache is not None and key:
        cache[key] = size
    return size


def estimate_prompt_tokens(
    messages: Sequence[BaseMessage],
    *,
    system_text: str = "",
    tools: Sequence[Any] = (),
    tool_chars_cache: Optional[Dict[str, int]] = None,
) -> int:
    """Deliberately conservative: about 3 characters per token, counting text, tool calls, and tool schemas."""
    chars = len(system_text or "")
    for message in messages:
        chars += len(message_text(message.content))
        for call in getattr(message, "tool_calls", None) or []:
            chars += len(str(call.get("name") or "")) + len(json.dumps(call.get("args") or {}, default=str))
    for tool in tools or ():
        chars += _tool_schema_chars(tool, tool_chars_cache)
    return int(chars / CHARS_PER_TOKEN_ESTIMATE) + 1
