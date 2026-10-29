"""When an investigation may start. A pure function so every refusal reason is unit-tested."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from ..similarity import content_tokens, jaccard
from .models import (
    API_HANDLERS,
    AUTOMATIC_ORIGINS,
    DUPLICATE_QUESTION_SIMILARITY,
    MAX_CONCURRENT_API,
    MAX_CONCURRENT_LOCAL,
    MAX_RUNS_PER_MEETING,
)


@dataclass(frozen=True)
class StartDecision:
    allowed: bool
    reason: str = ""


def concurrency_limit_for(model: Any) -> int:
    """One run at a time for a local model, a small bounded number for an API model."""
    try:
        from api.core.models.reasoning.model_runtime_profile import resolve_runtime_model_profile

        handler = str(getattr(resolve_runtime_model_profile(model), "handler", "") or "")
    except Exception:
        return MAX_CONCURRENT_LOCAL
    return MAX_CONCURRENT_API if handler in API_HANDLERS else MAX_CONCURRENT_LOCAL


def decide_start(
    *,
    origin: str,
    question: str,
    capacity: str,
    enabled: bool,
    active_count: int,
    concurrency_limit: int,
    runs_started: int,
    prior_questions: Sequence[str],
    max_runs: int = MAX_RUNS_PER_MEETING,
) -> StartDecision:
    """Apply the start rules in a fixed order and return the first refusal, or an allowance."""
    if not enabled:
        return StartDecision(False, "The investigator is turned off for this meeting.")
    if capacity == "paused":
        return StartDecision(False, "The Companion is paused while transcription catches up, so it cannot investigate right now.")
    if capacity != "ok" and origin in AUTOMATIC_ORIGINS:
        return StartDecision(False, "The Companion is saving capacity while transcription catches up.")
    if runs_started >= max_runs:
        return StartDecision(False, f"This meeting has already used its {max_runs} investigations.")
    tokens = content_tokens(question)
    for earlier in prior_questions:
        if jaccard(tokens, content_tokens(earlier)) >= DUPLICATE_QUESTION_SIMILARITY:
            return StartDecision(False, "That has already been investigated in this meeting.")
    if active_count >= concurrency_limit:
        return StartDecision(False, "The investigator is busy with another question. Try again when it finishes.")
    return StartDecision(True)
