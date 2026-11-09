from __future__ import annotations

import pytest

from api.core.runtime.hardware_capability_service import HardwareCapabilityProfile
from api.core.runtime.llama_cpp_load_plan import build_llama_cpp_load_plan


pytestmark = pytest.mark.use_temp_home


def _profile(**overrides):
    defaults = {
        "platform": "Darwin",
        "machine": "arm64",
        "total_ram_gb": 128,
        "is_apple_silicon": True,
        "chip_label": "Apple M5 Max",
        "memory_tier": "very_high",
        "local_model_memory_budget_gb": 96,
        "cpu_count": 16,
        "gpu_available": True,
        "gpu_backend": "metal",
        "recommended_gpu_layers": 43,
        "memory_optimizations": {"f16_kv": True},
        "recommended_threads": 12,
        "recommended_llama_batch": 2048,
        "recommended_llama_ubatch": 1024,
    }
    defaults.update(overrides)
    return HardwareCapabilityProfile(**defaults)


def test_high_memory_apple_silicon_plan_uses_all_metal_layers_and_hardware_batching():
    plan = build_llama_cpp_load_plan(
        hardware_profile=_profile(),
        registry_config={"context_window": 40960},
        gguf_context_window=40960,
    )

    assert plan.n_ctx == 40960
    assert plan.n_gpu_layers == -1
    assert plan.n_threads == 12
    assert plan.n_batch == 2048
    assert plan.n_ubatch == 1024
    assert plan.memory_optimizations == {"f16_kv": True}
    assert plan.fallback_reasons == []


def test_registry_batch_overrides_hardware_recommendations():
    plan = build_llama_cpp_load_plan(
        hardware_profile=_profile(),
        registry_config={"context_window": 8192, "n_batch": "256", "n_ubatch": 128},
        gguf_context_window=8192,
    )

    assert plan.n_batch == 256
    assert plan.n_ubatch == 128


def test_cpu_only_profile_disables_gpu_layers_and_uses_default_context_when_needed():
    plan = build_llama_cpp_load_plan(
        hardware_profile=_profile(
            platform="Linux",
            machine="x86_64",
            is_apple_silicon=False,
            chip_label=None,
            memory_tier="standard",
            total_ram_gb=16,
            local_model_memory_budget_gb=7,
            gpu_available=False,
            gpu_backend=None,
            recommended_gpu_layers=0,
            memory_optimizations={},
            recommended_threads=6,
            recommended_llama_batch=512,
            recommended_llama_ubatch=512,
        ),
        registry_config={},
        gguf_context_window=None,
    )

    assert plan.n_ctx == 32768
    assert plan.n_gpu_layers == 0
    assert plan.n_threads == 6
    assert "GGUF context metadata unavailable" in plan.fallback_reasons[0]


def test_caller_can_clamp_context_for_vision_loader():
    plan = build_llama_cpp_load_plan(
        hardware_profile=_profile(),
        registry_config={"context_window": 32768},
        gguf_context_window=32768,
        max_context_window=8192,
    )

    assert plan.n_ctx == 8192
    assert plan.fallback_reasons == [
        "Context window clamped from 32768 to caller max_context_window=8192"
    ]


def _plan():
    return build_llama_cpp_load_plan(hardware_profile=_profile(), registry_config={"context_window": 40960}, gguf_context_window=40960)


def test_llama_cpp_diagnostics_are_off_by_default(monkeypatch):
    monkeypatch.delenv("BASIL_LLAMA_CPP_VERBOSE", raising=False)

    plan = _plan()

    assert plan.verbose is False
    assert plan.to_llama_kwargs("model.gguf")["verbose"] is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
def test_llama_cpp_diagnostics_turn_on_with_the_environment_variable(monkeypatch, value):
    monkeypatch.setenv("BASIL_LLAMA_CPP_VERBOSE", value)

    plan = _plan()

    assert plan.verbose is True
    assert plan.to_llama_kwargs("model.gguf")["verbose"] is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "verbose"])
def test_llama_cpp_diagnostics_ignore_other_values(monkeypatch, value):
    monkeypatch.setenv("BASIL_LLAMA_CPP_VERBOSE", value)

    assert _plan().verbose is False


GIBIBYTE = 1 << 30


@pytest.mark.parametrize(
    ("total_ram_gb", "expected_gib"),
    [(8, 0), (16, 0), (23, 0), (24, 4), (32, 5), (64, 10), (96, 16), (128, 16), (512, 16)],
)
def test_prompt_cache_scales_with_memory_and_stays_off_on_small_machines(monkeypatch, total_ram_gb, expected_gib):
    monkeypatch.delenv("BASIL_LLAMA_CPP_PROMPT_CACHE_GB", raising=False)

    plan = build_llama_cpp_load_plan(
        hardware_profile=_profile(total_ram_gb=total_ram_gb),
        registry_config={"context_window": 40960},
        gguf_context_window=40960,
    )

    assert plan.prompt_cache_bytes == expected_gib * GIBIBYTE


def test_prompt_cache_default_is_larger_than_the_library_default_that_cannot_hold_a_snapshot(monkeypatch):
    monkeypatch.delenv("BASIL_LLAMA_CPP_PROMPT_CACHE_GB", raising=False)

    plan = build_llama_cpp_load_plan(hardware_profile=_profile(), registry_config={"context_window": 40960}, gguf_context_window=40960)

    assert plan.prompt_cache_bytes > 2 * GIBIBYTE


def test_prompt_cache_environment_override_sets_the_size(monkeypatch):
    monkeypatch.setenv("BASIL_LLAMA_CPP_PROMPT_CACHE_GB", "6.5")

    plan = build_llama_cpp_load_plan(
        hardware_profile=_profile(total_ram_gb=16),
        registry_config={"context_window": 8192},
        gguf_context_window=8192,
    )

    assert plan.prompt_cache_bytes == int(6.5 * GIBIBYTE)


def test_prompt_cache_environment_override_of_zero_turns_it_off(monkeypatch):
    monkeypatch.setenv("BASIL_LLAMA_CPP_PROMPT_CACHE_GB", "0")

    plan = build_llama_cpp_load_plan(hardware_profile=_profile(), registry_config={"context_window": 8192}, gguf_context_window=8192)

    assert plan.prompt_cache_bytes == 0


@pytest.mark.parametrize("value", ["lots", "-3", "nan-ish"])
def test_prompt_cache_ignores_unusable_override_values(monkeypatch, value):
    monkeypatch.setenv("BASIL_LLAMA_CPP_PROMPT_CACHE_GB", value)

    plan = build_llama_cpp_load_plan(hardware_profile=_profile(), registry_config={"context_window": 8192}, gguf_context_window=8192)

    assert plan.prompt_cache_bytes == 16 * GIBIBYTE


def test_prompt_cache_size_is_not_passed_to_llama_as_a_keyword():
    plan = build_llama_cpp_load_plan(hardware_profile=_profile(), registry_config={"context_window": 8192}, gguf_context_window=8192)

    assert "prompt_cache_bytes" not in plan.to_llama_kwargs("/tmp/model.gguf")
