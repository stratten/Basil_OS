"""Tests for registry-backed runtime model profile resolution."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import pytest

from api.core.models.base_model import ModelState
from api.core.models.model_types import ModelCapability
from api.core.models.reasoning.model_runtime_profile import (
    get_langchain_max_output_tokens,
    profile_supports_capability,
    resolve_local_output_budget,
    resolve_local_reasoning_mode,
    resolve_local_sampling,
    resolve_runtime_model_profile,
)
from api.core.models.reasoning.openai_model import OpenAIModel


def test_gpt_5_1_profile_includes_vision_from_registry():
    o = OpenAIModel(Path("/tmp"), {ModelCapability.REASONING})
    o.model_name = "gpt-5.1"
    o.state = ModelState.READY
    p = resolve_runtime_model_profile(o)
    assert p.model_id == "gpt-5.1"
    assert profile_supports_capability(p, "vision")
    assert profile_supports_capability(p, "reasoning")
    assert p.max_output_tokens is not None and p.max_output_tokens > 0


def test_gpt_5_nano_profile_excludes_vision():
    o = OpenAIModel(Path("/tmp"), {ModelCapability.REASONING})
    o.model_name = "gpt-5-nano"
    o.state = ModelState.READY
    p = resolve_runtime_model_profile(o)
    assert not profile_supports_capability(p, "vision")


def test_openai_max_tokens_uses_max_output_not_missing_attr():
    o = OpenAIModel(Path("/tmp"), {ModelCapability.REASONING})
    o.model_name = "gpt-5.1"
    o.state = ModelState.READY
    assert not hasattr(o, "max_tokens_to_sample")
    p = resolve_runtime_model_profile(o)
    mt = get_langchain_max_output_tokens(p, o)
    assert isinstance(mt, int)
    assert mt >= 1


def test_unknown_model_falls_back_to_instance_attrs():
    stub = SimpleNamespace(
        model_name="custom-unknown-xyz",
        max_context_length=8000,
        max_output_tokens=2000,
    )
    p = resolve_runtime_model_profile(stub)
    assert p.registry_entry is None
    assert p.context_window == 8000
    assert get_langchain_max_output_tokens(p, stub) == 2000


def test_local_coder_profile_exposes_location_and_local_generation():
    stub = SimpleNamespace(
        model_name="Qwen-qwen3-coder-30b-a3b-instruct-q4km",
        max_context_length=32768,
        max_tokens_to_sample=65536,
        model_path=Path("qwen3-coder-30b-a3b-instruct-q4km.gguf"),
    )
    profile = resolve_runtime_model_profile(stub)
    assert profile.location == "local"
    assert profile.handler == "llama_cpp"
    assert profile.local_generation.get("reasoning_mode") == "none"
    assert resolve_local_reasoning_mode(profile) == "none"
    assert resolve_local_sampling(profile)["temperature"] == 0.7
    assert resolve_local_output_budget(profile, "agent_execution") == 8192
