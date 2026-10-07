"""Classify model-call failures so each failure kind gets the recovery that fits it.

Recovery per kind, applied per model call by ``ModelRecoveryMiddleware`` in ``agent_loop_model_recovery``:
- context_overflow: compact older tool results in the model request, then stop with the completed steps.
- empty_generation: retry the model call once, then return a controlled empty result.
- transient_exhausted: a typed ``TransientModelError``; the model call is retried with jittered backoff.
- transient: an untyped network-shaped failure; the model call is retried after an exponential backoff.
- fatal: everything else, including authentication failures; never retried.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

from ...shared.prompt_context_trimming import parse_token_limit_error
from .llama_cpp_langchain_adapter import LocalModelContextWindowExceeded
from .model_errors import TRANSIENT_ERROR_TYPE_NAMES, TransientModelError, is_transient_error_text

CONTEXT_OVERFLOW = "context_overflow"
EMPTY_GENERATION = "empty_generation"
TRANSIENT_EXHAUSTED = "transient_exhausted"
TRANSIENT = "transient"
FATAL = "fatal"

EMPTY_GENERATION_MARKER = "No generation chunks were returned"

_OPENAI_CONTEXT_PATTERN = re.compile(
    r"maximum context length is (\d+) tokens.*?(?:resulted in|requested) (\d+) tokens",
    re.IGNORECASE | re.DOTALL,
)
_GEMINI_CONTEXT_PATTERN = re.compile(
    r"input token count \(?(\d+)\)? exceeds the maximum number of tokens allowed \(?(\d+)\)?",
    re.IGNORECASE,
)
_OVERFLOW_MARKERS = (
    "context_length_exceeded",
    "context length exceeded",
    "maximum context length",
    "context window",
    "prompt is too long",
    "input is too long",
    "too many tokens",
)


@dataclass(frozen=True)
class ModelErrorClassification:
    kind: str
    actual_tokens: Optional[int] = None
    max_tokens: Optional[int] = None


def parse_context_overflow(error_text: str) -> Optional[Tuple[Optional[int], Optional[int]]]:
    """Return ``(actual_tokens, max_tokens)`` for an overflow message, ``(None, None)`` when the counts are unknown, or None."""
    text = str(error_text or "")
    parsed = parse_token_limit_error(text)
    if parsed is not None:
        return parsed
    openai_match = _OPENAI_CONTEXT_PATTERN.search(text)
    if openai_match:
        return int(openai_match.group(2)), int(openai_match.group(1))
    gemini_match = _GEMINI_CONTEXT_PATTERN.search(text)
    if gemini_match:
        return int(gemini_match.group(1)), int(gemini_match.group(2))
    lowered = text.lower()
    if any(marker in lowered for marker in _OVERFLOW_MARKERS):
        return None, None
    return None


def is_transient_error(error: BaseException) -> bool:
    if type(error).__name__ in TRANSIENT_ERROR_TYPE_NAMES:
        return True
    return is_transient_error_text(str(error))


def classify_model_error(error: BaseException) -> ModelErrorClassification:
    if isinstance(error, LocalModelContextWindowExceeded):
        return ModelErrorClassification(CONTEXT_OVERFLOW, error.actual_tokens, error.max_tokens)
    text = str(error)
    if isinstance(error, ValueError) and EMPTY_GENERATION_MARKER in text:
        return ModelErrorClassification(EMPTY_GENERATION)
    overflow = parse_context_overflow(text)
    if overflow is not None:
        return ModelErrorClassification(CONTEXT_OVERFLOW, overflow[0], overflow[1])
    if isinstance(error, TransientModelError):
        return ModelErrorClassification(TRANSIENT_EXHAUSTED)
    if is_transient_error(error):
        return ModelErrorClassification(TRANSIENT)
    return ModelErrorClassification(FATAL)


def overflow_chars_to_remove(current_input: str, actual_tokens: Optional[int], max_tokens: Optional[int]) -> int:
    if actual_tokens is not None and max_tokens is not None:
        return (actual_tokens - max_tokens + 5000) * 4
    return max(len(current_input) // 4, 4000)


def overflow_token_summary(actual_tokens: Optional[int], max_tokens: Optional[int]) -> str:
    if actual_tokens is None or max_tokens is None:
        return ""
    return f" ({actual_tokens:,} > {max_tokens:,} tokens)"


__all__ = [
    "CONTEXT_OVERFLOW",
    "EMPTY_GENERATION",
    "FATAL",
    "ModelErrorClassification",
    "TRANSIENT",
    "TRANSIENT_EXHAUSTED",
    "classify_model_error",
    "is_transient_error",
    "overflow_chars_to_remove",
    "overflow_token_summary",
    "parse_context_overflow",
]
