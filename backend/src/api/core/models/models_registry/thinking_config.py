"""Registry-driven Anthropic thinking request configuration."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .schema import get_model


def get_thinking_request_config(model_id: str) -> Optional[Dict[str, Any]]:
    """Normalize a model's registry thinking capability into SDK-ready request kwargs.

    - adaptive_thinking -> {"thinking": {"type": "adaptive"[, "display": <str>]},
                            "effort": <str|None>, "omit_sampling": True}
    - extended_thinking -> {"thinking": {"type": "enabled", "budget_tokens": N},
                            "max_output_tokens_with_thinking": <int|None>, "omit_sampling": True}
    - neither -> None

    ``default_display`` is registry-driven (like ``default_effort``) and maps to Anthropic ``thinking.display``. ``summarized`` requests provider summaries for Basil's reasoning UI, but valid adaptive-thinking blocks may still have empty text and must be replayed unchanged.
    """
    cfg = get_model(model_id)
    if not cfg:
        return None
    feature_config = cfg.get("feature_config", {})

    adaptive = feature_config.get("adaptive_thinking")
    if isinstance(adaptive, dict):
        effort = adaptive.get("default_effort")
        display = adaptive.get("default_display")
        thinking: Dict[str, Any] = {"type": "adaptive"}
        if isinstance(display, str) and display:
            thinking["display"] = display
        return {
            "thinking": thinking,
            "effort": effort if isinstance(effort, str) and effort else None,
            "omit_sampling": True,
        }

    extended = feature_config.get("extended_thinking")
    if isinstance(extended, dict):
        budget = extended.get("budget_tokens")
        if not isinstance(budget, int):
            return None
        max_with = extended.get("max_output_tokens_with_thinking")
        return {
            "thinking": {"type": "enabled", "budget_tokens": budget},
            "max_output_tokens_with_thinking": max_with if isinstance(max_with, int) else None,
            "omit_sampling": True,
        }

    return None
