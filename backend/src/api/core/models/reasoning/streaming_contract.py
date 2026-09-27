"""Shared streaming and generation-budget contracts for reasoning models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional

from .model_runtime_profile import resolve_runtime_model_profile

GenerationPurpose = Literal[
    "decision",
    "structured",
    "narrative",
    "activity_analysis",
    "general",
    "agent_execution",
    "final_synthesis",
]
StreamTerminalReason = Literal[
    "completed",
    "max_tokens",
    "length",
    "cancelled",
    "safety",
    "error",
    "unknown",
]


@dataclass(frozen=True)
class GenerationBudget:
    """Resolved token budget for a single model call."""

    purpose: GenerationPurpose
    requested_output_tokens: int
    effective_output_tokens: int
    input_budget_tokens: Optional[int]
    reserved_output_tokens: int
    model_id: str
    context_window: Optional[int]
    model_max_output_tokens: Optional[int]


@dataclass(frozen=True)
class StreamTerminalMetadata:
    """Provider-neutral terminal metadata for a streamed generation."""

    reason: StreamTerminalReason
    provider_reason: Optional[str] = None
    output_tokens: Optional[int] = None
    truncated: bool = False
    error_message: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def completed_cleanly(self) -> bool:
        return self.reason == "completed" and not self.truncated and not self.error_message

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "reason": self.reason,
            "truncated": self.truncated,
        }
        if self.provider_reason:
            result["provider_reason"] = self.provider_reason
        if self.output_tokens is not None:
            result["output_tokens"] = self.output_tokens
        if self.error_message:
            result["error_message"] = self.error_message
        if self.raw:
            result["raw"] = self.raw
        return result


@dataclass(frozen=True)
class StreamEvent:
    """Text chunk or terminal event from a streamed generation."""

    text: str = ""
    terminal: Optional[StreamTerminalMetadata] = None

    @property
    def is_terminal(self) -> bool:
        return self.terminal is not None


def normalize_terminal_reason(provider_reason: Optional[str]) -> StreamTerminalReason:
    """Map provider-specific stop reasons to Basil's neutral terminal reasons."""
    reason = (provider_reason or "").strip().lower()
    if reason in {"end_turn", "stop", "stop_sequence", "complete", "completed"}:
        return "completed"
    if reason in {"max_tokens", "max_output_tokens", "length", "content_filter_length"}:
        return "max_tokens" if "token" in reason else "length"
    if reason in {"cancelled", "canceled"}:
        return "cancelled"
    if reason in {"safety", "content_filter", "blocked", "recitation"}:
        return "safety"
    if reason in {"error", "failed"}:
        return "error"
    return "unknown" if reason else "unknown"


def terminal_from_provider_reason(
    provider_reason: Optional[str],
    *,
    output_tokens: Optional[int] = None,
    raw: Optional[Dict[str, Any]] = None,
) -> StreamTerminalMetadata:
    """Build terminal metadata from a provider stop reason."""
    reason = normalize_terminal_reason(provider_reason)
    return StreamTerminalMetadata(
        reason=reason,
        provider_reason=provider_reason,
        output_tokens=output_tokens,
        truncated=reason in {"max_tokens", "length"},
        raw=raw or {},
    )


def terminal_from_error(error: BaseException) -> StreamTerminalMetadata:
    """Build terminal metadata for a stream failure."""
    return StreamTerminalMetadata(
        reason="error",
        provider_reason=type(error).__name__,
        truncated=True,
        error_message=str(error),
    )


def _local_profile_budget(
    profile: Any,
    purpose: GenerationPurpose,
) -> Optional[int]:
    if getattr(profile, "location", None) != "local":
        return None
    if getattr(profile, "handler", None) not in {"llama_cpp", "huggingface"}:
        return None
    config = getattr(profile, "local_generation", None)
    if not isinstance(config, dict):
        return None
    budgets = config.get("output_budgets")
    if not isinstance(budgets, dict):
        return None
    return _safe_int(budgets.get(purpose))


def resolve_generation_budget(
    llm_model: Any,
    *,
    purpose: GenerationPurpose = "general",
    input_token_estimate: Optional[int] = None,
    requested_output_tokens: Optional[int] = None,
    minimum_output_tokens: int = 1,
) -> GenerationBudget:
    """Resolve one request budget without treating a capability ceiling as a default."""
    profile = resolve_runtime_model_profile(llm_model)
    model_max = profile.max_output_tokens
    if model_max is None:
        model_max = _safe_int(getattr(llm_model, "max_output_tokens", None))
    if model_max is None:
        model_max = _safe_int(getattr(llm_model, "max_tokens_to_sample", None))
    if model_max is None:
        model_max = _safe_int(getattr(llm_model, "max_tokens_to_generate", None))
    if model_max is None:
        model_max = 4096
    model_max = max(1, model_max)

    requested = _safe_int(requested_output_tokens)
    if requested is None:
        requested = _local_profile_budget(profile, purpose)
    if requested is None:
        requested = model_max

    floor = min(model_max, max(1, int(minimum_output_tokens)))
    effective = min(model_max, max(floor, int(requested)))
    context_window = profile.context_window
    if context_window is None:
        context_window = _safe_int(getattr(llm_model, "max_context_length", None))

    input_budget = None
    if context_window:
        if input_token_estimate is not None:
            remaining_after_input = int(context_window) - int(input_token_estimate)
            if remaining_after_input > 0:
                effective = min(effective, remaining_after_input)
        input_budget = max(0, int(context_window) - effective)
        effective = max(1, effective)

    return GenerationBudget(
        purpose=purpose,
        requested_output_tokens=int(requested),
        effective_output_tokens=int(effective),
        input_budget_tokens=input_budget,
        reserved_output_tokens=int(effective),
        model_id=profile.model_id,
        context_window=context_window,
        model_max_output_tokens=model_max,
    )


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "GenerationBudget",
    "GenerationPurpose",
    "StreamEvent",
    "StreamTerminalMetadata",
    "StreamTerminalReason",
    "normalize_terminal_reason",
    "resolve_generation_budget",
    "terminal_from_error",
    "terminal_from_provider_reason",
]
