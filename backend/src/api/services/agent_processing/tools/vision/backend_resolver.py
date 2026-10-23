"""
Resolve which backend powers analyze_with_vision: native multimodal agent model,
manual-install local Qwen2.5-VL, or unavailable.

Never triggers model downloads; disk presence is checked only.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from api.core.models.models_registry import get_model
from api.core.models.models_registry.local_vision_registry import local_vision_files_present
from api.core.models.preferences import Preferences
from api.core.models.reasoning.model_runtime_profile import (
    profile_supports_capability,
    resolve_runtime_model_profile,
)


class VisionBackend(str, Enum):
    """Vision inference backend for the analyze_with_vision tool."""

    UNAVAILABLE = "unavailable"
    NATIVE = "native"
    LOCAL_QWEN_VL = "local_qwen_vl"


def resolve_agent_vision_backend(
    llm_model: Any,
    preferences: Preferences,
    models_dir: Path,
) -> VisionBackend:
    """
    Prefer native vision on the active agent model; optionally fall back to local
    Qwen2.5-VL when enabled and both GGUF files are present under ``models_dir``.
    """
    profile = resolve_runtime_model_profile(llm_model)
    if profile_supports_capability(profile, "vision"):
        return VisionBackend.NATIVE

    if not getattr(preferences.models, "local_vision_fallback_enabled", False):
        return VisionBackend.UNAVAILABLE

    model_id = getattr(preferences.models, "local_vision_model_id", "") or ""
    cfg = get_model(model_id.strip())
    if not cfg or cfg.get("handler") != "llama_cpp_vision":
        return VisionBackend.UNAVAILABLE

    if not local_vision_files_present(models_dir, cfg):
        return VisionBackend.UNAVAILABLE

    return VisionBackend.LOCAL_QWEN_VL
