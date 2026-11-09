"""Memory-aware context ceiling for llama.cpp loads.

llama.cpp allocates the KV cache and the compute buffers for the full requested context at load time.
Measured on Apple Silicon (Metal) with llama-cpp-python 0.3.28:

- Llama 3.2 3B: n_ctx 32768 -> KV 3.5 GiB + compute 1.6 GiB; n_ctx 262144 -> KV 28 GiB + compute 12.8 GiB.
- Qwen3.6 35B-A3B (hybrid, one attention layer in four): n_ctx 32768 -> KV 0.6 GiB + compute 1.1 GiB; n_ctx 262144 -> KV 5 GiB + compute 8.7 GiB.

Both grow linearly with n_ctx, so a registry value such as 262144 can exhaust a low-memory Mac long before the weights do.
This module turns the machine's local-model memory budget and the model file's own metadata into a safe n_ctx ceiling.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

KV_BYTES_PER_ELEMENT = 2
"""f16 K and V entries, which is what Basil loads with."""

COMPUTE_BYTES_PER_TOKEN = 56 * 1024
"""Measured compute-buffer cost per context token: 50.5 KiB (Llama 3B) and 35.1 KiB (Qwen3.6 hybrid) at n_ubatch 512."""

FALLBACK_KV_BYTES_PER_TOKEN = 160 * 1024
"""Conservative KV cost per token when the model file does not expose enough metadata to compute it."""

HEADROOM_BYTES = 512 * 1024 * 1024
"""Slack kept free for runtime allocations that are not part of the weights, KV cache or compute buffers."""

CONTEXT_STEP = 1024
MEMORY_FLOOR_CONTEXT = 4096
"""Never plan below this; a machine that cannot hold even this much context should use a smaller model instead."""


@dataclass(frozen=True)
class ModelMemoryFacts:
    """What the model file tells us about its own memory cost."""

    model_bytes: int
    kv_bytes_per_token: Optional[int]


def kv_bytes_per_token_from_shape(
    *,
    attention_layers: int,
    kv_heads_per_layer_sum: int,
    key_length: int,
    value_length: int,
) -> int:
    """KV bytes per context token for the layers that carry a KV cache.

    ``kv_heads_per_layer_sum`` is the sum of KV heads over the attention layers, so uniform and per-layer head counts share one formula.
    """

    if attention_layers <= 0 or kv_heads_per_layer_sum <= 0 or key_length <= 0 or value_length <= 0:
        raise ValueError("attention shape values must be positive")
    return kv_heads_per_layer_sum * (key_length + value_length) * KV_BYTES_PER_ELEMENT


def memory_safe_context_window(
    *,
    budget_gb: float,
    model_bytes: int,
    kv_bytes_per_token: Optional[int],
) -> int:
    """Largest n_ctx, rounded down to CONTEXT_STEP, whose KV and compute buffers fit beside the weights.

    Returns MEMORY_FLOOR_CONTEXT when even that does not fit, so callers can still load and report the shortfall.
    """

    kv_cost = kv_bytes_per_token if kv_bytes_per_token and kv_bytes_per_token > 0 else FALLBACK_KV_BYTES_PER_TOKEN
    per_token = kv_cost + COMPUTE_BYTES_PER_TOKEN
    available = int(budget_gb * 1024**3) - max(int(model_bytes), 0) - HEADROOM_BYTES
    if available <= 0:
        return MEMORY_FLOOR_CONTEXT
    tokens = (available // per_token) // CONTEXT_STEP * CONTEXT_STEP
    return max(int(tokens), MEMORY_FLOOR_CONTEXT)


def _field_numbers(field: Any) -> List[int]:
    values: List[int] = []
    for index in field.data:
        part = field.parts[index]
        if len(part) == 0:
            continue
        values.append(int(part[0]))
    return values


def _field_text(field: Any) -> str:
    return bytes(field.parts[field.data[0]]).decode("utf-8", errors="replace")


def read_model_memory_facts(model_path: Path | str) -> ModelMemoryFacts:
    """Read the model's size and, when the GGUF exposes it, its per-token KV cost.

    Never raises: any problem reading metadata yields ``kv_bytes_per_token=None`` and the caller falls back to the conservative default.
    """

    path = Path(model_path)
    try:
        model_bytes = int(os.path.getsize(path))
    except OSError:
        model_bytes = 0

    try:
        from gguf import GGUFReader

        reader = GGUFReader(str(path))
        fields: Dict[str, Any] = dict(reader.fields)
        arch_field = fields.get("general.architecture")
        if arch_field is None:
            return ModelMemoryFacts(model_bytes, None)
        arch = _field_text(arch_field)

        def numbers(suffix: str) -> Optional[List[int]]:
            field = fields.get(f"{arch}.{suffix}")
            return _field_numbers(field) if field is not None else None

        block_count = (numbers("block_count") or [0])[0]
        head_counts = numbers("attention.head_count") or [0]
        kv_heads = numbers("attention.head_count_kv") or head_counts
        embedding = (numbers("embedding_length") or [0])[0]
        key_length = (numbers("attention.key_length") or [0])[0]
        value_length = (numbers("attention.value_length") or [0])[0]
        interval = (numbers("full_attention_interval") or [0])[0]

        if key_length <= 0 and embedding > 0 and head_counts[0] > 0:
            key_length = embedding // head_counts[0]
        if value_length <= 0:
            value_length = key_length
        if block_count <= 0 or key_length <= 0:
            return ModelMemoryFacts(model_bytes, None)

        if len(kv_heads) > 1:
            per_layer = kv_heads[:block_count]
            attention_layers = sum(1 for heads in per_layer if heads > 0)
            kv_sum = sum(per_layer)
        else:
            attention_layers = block_count // interval if interval > 1 else block_count
            attention_layers = max(attention_layers, 1)
            kv_sum = kv_heads[0] * attention_layers

        return ModelMemoryFacts(
            model_bytes,
            kv_bytes_per_token_from_shape(
                attention_layers=attention_layers,
                kv_heads_per_layer_sum=kv_sum,
                key_length=key_length,
                value_length=value_length,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - metadata is best effort and must never block a load
        logger.warning("[LlamaCpp] Could not read KV shape from %s: %s", path, exc)
        return ModelMemoryFacts(model_bytes, None)
