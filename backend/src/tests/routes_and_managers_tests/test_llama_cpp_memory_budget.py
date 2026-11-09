from __future__ import annotations

from pathlib import Path

import pytest

from api.core.runtime.hardware_capability_service import HardwareCapabilityProfile
from api.core.runtime.llama_cpp_load_plan import build_llama_cpp_load_plan
from api.core.runtime.llama_cpp_memory_budget import (
    COMPUTE_BYTES_PER_TOKEN,
    FALLBACK_KV_BYTES_PER_TOKEN,
    MEMORY_FLOOR_CONTEXT,
    kv_bytes_per_token_from_shape,
    memory_safe_context_window,
    read_model_memory_facts,
)

pytestmark = pytest.mark.use_temp_home

GIBIBYTE = 1 << 30
MEBIBYTE = 1 << 20


def _profile(**overrides):
    defaults = {
        "platform": "Darwin",
        "machine": "arm64",
        "total_ram_gb": 16,
        "is_apple_silicon": True,
        "chip_label": "Apple M2",
        "memory_tier": "standard",
        "local_model_memory_budget_gb": 7,
        "cpu_count": 8,
        "gpu_available": True,
        "gpu_backend": "metal",
        "recommended_gpu_layers": 33,
        "memory_optimizations": {"f16_kv": True},
        "recommended_threads": 4,
        "recommended_llama_batch": 512,
        "recommended_llama_ubatch": 512,
    }
    defaults.update(overrides)
    return HardwareCapabilityProfile(**defaults)


def test_kv_formula_matches_the_llama_cpp_buffer_measured_for_a_dense_3b_model():
    per_token = kv_bytes_per_token_from_shape(attention_layers=28, kv_heads_per_layer_sum=28 * 8, key_length=128, value_length=128)

    assert per_token * 32768 == 3584 * MEBIBYTE


def test_kv_formula_matches_the_llama_cpp_buffer_measured_for_a_hybrid_model():
    per_token = kv_bytes_per_token_from_shape(attention_layers=10, kv_heads_per_layer_sum=10 * 2, key_length=256, value_length=256)

    assert per_token * 32768 == 640 * MEBIBYTE
    assert per_token * 262144 == 5120 * MEBIBYTE


def test_kv_formula_rejects_non_positive_shapes():
    with pytest.raises(ValueError):
        kv_bytes_per_token_from_shape(attention_layers=0, kv_heads_per_layer_sum=8, key_length=128, value_length=128)


def test_ceiling_is_a_multiple_of_the_step_and_fits_beside_the_weights():
    ceiling = memory_safe_context_window(budget_gb=7, model_bytes=5 * GIBIBYTE, kv_bytes_per_token=24576)

    assert ceiling == 19456
    assert ceiling % 1024 == 0
    assert ceiling * (24576 + COMPUTE_BYTES_PER_TOKEN) <= 2 * GIBIBYTE


def test_ceiling_uses_the_conservative_default_when_the_kv_cost_is_unknown():
    unknown = memory_safe_context_window(budget_gb=7, model_bytes=5 * GIBIBYTE, kv_bytes_per_token=None)
    explicit = memory_safe_context_window(budget_gb=7, model_bytes=5 * GIBIBYTE, kv_bytes_per_token=FALLBACK_KV_BYTES_PER_TOKEN)

    assert unknown == explicit
    assert unknown < 19456


def test_ceiling_never_drops_below_the_floor_even_when_the_weights_alone_exceed_the_budget():
    assert memory_safe_context_window(budget_gb=7, model_bytes=9 * GIBIBYTE, kv_bytes_per_token=24576) == MEMORY_FLOOR_CONTEXT
    assert memory_safe_context_window(budget_gb=0, model_bytes=0, kv_bytes_per_token=24576) == MEMORY_FLOOR_CONTEXT


def test_large_machine_ceiling_does_not_restrict_the_trained_context():
    assert memory_safe_context_window(budget_gb=96, model_bytes=6 * GIBIBYTE, kv_bytes_per_token=24576) > 262144


def test_sixteen_gb_mac_no_longer_loads_a_nine_b_model_at_the_registry_context():
    plan = build_llama_cpp_load_plan(
        hardware_profile=_profile(),
        registry_config={"context_window": 262144},
        gguf_context_window=262144,
        model_bytes=int(5.68 * GIBIBYTE),
        kv_bytes_per_token=24576,
    )

    assert plan.n_ctx < 32768
    assert plan.n_ctx >= MEMORY_FLOOR_CONTEXT
    assert any("clamped from 262144" in reason and "7 GB local-model memory budget" in reason for reason in plan.fallback_reasons)


def test_one_hundred_twenty_eight_gb_mac_keeps_the_registry_context():
    plan = build_llama_cpp_load_plan(
        hardware_profile=_profile(total_ram_gb=128, memory_tier="very_high", local_model_memory_budget_gb=96, chip_label="Apple M5 Max"),
        registry_config={"context_window": 262144},
        gguf_context_window=262144,
        model_bytes=int(5.68 * GIBIBYTE),
        kv_bytes_per_token=24576,
    )

    assert plan.n_ctx == 262144
    assert plan.fallback_reasons == []


def test_prompt_cache_reservation_lowers_the_ceiling_on_a_24_gb_mac(monkeypatch):
    monkeypatch.delenv("BASIL_LLAMA_CPP_PROMPT_CACHE_GB", raising=False)
    common = {
        "registry_config": {"context_window": 262144},
        "gguf_context_window": 262144,
        "model_bytes": int(5.68 * GIBIBYTE),
        "kv_bytes_per_token": 24576,
    }
    without_cache = build_llama_cpp_load_plan(
        hardware_profile=_profile(total_ram_gb=24, memory_tier="medium", local_model_memory_budget_gb=13), **common
    )
    monkeypatch.setenv("BASIL_LLAMA_CPP_PROMPT_CACHE_GB", "0")
    no_cache = build_llama_cpp_load_plan(
        hardware_profile=_profile(total_ram_gb=24, memory_tier="medium", local_model_memory_budget_gb=13), **common
    )

    assert without_cache.prompt_cache_bytes == 4 * GIBIBYTE
    assert without_cache.n_ctx < no_cache.n_ctx


def test_plan_without_model_facts_is_unchanged_so_the_vision_loader_keeps_its_own_clamp():
    plan = build_llama_cpp_load_plan(
        hardware_profile=_profile(),
        registry_config={"context_window": 32768},
        gguf_context_window=32768,
        max_context_window=8192,
    )

    assert plan.n_ctx == 8192
    assert plan.fallback_reasons == ["Context window clamped from 32768 to caller max_context_window=8192"]


def _write_gguf(path: Path, fields: dict) -> None:
    from gguf import GGUFWriter

    writer = GGUFWriter(str(path), "llama")
    for key, value in fields.items():
        if isinstance(value, list):
            writer.add_array(key, value)
        else:
            writer.add_uint32(key, value)
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()
    writer.close()


def test_reads_dense_model_shape_from_gguf_metadata(tmp_path):
    model = tmp_path / "dense.gguf"
    _write_gguf(
        model,
        {
            "llama.block_count": 28,
            "llama.attention.head_count": 24,
            "llama.attention.head_count_kv": 8,
            "llama.attention.key_length": 128,
            "llama.attention.value_length": 128,
            "llama.embedding_length": 3072,
        },
    )

    facts = read_model_memory_facts(model)

    assert facts.kv_bytes_per_token == 114688
    assert facts.model_bytes == model.stat().st_size


def test_reads_hybrid_model_shape_and_counts_only_attention_layers(tmp_path):
    model = tmp_path / "hybrid.gguf"
    _write_gguf(
        model,
        {
            "llama.block_count": 40,
            "llama.attention.head_count": 16,
            "llama.attention.head_count_kv": 2,
            "llama.attention.key_length": 256,
            "llama.attention.value_length": 256,
            "llama.full_attention_interval": 4,
        },
    )

    assert read_model_memory_facts(model).kv_bytes_per_token == 20480


def test_derives_head_size_from_the_embedding_when_lengths_are_absent(tmp_path):
    model = tmp_path / "derived.gguf"
    _write_gguf(
        model,
        {
            "llama.block_count": 28,
            "llama.attention.head_count": 24,
            "llama.attention.head_count_kv": 8,
            "llama.embedding_length": 3072,
        },
    )

    assert read_model_memory_facts(model).kv_bytes_per_token == 114688


def test_sums_per_layer_kv_head_counts_and_skips_layers_without_attention(tmp_path):
    model = tmp_path / "per-layer.gguf"
    _write_gguf(
        model,
        {
            "llama.block_count": 4,
            "llama.attention.head_count": 16,
            "llama.attention.head_count_kv": [4, 0, 4, 0],
            "llama.attention.key_length": 128,
            "llama.attention.value_length": 128,
        },
    )

    assert read_model_memory_facts(model).kv_bytes_per_token == 8 * 256 * 2


def test_metadata_gaps_and_unreadable_files_yield_unknown_kv_cost_without_raising(tmp_path):
    sparse = tmp_path / "sparse.gguf"
    _write_gguf(sparse, {"llama.block_count": 28})
    missing = tmp_path / "missing.gguf"
    garbage = tmp_path / "garbage.gguf"
    garbage.write_bytes(b"not a gguf file")

    assert read_model_memory_facts(sparse).kv_bytes_per_token is None
    assert read_model_memory_facts(missing).model_bytes == 0
    assert read_model_memory_facts(missing).kv_bytes_per_token is None
    assert read_model_memory_facts(garbage).kv_bytes_per_token is None
