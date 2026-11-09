"""Hardware-aware llama.cpp load planning."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from api.core.runtime.hardware_capability_service import HardwareCapabilityProfile
from api.core.runtime.llama_cpp_memory_budget import memory_safe_context_window


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
    prompt_cache_bytes: int = 0
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
    model_bytes: Optional[int] = None,
    kv_bytes_per_token: Optional[int] = None,
) -> LlamaCppLoadPlan:
    """Build a llama.cpp load plan from hardware, registry, and GGUF facts.

    When ``model_bytes`` is given, the context window is also capped so the weights, KV cache and compute buffers fit the machine's local-model memory budget.
    """

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

    prompt_cache_bytes = prompt_cache_capacity_bytes(hardware_profile.total_ram_gb)

    if model_bytes is not None:
        # The prompt-state cache lives in the same memory as the weights and context buffers.
        memory_ceiling = memory_safe_context_window(
            budget_gb=max(hardware_profile.local_model_memory_budget_gb - prompt_cache_bytes / _GIBIBYTE, 0),
            model_bytes=model_bytes,
            kv_bytes_per_token=kv_bytes_per_token,
        )
        if n_ctx > memory_ceiling:
            fallback_reasons.append(
                f"Context window clamped from {n_ctx} to {memory_ceiling} to fit the "
                f"{hardware_profile.local_model_memory_budget_gb} GB local-model memory budget "
                f"({hardware_profile.total_ram_gb} GB RAM)"
            )
            n_ctx = memory_ceiling

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
        verbose=_verbose_requested(),
        prompt_cache_bytes=prompt_cache_bytes,
        memory_optimizations=dict(hardware_profile.memory_optimizations),
        fallback_reasons=fallback_reasons,
    )


PROMPT_CACHE_ENVIRONMENT_VARIABLE = "BASIL_LLAMA_CPP_PROMPT_CACHE_GB"
_GIBIBYTE = 1 << 30
# A snapshot is the whole KV state of one finished call (about 3.8 GB for a 25k-token prompt on an 8B model), and llama-cpp-python keeps the newest ones that fit. Its default of 2 GiB cannot hold even one, so every snapshot would be copied and then dropped at once.
PROMPT_CACHE_MIN_RAM_GB = 24
PROMPT_CACHE_RAM_DIVISOR = 6
PROMPT_CACHE_MIN_GB = 4
PROMPT_CACHE_MAX_GB = 16


def prompt_cache_capacity_bytes(total_ram_gb: int) -> int:
    """Size of the in-memory prompt-state cache for a llama.cpp model, or 0 for none.

    The cache lets a short call between two long agent calls leave the long prompt recoverable, instead of forcing the next long call to read its whole prompt again. It takes one sixth of physical memory, between 4 and 16 GiB, and is off below 24 GB of RAM because a machine that small cannot spare room for even one snapshot. ``BASIL_LLAMA_CPP_PROMPT_CACHE_GB`` overrides the size in GiB, and 0 turns the cache off.
    """
    override = os.environ.get(PROMPT_CACHE_ENVIRONMENT_VARIABLE, "").strip()
    if override:
        try:
            override_gb = float(override)
        except ValueError:
            override_gb = None
        if override_gb is not None and override_gb >= 0:
            return int(override_gb * _GIBIBYTE)
    if total_ram_gb < PROMPT_CACHE_MIN_RAM_GB:
        return 0
    capacity_gb = min(max(total_ram_gb // PROMPT_CACHE_RAM_DIVISOR, PROMPT_CACHE_MIN_GB), PROMPT_CACHE_MAX_GB)
    return capacity_gb * _GIBIBYTE


VERBOSE_ENVIRONMENT_VARIABLE = "BASIL_LLAMA_CPP_VERBOSE"


def _verbose_requested() -> bool:
    """Opt-in llama.cpp diagnostics (prompt-cache prefix hits, prompt-processing time and tokens per call); set BASIL_LLAMA_CPP_VERBOSE=1 before starting the backend. The output is noisy, so it is off by default."""
    return os.environ.get(VERBOSE_ENVIRONMENT_VARIABLE, "").strip().lower() in {"1", "true", "yes", "on"}


def _coerce_positive_int(value: Any) -> Optional[int]:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced > 0 else None
