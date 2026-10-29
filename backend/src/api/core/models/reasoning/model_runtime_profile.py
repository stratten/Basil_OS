"""
Runtime model profile: merges registry config with the loaded model instance.

Used for capability-driven tool inclusion and consistent LangChain/API kwargs without
scattering provider-specific attribute reads across functional classes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from api.core.models.models_registry import get_local_reasoning_models, get_model

logger = logging.getLogger(__name__)

# Recognized tool rendering profile values. The construction layer (per-tool
# factories) selects FULL vs SLIM forms based on this value; the local
# llama.cpp adapter additionally branches on `slim_text_catalog` to omit
# `tools=` and inject a text preamble. See Plan B for full semantics.
TOOL_RENDERING_FULL_SCHEMA = "full_schema"
TOOL_RENDERING_SLIM_SCHEMA = "slim_schema"
TOOL_RENDERING_SLIM_TEXT_CATALOG = "slim_text_catalog"
VALID_TOOL_RENDERING_VALUES = frozenset(
    {
        TOOL_RENDERING_FULL_SCHEMA,
        TOOL_RENDERING_SLIM_SCHEMA,
        TOOL_RENDERING_SLIM_TEXT_CATALOG,
    }
)

TOOL_CALL_FORMAT_JSON_TOOL_CALL = "json_tool_call"
TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS = "function_parameter_tags"
VALID_TOOL_CALL_FORMAT_VALUES = frozenset(
    {
        TOOL_CALL_FORMAT_JSON_TOOL_CALL,
        TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS,
    }
)


@dataclass
class RuntimeModelProfile:
    """Merged view of registry entry (if any) and live model attributes."""

    model_id: str
    registry_entry: Optional[Dict[str, Any]]
    provider: Optional[str]
    handler: Optional[str]
    capabilities: List[str] = field(default_factory=list)
    features: List[str] = field(default_factory=list)
    feature_config: Dict[str, Any] = field(default_factory=dict)
    context_window: Optional[int] = None
    max_output_tokens: Optional[int] = None
    engine_source: Optional[str] = None
    tool_rendering: str = TOOL_RENDERING_FULL_SCHEMA
    tool_call_format: str = TOOL_CALL_FORMAT_JSON_TOOL_CALL
    location: Optional[str] = None
    local_generation: Dict[str, Any] = field(default_factory=dict)


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_tool_rendering(raw: Any, model_id: str) -> str:
    """Return a recognized tool rendering value or fall back to full_schema with a warning."""
    if raw is None:
        return TOOL_RENDERING_FULL_SCHEMA
    candidate = str(raw).strip().lower()
    if not candidate:
        return TOOL_RENDERING_FULL_SCHEMA
    if candidate in VALID_TOOL_RENDERING_VALUES:
        return candidate
    logger.warning(
        "Unknown tool_rendering value %r for model %s; falling back to %s",
        raw,
        model_id,
        TOOL_RENDERING_FULL_SCHEMA,
    )
    return TOOL_RENDERING_FULL_SCHEMA


def _normalize_tool_call_format(raw: Any, model_id: str) -> str:
    """Return a recognized tool-call format or fall back to json_tool_call."""
    if raw is None:
        return TOOL_CALL_FORMAT_JSON_TOOL_CALL
    candidate = str(raw).strip().lower()
    if not candidate:
        return TOOL_CALL_FORMAT_JSON_TOOL_CALL
    if candidate in VALID_TOOL_CALL_FORMAT_VALUES:
        return candidate
    logger.warning(
        "Unknown tool_call_format value %r for model %s; falling back to %s",
        raw,
        model_id,
        TOOL_CALL_FORMAT_JSON_TOOL_CALL,
    )
    return TOOL_CALL_FORMAT_JSON_TOOL_CALL


def _registry_model_id_from_local_path(llm_model: Any) -> Optional[str]:
    """Reverse-lookup a local model's registry id via its on-disk filename.

    LlamaCppModel (and other local GGUF/HF model classes) never assign
    ``self.model_name`` to the registry key the way the API model classes do
    in ``model_manager.py``. Without this fallback, ``resolve_runtime_model_profile``
    cannot find the registry config for any local model, which silently
    disables every registry-driven flag (most importantly ``tool_rendering``,
    Plan B's slim/full switch). We match by the registry's declared
    ``on_disk_name`` against ``model_path.stem`` so the reverse lookup can
    never collide across models.
    """
    path = getattr(llm_model, "model_path", None)
    if path is None:
        return None
    stem = getattr(path, "stem", "") or ""
    stem_norm = stem.strip().lower()
    if not stem_norm:
        return None
    try:
        local_models = get_local_reasoning_models()
    except Exception:
        return None
    for mid, cfg in local_models.items():
        on_disk = str(cfg.get("on_disk_name") or "").strip().lower()
        if on_disk and on_disk == stem_norm:
            return mid
    return None


def resolve_runtime_model_profile(llm_model: Any) -> RuntimeModelProfile:
    """Build a profile from ``get_model(model_name)`` plus live model fallbacks."""
    model_id = (
        getattr(llm_model, "model_name", None)
        or _registry_model_id_from_local_path(llm_model)
        or "unknown"
    )
    cfg = get_model(model_id) if model_id and model_id != "unknown" else None

    capabilities: List[str] = []
    features: List[str] = []
    feature_config: Dict[str, Any] = {}
    provider: Optional[str] = None
    handler: Optional[str] = None
    context_window: Optional[int] = None
    max_output_tokens: Optional[int] = None
    tool_rendering: str = TOOL_RENDERING_FULL_SCHEMA
    tool_call_format: str = TOOL_CALL_FORMAT_JSON_TOOL_CALL
    location: Optional[str] = None
    local_generation: Dict[str, Any] = {}

    if cfg:
        capabilities = list(cfg.get("capabilities") or [])
        features = list(cfg.get("features") or [])
        feature_config = dict(cfg.get("feature_config") or {})
        provider = cfg.get("provider")
        handler = cfg.get("handler")
        location = cfg.get("location")
        raw_local_generation = cfg.get("local_generation")
        if isinstance(raw_local_generation, dict):
            local_generation = dict(raw_local_generation)
        context_window = _safe_int(cfg.get("context_window"))
        max_output_tokens = _safe_int(cfg.get("max_output_tokens"))
        tool_rendering = _normalize_tool_rendering(cfg.get("tool_rendering"), model_id)
        tool_call_format = _normalize_tool_call_format(
            cfg.get("tool_call_format"), model_id
        )

    engine_source: Optional[str] = None
    try:
        meta = llm_model.get_metadata()
        engine_source = getattr(meta, "source", None) or None
        params = getattr(meta, "parameters", None)
        if isinstance(params, dict):
            if context_window is None:
                context_window = _safe_int(params.get("context_window"))
            if max_output_tokens is None:
                max_output_tokens = _safe_int(
                    params.get("max_output_tokens") or params.get("max_tokens")
                )
    except Exception:
        pass

    if context_window is None:
        context_window = _safe_int(getattr(llm_model, "max_context_length", None))
    if context_window is None:
        context_window = _safe_int(getattr(llm_model, "context_window", None))

    if max_output_tokens is None:
        max_output_tokens = _safe_int(getattr(llm_model, "max_output_tokens", None))
    if max_output_tokens is None:
        max_output_tokens = _safe_int(getattr(llm_model, "max_tokens_to_sample", None))
    if max_output_tokens is None:
        max_output_tokens = _safe_int(getattr(llm_model, "max_tokens_to_generate", None))

    return RuntimeModelProfile(
        model_id=model_id,
        registry_entry=cfg,
        provider=provider,
        handler=handler,
        capabilities=capabilities,
        features=features,
        feature_config=feature_config,
        context_window=context_window,
        max_output_tokens=max_output_tokens,
        engine_source=engine_source,
        tool_rendering=tool_rendering,
        tool_call_format=tool_call_format,
        location=location,
        local_generation=local_generation,
    )


def resolve_tool_rendering_for(profile: Optional[RuntimeModelProfile]) -> str:
    """Return the active tool rendering profile value, defaulting to full_schema.

    Centralized here so call sites (tool factories, adapters) never have to
    reimplement the None-safe lookup or repeat the default.
    """
    if profile is None:
        return TOOL_RENDERING_FULL_SCHEMA
    value = getattr(profile, "tool_rendering", None) or TOOL_RENDERING_FULL_SCHEMA
    return value if value in VALID_TOOL_RENDERING_VALUES else TOOL_RENDERING_FULL_SCHEMA


def resolve_tool_call_format_for(profile: Optional[RuntimeModelProfile]) -> str:
    """Return the active local text tool-call format, defaulting to json_tool_call."""
    if profile is None:
        return TOOL_CALL_FORMAT_JSON_TOOL_CALL
    value = getattr(profile, "tool_call_format", None) or TOOL_CALL_FORMAT_JSON_TOOL_CALL
    return (
        value
        if value in VALID_TOOL_CALL_FORMAT_VALUES
        else TOOL_CALL_FORMAT_JSON_TOOL_CALL
    )


def is_slim_rendering(profile: Optional[RuntimeModelProfile]) -> bool:
    """True when the active profile is one of the slim rendering modes.

    Used by per-tool factories to pick between FULL and SLIM companion fields.
    """
    return resolve_tool_rendering_for(profile) in (
        TOOL_RENDERING_SLIM_SCHEMA,
        TOOL_RENDERING_SLIM_TEXT_CATALOG,
    )


def select_description_for_profile(
    profile: Optional[RuntimeModelProfile],
    full_description: str,
    slim_description: Optional[str],
) -> str:
    """Pick the per-tool description to publish to LangChain for the given profile.

    Returns ``slim_description`` when the active profile is a slim rendering mode
    AND ``slim_description`` is non-empty. Otherwise returns ``full_description``.
    No truncation, no derivation: the slim form is exactly what the tool's file
    declares as its hand-authored companion. Empty/missing slim companions fall
    back to the full description with a warning so callers never see a partial
    slim form silently emitted.
    """
    if is_slim_rendering(profile) and slim_description:
        return slim_description
    if is_slim_rendering(profile) and not slim_description:
        logger.warning(
            "Slim profile %s requested but no slim_description was authored; "
            "falling back to full description.",
            resolve_tool_rendering_for(profile),
        )
    return full_description


def select_args_schema_for_profile(
    profile: Optional[RuntimeModelProfile],
    full_args_schema: Any,
    slim_args_schema: Optional[Any],
) -> Any:
    """Pick the per-tool Pydantic args_schema to publish to LangChain.

    Returns ``slim_args_schema`` when the active profile is a slim rendering
    mode AND a sibling slim schema has been authored. Otherwise returns
    ``full_args_schema``. Tools that do not author a deliberate slim schema
    (the common case) keep their full schema even under slim profiles; the
    description still slims via ``select_description_for_profile``.
    """
    if is_slim_rendering(profile) and slim_args_schema is not None:
        return slim_args_schema
    return full_args_schema


def _is_local_reasoning_profile(profile: RuntimeModelProfile) -> bool:
    return profile.location == "local" and profile.handler in {"llama_cpp", "huggingface"}


def resolve_local_reasoning_mode(profile: RuntimeModelProfile) -> str:
    """Return the registry reasoning mode for a local model, defaulting to tagged."""
    if not _is_local_reasoning_profile(profile):
        return "tagged"
    mode = profile.local_generation.get("reasoning_mode")
    if mode in {"tagged", "none"}:
        return mode
    if mode is not None:
        logger.warning(
            "Unknown reasoning_mode %r for model %s; falling back to tagged",
            mode,
            profile.model_id,
        )
    return "tagged"


def resolve_local_sampling(profile: RuntimeModelProfile) -> Dict[str, Any]:
    """Return registry sampling parameters for a local model."""
    if not _is_local_reasoning_profile(profile):
        return {}
    sampling = profile.local_generation.get("sampling")
    return dict(sampling) if isinstance(sampling, dict) else {}


def resolve_local_output_budget(
    profile: RuntimeModelProfile,
    purpose: str,
) -> Optional[int]:
    """Return a per-purpose output budget for a local model when configured."""
    if not _is_local_reasoning_profile(profile):
        return None
    budgets = profile.local_generation.get("output_budgets")
    if not isinstance(budgets, dict):
        return None
    return _safe_int(budgets.get(purpose))


def profile_supports_capability(profile: RuntimeModelProfile, capability: str) -> bool:
    """True if registry capabilities include ``capability`` (case-insensitive string)."""
    want = (capability or "").strip().lower()
    if not want:
        return False
    for c in profile.capabilities:
        label = c.value if hasattr(c, "value") else c
        if str(label).lower() == want:
            return True
    return False


def get_langchain_max_output_tokens(profile: RuntimeModelProfile, llm_model: Any) -> int:
    """
    Resolved max output tokens for LangChain ChatOpenAI / ChatAnthropic ``max_tokens``.

    Falls back conservatively if nothing is known.
    """
    limit = profile.max_output_tokens
    if limit is None:
        limit = _safe_int(getattr(llm_model, "max_output_tokens", None))
    if limit is None:
        limit = _safe_int(getattr(llm_model, "max_tokens_to_sample", None))
    if limit is None:
        limit = _safe_int(getattr(llm_model, "max_tokens_to_generate", None))
    if limit is None:
        limit = 4096
    limit = max(1, int(limit))
    # Hard ceiling guards absurd registry mistakes; LLMs rarely need >128k output.
    return min(limit, 128000)
