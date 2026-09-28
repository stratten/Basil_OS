from pathlib import Path
from types import SimpleNamespace

import pytest

from api.core.models.models_registry import (
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI,
    get_api_endpoint,
    get_default_enabled_for_provider,
    get_downloadable_models,
    get_model,
    get_omitted_request_parameters,
    get_reasoning_effort_default,
    get_thinking_request_config,
    requires_responses_api,
)
from api.core.models.base_model import ModelState
from api.core.models.model_types import ModelCapability
from api.core.models.models_registry.local_vision_registry import local_vision_files_present
from api.core.models.reasoning.auth_proxy_model import AuthProxyModel
from api.core.models.reasoning.claude_model import ClaudeModel
from api.services.agent_processing.lifecycle.execution_graph.auth_proxy_langchain_adapter import (
    create_langchain_llm_from_auth_proxy,
)
from langchain_core.messages import HumanMessage


def test_larger_local_reasoning_models_are_downloadable() -> None:
    downloadable = get_downloadable_models()

    expected = {
        "Qwen-qwen3-30b-a3b-q4km": {
            "download_url": "https://huggingface.co/Qwen/Qwen3-30B-A3B-GGUF/resolve/main/Qwen3-30B-A3B-Q4_K_M.gguf",
            "on_disk_name": "qwen3-30b-a3b-q4km",
            "context_window": 40960,
            "size": "18.6GB",
            "features": ["gpu_acceleration", "quantization", "function_calling"],
        },
        "Qwen-qwen35-4b-q4km": {
            "download_url": "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf",
            "on_disk_name": "qwen35-4b-q4km",
            "context_window": 262144,
            "size": "2.78GB",
            "features": ["gpu_acceleration", "quantization", "function_calling"],
        },
        "Qwen-qwen36-35b-a3b-ud-q4km": {
            "download_url": (
                "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/"
                "Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
            ),
            "on_disk_name": "qwen36-35b-a3b-ud-q4km",
            "context_window": 262144,
            "size": "18GB",
            "features": ["gpu_acceleration", "quantization", "function_calling"],
        },
        "Google-gemma4-e4b-it-qat-q4_0": {
            "download_url": (
                "https://huggingface.co/google/gemma-4-E4B-it-qat-q4_0-gguf/resolve/main/"
                "gemma-4-E4B_q4_0-it.gguf"
            ),
            "on_disk_name": "gemma4-e4b-it-qat-q4_0",
            "context_window": 128000,
            "size": "5.15GB",
            "features": ["gpu_acceleration", "quantization"],
        },
        "Microsoft-phi4-mini-q4km": {
            "download_url": (
                "https://huggingface.co/tensorblock/Phi-4-mini-instruct-GGUF/resolve/main/"
                "Phi-4-mini-instruct-Q4_K_M.gguf"
            ),
            "on_disk_name": "phi4-mini-instruct-q4km",
            "context_window": 128000,
            "size": "2.49GB",
            "features": ["gpu_acceleration", "quantization", "function_calling"],
        },
        "HuggingFace-smollm3-3b-q4km": {
            "download_url": (
                "https://huggingface.co/Edge-Quant/SmolLM3-3B-Q4_K_M-GGUF/resolve/main/"
                "smollm3-3b-q4_k_m.gguf"
            ),
            "on_disk_name": "smollm3-3b-q4km",
            "context_window": 128000,
            "size": "1.92GB",
            "features": ["gpu_acceleration", "quantization", "function_calling"],
        },
    }

    for model_id, assertions in expected.items():
        cfg = get_model(model_id)
        assert cfg is not None
        assert model_id in downloadable
        assert cfg.get("handler") == "llama_cpp"
        assert cfg.get("capabilities") == ["reasoning"]
        for key, value in assertions.items():
            assert cfg.get(key) == value


def test_qwen_coder_models_are_opt_in_with_local_generation_profiles(tmp_path: Path) -> None:
    from api.core.models.model_download.artifacts import ModelArtifactStore

    downloadable = get_downloadable_models()
    coder_30 = get_model("Qwen-qwen3-coder-30b-a3b-instruct-q4km")
    coder_next = get_model("Qwen-qwen3-coder-next-q4km")

    assert coder_30 is not None
    assert coder_next is not None
    assert "Qwen-qwen3-coder-30b-a3b-instruct-q4km" in downloadable
    assert "Qwen-qwen3-coder-next-q4km" in downloadable

    for cfg in (coder_30, coder_next):
        assert cfg.get("recommended") is False
        assert cfg.get("recommended_for_onboarding") is False
        assert cfg.get("context_window") == 32768
        assert cfg.get("max_output_tokens") == 65536
        assert cfg.get("tool_call_format") == "function_parameter_tags"
        local_generation = cfg.get("local_generation")
        assert isinstance(local_generation, dict)
        assert local_generation.get("reasoning_mode") == "none"

    assert coder_30.get("local_generation", {}).get("sampling") == {
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 20,
        "min_p": None,
        "repeat_penalty": 1.05,
    }
    assert coder_next.get("local_generation", {}).get("sampling") == {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 40,
        "min_p": 0.0,
        "repeat_penalty": 1.0,
    }
    assert len(coder_next.get("artifact_files") or []) == 4

    store = ModelArtifactStore(tmp_path, tmp_path / "legacy")
    assert store.artifact_manifest_is_complete(coder_next, tmp_path) is False
    root = tmp_path / coder_next["artifact_root"]
    root.mkdir()
    for item in coder_next["artifact_files"]:
        (root / item["file"]).write_bytes(b"x")
    assert store.artifact_manifest_is_complete(coder_next, tmp_path) is True


def test_qwen25vl_32b_download_metadata_and_file_presence(tmp_path: Path) -> None:
    model_id = "Qwen-qwen25vl-32b-instruct-q4km"
    cfg = get_model(model_id)
    downloadable = get_downloadable_models()

    assert cfg is not None
    assert model_id in downloadable
    assert cfg.get("handler") == "llama_cpp_vision"
    assert cfg.get("download_url") == (
        "https://huggingface.co/ggml-org/Qwen2.5-VL-32B-Instruct-GGUF/resolve/main/"
        "Qwen2.5-VL-32B-Instruct-Q4_K_M.gguf"
    )
    assert cfg.get("main_model_file") == "Qwen2.5-VL-32B-Instruct-Q4_K_M.gguf"
    assert cfg.get("mmproj_file") == "mmproj-Qwen2.5-VL-32B-Instruct-f16.gguf"
    assert cfg.get("companion_downloads") == [
        {
            "file": "mmproj-Qwen2.5-VL-32B-Instruct-f16.gguf",
            "download_url": (
                "https://huggingface.co/ggml-org/Qwen2.5-VL-32B-Instruct-GGUF/resolve/main/"
                "mmproj-Qwen2.5-VL-32B-Instruct-f16.gguf"
            ),
        }
    ]
    assert local_vision_files_present(tmp_path, cfg) is False
    (tmp_path / cfg["main_model_file"]).write_bytes(b"main")
    assert local_vision_files_present(tmp_path, cfg) is False
    (tmp_path / cfg["mmproj_file"]).write_bytes(b"mmproj")
    assert local_vision_files_present(tmp_path, cfg) is True


def test_latest_cloud_model_entries_resolve_with_openrouter_ids() -> None:
    expected = {
        "gpt-5.4-mini": (PROVIDER_OPENAI, "openai/gpt-5.4-mini", 400000, 128000),
        "gpt-5.4-nano": (PROVIDER_OPENAI, "openai/gpt-5.4-nano", 400000, 128000),
        "gpt-5.5": (PROVIDER_OPENAI, "openai/gpt-5.5", 1050000, 128000),
        "gpt-5.5-pro": (PROVIDER_OPENAI, "openai/gpt-5.5-pro", 1050000, 128000),
        "gpt-5.6-sol": (PROVIDER_OPENAI, "openai/gpt-5.6-sol", 1050000, 128000),
        "gpt-5.6-terra": (PROVIDER_OPENAI, "openai/gpt-5.6-terra", 1050000, 128000),
        "gpt-5.6-luna": (PROVIDER_OPENAI, "openai/gpt-5.6-luna", 1050000, 128000),
        "gpt-6-astra": (PROVIDER_OPENAI, "openai/gpt-6-astra", 1050000, 128000),
        "gpt-6-sol": (PROVIDER_OPENAI, "openai/gpt-6-sol", 1050000, 128000),
        "gpt-6-luna": (PROVIDER_OPENAI, "openai/gpt-6-luna", 1050000, 128000),
        "claude-opus-5-5": (
            PROVIDER_ANTHROPIC,
            "anthropic/claude-opus-5.5",
            1000000,
            128000,
        ),
        "claude-fable-5-1": (
            PROVIDER_ANTHROPIC,
            "anthropic/claude-fable-5.1",
            1000000,
            128000,
        ),
        "claude-opus-5": (
            PROVIDER_ANTHROPIC,
            "anthropic/claude-opus-5",
            1000000,
            128000,
        ),
        "claude-opus-4-5-20251101": (
            PROVIDER_ANTHROPIC,
            "anthropic/claude-opus-4.5",
            200000,
            64000,
        ),
        "gemini-3.8-flash": (
            PROVIDER_GOOGLE,
            "google/gemini-3.8-flash",
            1048576,
            65536,
        ),
        "gemini-3.7-flash": (
            PROVIDER_GOOGLE,
            "google/gemini-3.7-flash",
            1048576,
            65536,
        ),
        "gemini-3.6-flash": (
            PROVIDER_GOOGLE,
            "google/gemini-3.6-flash",
            1048576,
            65536,
        ),
        "gemini-3.5-flash-lite": (
            PROVIDER_GOOGLE,
            "google/gemini-3.5-flash-lite",
            1048576,
            65536,
        ),
        "claude-fable-5": (
            PROVIDER_ANTHROPIC,
            "anthropic/claude-fable-5",
            1000000,
            128000,
        ),
        "claude-sonnet-5": (
            PROVIDER_ANTHROPIC,
            "anthropic/claude-sonnet-5",
            1000000,
            128000,
        ),
        "claude-opus-4-8": (
            PROVIDER_ANTHROPIC,
            "anthropic/claude-opus-4.8",
            1000000,
            128000,
        ),
        "claude-opus-4-7": (
            PROVIDER_ANTHROPIC,
            "anthropic/claude-opus-4.7",
            1000000,
            128000,
        ),
        "claude-sonnet-4-6": (
            PROVIDER_ANTHROPIC,
            "anthropic/claude-sonnet-4.6",
            1000000,
            64000,
        ),
        "claude-haiku-4-5-20251001": (
            PROVIDER_ANTHROPIC,
            "anthropic/claude-haiku-4.5",
            200000,
            65536,
        ),
        "gemini-3.5-flash": (
            PROVIDER_GOOGLE,
            "google/gemini-3.5-flash",
            1048576,
            65536,
        ),
        "gemini-3.1-flash-lite": (
            PROVIDER_GOOGLE,
            "google/gemini-3.1-flash-lite",
            1048576,
            65536,
        ),
    }

    for model_id, (provider, openrouter_id, context_window, max_output) in expected.items():
        cfg = get_model(model_id)
        assert cfg is not None
        assert cfg.get("provider") == provider
        assert cfg.get("openrouter_id") == openrouter_id
        assert cfg.get("context_window") == context_window
        assert cfg.get("max_output_tokens") == max_output
        assert cfg.get("supports_openrouter_proxy") is True


def test_cloud_preference_defaults_absorb_new_model_ids() -> None:
    assert get_default_enabled_for_provider(PROVIDER_OPENAI)["gpt-5.5"] is False
    assert get_default_enabled_for_provider(PROVIDER_OPENAI)["gpt-5.5-pro"] is False
    assert get_default_enabled_for_provider(PROVIDER_OPENAI)["gpt-5.6-sol"] is False
    assert get_default_enabled_for_provider(PROVIDER_OPENAI)["gpt-5.6-terra"] is False
    assert get_default_enabled_for_provider(PROVIDER_OPENAI)["gpt-5.6-luna"] is False
    assert get_default_enabled_for_provider(PROVIDER_ANTHROPIC)["claude-opus-4-7"] is False
    assert get_default_enabled_for_provider(PROVIDER_ANTHROPIC)["claude-sonnet-4-6"] is False
    assert get_default_enabled_for_provider(PROVIDER_ANTHROPIC)["claude-sonnet-5"] is False
    assert get_default_enabled_for_provider(PROVIDER_GOOGLE)["gemini-3.5-flash"] is False
    for model_id in ("gpt-6-astra", "gpt-6-sol", "gpt-6-luna"):
        assert get_default_enabled_for_provider(PROVIDER_OPENAI)[model_id] is False
    for model_id in ("claude-opus-5-5", "claude-fable-5-1", "claude-opus-5", "claude-opus-4-5-20251101"):
        assert get_default_enabled_for_provider(PROVIDER_ANTHROPIC)[model_id] is False
    for model_id in ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"):
        assert get_default_enabled_for_provider(PROVIDER_GOOGLE)[model_id] is False
    assert get_model("claude-opus-4-5-20260115") is None


def test_latest_anthropic_registry_entries_drive_request_parameter_omissions() -> None:
    for model_id in (
        "claude-opus-5-5",
        "claude-fable-5-1",
        "claude-opus-5",
        "claude-fable-5",
        "claude-sonnet-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
    ):
        assert get_omitted_request_parameters(model_id) == [
            "temperature",
            "top_p",
            "top_k",
        ]
    for model_id in ("gpt-6-astra", "gpt-6-sol", "gpt-6-luna"):
        assert get_omitted_request_parameters(model_id) == ["temperature", "top_p"]


def test_always_thinking_anthropic_models_request_adaptive_thinking_only() -> None:
    expected_default_effort = {
        "claude-opus-5-5": "medium",
        "claude-fable-5-1": "high",
        "claude-opus-5": "high",
        "claude-opus-4-7": "high",
    }
    for model_id, default_effort in expected_default_effort.items():
        thinking_cfg = get_thinking_request_config(model_id)
        assert thinking_cfg == {
            "thinking": {"type": "adaptive", "display": "summarized"},
            "effort": default_effort,
            "omit_sampling": True,
        }
        adaptive = get_model(model_id)["feature_config"]["adaptive_thinking"]
        assert adaptive["effort_levels"] == ["low", "medium", "high", "xhigh", "max"]
        assert "extended_thinking" not in get_model(model_id)["features"]


def test_gpt_6_reasoning_levels_match_provider_contract() -> None:
    for model_id in ("gpt-6-astra", "gpt-6-sol", "gpt-6-luna"):
        assert get_api_endpoint(model_id) == "responses"
        assert requires_responses_api(model_id) is True
        assert get_reasoning_effort_default(model_id) == "medium"
    astra_levels = get_model("gpt-6-astra")["feature_config"]["reasoning_effort"]["levels"]
    assert "none" not in astra_levels
    for model_id in ("gpt-6-sol", "gpt-6-luna"):
        assert "none" in get_model(model_id)["feature_config"]["reasoning_effort"]["levels"]


def test_new_gemini_thinking_levels_match_provider_contract() -> None:
    for model_id in ("gemini-3.8-flash", "gemini-3.7-flash"):
        assert get_model(model_id)["feature_config"]["thinking"]["levels"] == ["low", "medium", "high"]
    for model_id in ("gemini-3.6-flash", "gemini-3.5-flash-lite"):
        assert get_model(model_id)["feature_config"]["thinking"]["levels"] == ["minimal", "low", "medium", "high"]


@pytest.mark.asyncio
async def test_claude_sonnet_5_omits_unsupported_temperature_parameter() -> None:
    captured_params = {}

    class FakeStream:
        def __init__(self, **kwargs):
            captured_params.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get_final_message(self):
            return SimpleNamespace(content=[SimpleNamespace(text="ok")])

    class FakeMessages:
        def stream(self, **kwargs):
            return FakeStream(**kwargs)

    model = ClaudeModel(Path("/tmp/basil-cloud-smoke"), {ModelCapability.REASONING})
    model.model_name = "claude-sonnet-5"
    model.state = ModelState.READY
    model._async_client = SimpleNamespace(messages=FakeMessages())

    assert await model.generate_response("Reply with exactly: ok", max_tokens=16, enable_web_search=False) == "ok"
    assert captured_params["model"] == "claude-sonnet-5"
    assert "temperature" not in captured_params


@pytest.mark.asyncio
async def test_auth_proxy_forwards_registry_omissions_without_temperature() -> None:
    captured_payload = {}

    class FakeResponse:
        status_code = 200
        headers = {}
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeClient:
        is_closed = False

        async def post(self, url, json, headers):
            captured_payload.update(json)
            return FakeResponse()

    model = AuthProxyModel("claude-opus-4-7", access_token="token")
    model._client = FakeClient()

    assert await model.generate_response("Reply with exactly: ok", max_tokens=16) == "ok"
    assert captured_payload["model"] == "anthropic/claude-opus-4.7"
    assert captured_payload["omit_parameters"] == ["temperature", "top_p", "top_k"]
    assert "temperature" not in captured_payload


@pytest.mark.asyncio
async def test_auth_proxy_langchain_forwards_registry_omissions_without_temperature(monkeypatch) -> None:
    from api.services.agent_processing.lifecycle.execution_graph.auth_proxy_stream import (
        StreamAccumulator,
    )

    captured_payload = {}
    proxy_model = AuthProxyModel("claude-opus-4-7", access_token="token")
    adapter = create_langchain_llm_from_auth_proxy(proxy_model)

    async def fake_stream_route_request(self, client, payload, run_manager):
        captured_payload.update(payload)
        acc = StreamAccumulator()
        acc.content_parts.append("ok")
        return acc

    monkeypatch.setattr(
        adapter,
        "_stream_route_request",
        fake_stream_route_request.__get__(adapter, adapter.__class__),
    )

    result = await adapter._agenerate([HumanMessage(content="Reply with exactly: ok")])

    assert result.generations[0].message.content == "ok"
    assert captured_payload["model"] == "anthropic/claude-opus-4.7"
    assert captured_payload["omit_parameters"] == ["temperature", "top_p", "top_k"]
    assert "temperature" not in captured_payload


def test_gpt_5_6_models_declare_responses_endpoint_and_reasoning_default() -> None:
    for model_id in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
        assert get_api_endpoint(model_id) == "responses"
        assert requires_responses_api(model_id) is True
        assert get_reasoning_effort_default(model_id) == "medium"


def test_non_reasoning_openai_model_does_not_require_responses_api() -> None:
    assert requires_responses_api("gpt-4o") is False
    assert get_api_endpoint("gpt-4o") is None
    assert get_reasoning_effort_default("gpt-4o") is None
