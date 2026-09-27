from pathlib import Path
from types import SimpleNamespace

from api.core.models.reasoning.streaming_contract import resolve_generation_budget


class _LocalCoder:
    model_name = "Qwen-qwen3-coder-30b-a3b-instruct-q4km"
    model_path = Path("qwen3-coder-30b-a3b-instruct-q4km.gguf")
    max_context_length = 32768
    max_tokens_to_sample = 65536


class _CloudLike:
    model_name = "cloud-like"
    max_context_length = 32768
    max_output_tokens = 65536


def test_local_coder_uses_registry_budget_by_purpose() -> None:
    model = _LocalCoder()
    assert resolve_generation_budget(model, purpose="decision").effective_output_tokens == 512
    assert resolve_generation_budget(model, purpose="structured").effective_output_tokens == 2048
    assert resolve_generation_budget(model, purpose="narrative").effective_output_tokens == 2048
    assert resolve_generation_budget(model, purpose="activity_analysis").effective_output_tokens == 4096
    assert resolve_generation_budget(model, purpose="general").effective_output_tokens == 4096
    assert resolve_generation_budget(model, purpose="agent_execution").effective_output_tokens == 8192
    assert resolve_generation_budget(model, purpose="final_synthesis").effective_output_tokens == 16384


def test_qwen35_activity_analysis_uses_measured_registry_budget() -> None:
    model = SimpleNamespace(
        model_name="Qwen-qwen35-4b-q4km",
        model_path=Path("qwen35-4b-q4km.gguf"),
        max_context_length=262144,
        max_tokens_to_sample=4096,
    )

    budget = resolve_generation_budget(model, purpose="activity_analysis")

    assert budget.requested_output_tokens == 1024
    assert budget.effective_output_tokens == 1024


def test_explicit_local_request_is_honored_but_capped() -> None:
    model = _LocalCoder()
    assert resolve_generation_budget(
        model,
        purpose="decision",
        requested_output_tokens=320,
    ).effective_output_tokens == 320
    assert resolve_generation_budget(
        model,
        purpose="decision",
        requested_output_tokens=100000,
    ).effective_output_tokens == 65536


def test_context_residual_clamps_local_output() -> None:
    model = _LocalCoder()
    budget = resolve_generation_budget(
        model,
        purpose="final_synthesis",
        input_token_estimate=32000,
    )
    assert budget.effective_output_tokens == 768


def test_unknown_or_cloud_profiles_retain_existing_ceiling_behavior() -> None:
    cloud = _CloudLike()
    assert resolve_generation_budget(cloud, purpose="decision").effective_output_tokens == 65536
    unknown_local = SimpleNamespace(
        model_name="unknown-local",
        max_context_length=8192,
        max_tokens_to_sample=4096,
        model_path=Path("unknown-local.gguf"),
    )
    assert resolve_generation_budget(
        unknown_local,
        purpose="decision",
    ).effective_output_tokens == 4096
