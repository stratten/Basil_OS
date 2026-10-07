"""Typed model-call failures shared by the model adapters and the inner agent loop's model recovery."""

from __future__ import annotations


class TransientModelError(RuntimeError):
    """A model call failed in a way that is worth retrying unchanged after a backoff.

    Subclasses ``RuntimeError`` (not ``ValueError``) so ``classify_model_error`` never mistakes it for the "No generation chunks were returned" empty-generation ``ValueError``.
    """


LLM_RETRY_EXCEPTION_TYPES = (TransientModelError,)

TRANSIENT_ERROR_MARKERS = (
    "timeout",
    "timed out",
    "connection",
    "network",
    "broken pipe",
    "temporary failure",
    "temporarily unavailable",
    "service unavailable",
    "gateway timeout",
    "bad gateway",
    "socket",
    "dns",
    "name resolution",
    "eof",
    "end of file",
    "rate limit",
    "too many requests",
    "overloaded",
)

TRANSIENT_ERROR_TYPE_NAMES = frozenset(
    {
        "TimeoutError",
        "ConnectionError",
        "ConnectionResetError",
        "ConnectionRefusedError",
        "ConnectionAbortedError",
        "OSError",
    }
)


def is_transient_error_text(text: str) -> bool:
    """True when an error message has the shape of a network, overload, or rate-limit failure."""
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in TRANSIENT_ERROR_MARKERS)


__all__ = [
    "LLM_RETRY_EXCEPTION_TYPES",
    "TRANSIENT_ERROR_MARKERS",
    "TRANSIENT_ERROR_TYPE_NAMES",
    "TransientModelError",
    "is_transient_error_text",
]
