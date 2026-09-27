"""Hardware-aware llama.cpp load planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from api.core.runtime.hardware_capability_service import HardwareCapabilityProfile


@dataclass(frozen=True)
class LlamaCppLoadPlan:
    """Resolved llama.cpp runtime settings for one model load."""

    n_ctx: int
    n_gpu_layers: int
    n_threads: int
    n_batch: Optional[int]
    n_ubatch: Optional[int]
    use_mlock: bool
    seed: int = 42
    verbose: bool = False
    memory_optimizations: Dict[str, Any] = field(default_factory=dict)
    fallback_reasons: List[str] = field(default_factory=list)

    def to_llama_kwargs(self, model_path: Path | str, **extra_kwargs: Any) -> Dict[str, Any]:
        """Return kwargs suitable for llama_cpp.Llama."""

        kwargs: Dict[str, Any] = {
            "model_path": str(model_path),
            "n_ctx": self.n_ctx,
            "n_gpu_layers": self.n_gpu_layers,
            "n_threads": self.n_threads,
            "verbose": self.verbose,
            "use_mlock": self.use_mlock,
            "seed": self.seed,
        }
        if self.n_batch is not None:
            kwargs["n_batch"] = self.n_batch
        if self.n_ubatch is not None:
            kwargs["n_ubatch"] = self.n_ubatch
        kwargs.update(extra_kwargs)
        return kwargs


def build_llama_cpp_load_plan(
    *,
    hardware_profile: HardwareCapabilityProfile,
    registry_config: Optional[Dict[str, Any]] = None,
    gguf_context_window: Optional[int] = None,
    default_context_window: int = 32768,
    min_context_window: Optional[int] = None,
    max_context_window: Optional[int] = None,
) -> LlamaCppLoadPlan:
    """Build a llama.cpp load plan from hardware, registry, and GGUF facts."""

    registry_config = registry_config or {}
    fallback_reasons: List[str] = []

    registry_context = _coerce_positive_int(registry_config.get("context_window"))
    if registry_context is not None:
        n_ctx = registry_context
        if gguf_context_window is not None and registry_context > gguf_context_window:
            fallback_reasons.append(
                f"Registry context_window={registry_context} exceeds GGUF trained context={gguf_context_window}"
            )
    elif gguf_context_window is not None:
        n_ctx = gguf_context_window
    else:
        n_ctx = default_context_window
        fallback_reasons.append("GGUF context metadata unavailable; using default context window")

    if max_context_window is not None and n_ctx > max_context_window:
        fallback_reasons.append(
            f"Context window clamped from {n_ctx} to caller max_context_window={max_context_window}"
        )
        n_ctx = max_context_window
    if min_context_window is not None and n_ctx < min_context_window:
        fallback_reasons.append(
            f"Context window raised from {n_ctx} to caller min_context_window={min_context_window}"
        )
        n_ctx = min_context_window

    n_batch = _coerce_positive_int(registry_config.get("n_batch"))
    if n_batch is None:
        n_batch = hardware_profile.recommended_llama_batch

    n_ubatch = _coerce_positive_int(registry_config.get("n_ubatch"))
    if n_ubatch is None:
        n_ubatch = hardware_profile.recommended_llama_ubatch

    n_gpu_layers = 0
    if hardware_profile.gpu_available:
        if hardware_profile.gpu_backend == "metal":
            n_gpu_layers = -1
        else:
            n_gpu_layers = hardware_profile.recommended_gpu_layers

    return LlamaCppLoadPlan(
        n_ctx=n_ctx,
        n_gpu_layers=n_gpu_layers,
        n_threads=hardware_profile.recommended_threads,
        n_batch=n_batch,
        n_ubatch=n_ubatch,
        use_mlock=False,
        memory_optimizations=dict(hardware_profile.memory_optimizations),
        fallback_reasons=fallback_reasons,
    )


def _coerce_positive_int(value: Any) -> Optional[int]:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced > 0 else None
