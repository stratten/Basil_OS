"""Typed failure for a local llama.cpp model that cannot decode, and the recovery options it offers.

llama-cpp-python raises a bare ``RuntimeError("llama_decode returned N")`` when the native decode step fails.
The code N is what separates a context that is too large for this Mac's memory from a prompt that does not fit, so the codes are parsed here once and every surface (retry logic, setup assistant, conversation) reads the same classification.

llama.cpp return codes: 1 means no KV slot was found (the prompt does not fit the context), -1 means the batch was invalid, and anything below -1 is a fatal compute failure, which on Metal is almost always memory exhaustion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

_DECODE_PATTERN = re.compile(r"llama_decode returned (-?\d+)")


class LocalModelFailureKind(str, Enum):
    """Why a local model could not decode."""

    MEMORY = "memory"
    CONTEXT_FULL = "context_full"
    INVALID_INPUT = "invalid_input"


@dataclass(frozen=True)
class DecodeFailure:
    """A parsed ``llama_decode`` failure."""

    code: int
    kind: LocalModelFailureKind


class LocalModelDecodeError(RuntimeError):
    """A local model failed to decode, after any automatic retry was exhausted or ruled out."""

    def __init__(
        self,
        *,
        code: int,
        kind: LocalModelFailureKind,
        model_name: str,
        n_ctx: Optional[int],
        retried_at_context: Optional[int] = None,
    ) -> None:
        self.code = code
        self.kind = kind
        self.model_name = model_name
        self.n_ctx = n_ctx
        self.retried_at_context = retried_at_context
        super().__init__(user_message_for(kind, model_name, retried=retried_at_context is not None))


def parse_decode_failure(exc: BaseException) -> Optional[DecodeFailure]:
    """Classify an exception as a decode failure, or return None when it is some other error.

    Return code 2 means the decode was aborted on purpose, so it is not a failure.
    """

    match = _DECODE_PATTERN.search(str(exc))
    if match is None:
        return None
    code = int(match.group(1))
    if code == 1:
        return DecodeFailure(code, LocalModelFailureKind.CONTEXT_FULL)
    if code == -1:
        return DecodeFailure(code, LocalModelFailureKind.INVALID_INPUT)
    if code <= -2:
        return DecodeFailure(code, LocalModelFailureKind.MEMORY)
    return None


def user_message_for(kind: LocalModelFailureKind, model_name: str, *, retried: bool = False) -> str:
    """Plain-language explanation shown to the user, with no internal field names.

    ``retried`` is True only when Basil really did reload the model with a smaller working memory, so the message never claims a retry that did not happen.
    """

    if kind is LocalModelFailureKind.MEMORY:
        retry_note = "Basil already tried again with a smaller working memory. " if retried else ""
        return (
            f"Your Mac ran out of memory while running {model_name}. "
            f"{retry_note}"
            "You can try again, switch to a smaller model, use Basil Cloud or your own API key, or send us a report."
        )
    if kind is LocalModelFailureKind.CONTEXT_FULL:
        return (
            f"That request was too long for {model_name} to hold in memory at once. "
            "Try a shorter request, switch to a smaller model, or use Basil Cloud or your own API key."
        )
    return (
        f"{model_name} could not read that request. "
        "Try again, or send us a report if it keeps happening."
    )


def recovery_actions(kind: LocalModelFailureKind) -> List[Dict[str, str]]:
    """The actions the UI offers, in order. Every kind offers retry, show logs and report; memory and context failures also offer a smaller model and a cloud route."""

    actions = [{"id": "retry", "label": "Try again"}]
    if kind is not LocalModelFailureKind.INVALID_INPUT:
        actions.append({"id": "smaller_model", "label": "Use a smaller model"})
        actions.append({"id": "cloud_or_key", "label": "Use Basil Cloud or an API key"})
    actions.append({"id": "show_logs", "label": "Show logs"})
    actions.append({"id": "report", "label": "Report a problem"})
    return actions


def find_local_model_failure(exc: Optional[BaseException]) -> Optional[LocalModelDecodeError]:
    """Return the LocalModelDecodeError in an exception's cause chain, or None."""

    seen: set[int] = set()
    current = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, LocalModelDecodeError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


def failure_payload(error: LocalModelDecodeError) -> Dict[str, Any]:
    """JSON-safe description of a failure for event streams and HTTP responses.

    ``detail`` carries the numeric code for the diagnostics bundle and never contains prompt or conversation text.
    """

    return {
        "type": "local_model_failure",
        "kind": error.kind.value,
        "message": str(error),
        "detail": f"llama_decode returned {error.code} with a context of {error.n_ctx} tokens",
        "retried_at_context": error.retried_at_context,
        "actions": recovery_actions(error.kind),
    }
