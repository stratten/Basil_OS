"""Registry-derived candidate model enumeration.

Every reasoning-capable model (standard registry + user-defined custom
models) is discovered from the models registry at call time, so the smoke
harness automatically covers models as they are added or removed rather than
hard-coding a model list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from api.core.models.models_registry import get_custom_models
from api.core.models.models_registry.schema import (
    ModelFeature,
    ModelLocation,
    get_models_by_capability,
    has_feature,
)


@dataclass(frozen=True)
class ModelCandidate:
    """A single reasoning model discovered from the registry, with the
    capability/location flags needed to decide which scenarios apply to it."""

    model_id: str
    display_name: str
    provider: str
    location: str  # ModelLocation value: "local" | "cloud"
    handler: str
    is_custom: bool
    supports_function_calling: bool
    supports_openrouter_proxy: bool

    @property
    def is_local(self) -> bool:
        return self.location == ModelLocation.LOCAL.value

    def label(self) -> str:
        kind = "custom" if self.is_custom else self.provider
        return f"{self.model_id} [{kind}/{self.handler}]"

    @property
    def channel_key(self) -> str:
        """A stable grouping key approximating the runtime channel from
        registry fields alone (before any model is loaded).

        The plan derives the reported channel from location/handler and the
        loaded model class (direct OpenAI, direct Anthropic, OpenRouter/
        AuthProxy, local llama.cpp, custom OpenAI-compatible). We can't know
        the loaded class here, but location + handler + custom-ness partition
        candidates into those same channels, which is all ``--sample-channels``
        needs: one representative per distinct handling path.
        """
        kind = "custom" if self.is_custom else self.provider
        return f"{self.location}/{kind}/{self.handler}"


def select_channel_samples(candidates: List["ModelCandidate"]) -> List["ModelCandidate"]:
    """Reduce candidates to one representative per distinct channel.

    Preserves input order and keeps the FIRST candidate seen for each
    ``channel_key`` (candidates arrive id-sorted from ``enumerate_candidates``,
    so this is deterministic). Lets a full sweep of dozens of paid cloud models
    collapse to a handful of channel probes for fast routine validation.
    """
    seen: set[str] = set()
    sampled: List["ModelCandidate"] = []
    for candidate in candidates:
        if candidate.channel_key in seen:
            continue
        seen.add(candidate.channel_key)
        sampled.append(candidate)
    return sampled


def enumerate_candidates(
    *,
    id_filter: Optional[str] = None,
    provider_filter: Optional[str] = None,
    location_filter: Optional[str] = None,
) -> List[ModelCandidate]:
    """Enumerate every registry + custom model with the REASONING capability.

    NOTE: this intentionally calls ``get_models_by_capability("reasoning")``
    with the raw capability *string* rather than ``ModelCapability.REASONING``.
    ``get_models_by_capability`` compares ``capability.value`` against the
    registry's string capability lists ("reasoning", "vision", ...); because
    ``ModelCapability`` is a plain ``Enum`` (via ``auto()``), ``.value`` is an
    int and never matches those strings, so passing the enum member silently
    returns an empty dict. Passing the string directly takes the (correct)
    fallback branch. This is a pre-existing registry quirk (get_models_by_capability
    has no other caller in the codebase); fixing the enum itself is out of
    scope for this harness, so the harness routes around it explicitly here.
    """
    candidates: List[ModelCandidate] = []

    reasoning_models = get_models_by_capability("reasoning")
    for model_id, cfg in sorted(reasoning_models.items()):
        candidates.append(_build_candidate(model_id, cfg, is_custom=False))

    for model_id, cfg in sorted(get_custom_models().items()):
        if "reasoning" not in cfg.get("capabilities", []):
            continue
        candidates.append(_build_candidate(model_id, cfg, is_custom=True))

    if id_filter:
        needle = id_filter.lower()
        candidates = [c for c in candidates if needle in c.model_id.lower()]
    if provider_filter:
        candidates = [c for c in candidates if c.provider.lower() == provider_filter.lower()]
    if location_filter:
        candidates = [c for c in candidates if c.location == location_filter]

    return candidates


def _build_candidate(model_id: str, cfg: Dict[str, Any], *, is_custom: bool) -> ModelCandidate:
    return ModelCandidate(
        model_id=model_id,
        display_name=str(cfg.get("display_name", model_id)),
        provider=str(cfg.get("provider", "custom" if is_custom else "unknown")),
        location=str(cfg.get("location", ModelLocation.CLOUD.value)),
        handler=str(cfg.get("handler", "unknown")),
        is_custom=is_custom,
        supports_function_calling=has_feature(model_id, ModelFeature.FUNCTION_CALLING),
        supports_openrouter_proxy=bool(cfg.get("supports_openrouter_proxy", False)),
    )
