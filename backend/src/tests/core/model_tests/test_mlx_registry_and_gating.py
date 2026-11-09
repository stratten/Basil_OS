"""The 12 MLX registry entries obey the registry's invariants and mirror their GGUF entries, and the registry shows MLX as the default on a machine that can run it and hides it on one that cannot."""

import importlib.util
import platform
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.core.models.model_download.snapshot_downloader import build_snapshot_patterns
from api.core.models.model_downloader import ModelDownloader
from api.core.models.models_registry import (
    ModelHandler,
    get_downloadable_models,
    get_local_reasoning_models,
    get_model,
    is_in_registry,
)
from api.core.models.models_registry.local_reasoning_registry import LOCAL_GGUF_MODELS, LOCAL_HF_MODELS
from api.core.models.preference_models.defaults import _get_default_local_reasoning_model_id
from api.core.models.reasoning.mlx_model import MlxModel
from api.core.models.reasoning.model_runtime_profile import (
    _is_local_reasoning_profile,
    resolve_runtime_model_profile,
)
from api.core.runtime import mlx_support
from api.core.services.model_service import HANDLER_CLASS_MAP
from api.services.setup_assistant.discovery_service import SetupAssistantDiscoveryService

MLX_TO_GGUF = {
    "Qwen-qwen3-8b-mlx-4bit": "Qwen-qwen3-8b-instruct-q4km",
    "Qwen-qwen3-30b-a3b-instruct-2507-mlx-4bit": "Qwen-qwen3-30b-a3b-q4km",
    "Qwen-qwen3-coder-30b-a3b-instruct-mlx-4bit": "Qwen-qwen3-coder-30b-a3b-instruct-q4km",
    "Qwen-qwen3-coder-next-mlx-4bit": "Qwen-qwen3-coder-next-q4km",
    "Qwen-qwen35-4b-mlx-4bit": "Qwen-qwen35-4b-q4km",
    "Qwen-qwen35-9b-mlx-4bit": "Qwen-qwen35-9b-q4km",
    "Qwen-qwen36-35b-a3b-mlx-4bit": "Qwen-qwen36-35b-a3b-ud-q4km",
    "Google-gemma4-e4b-it-qat-mlx-4bit": "Google-gemma4-e4b-it-qat-q4_0",
    "Microsoft-phi4-mini-mlx-4bit": "Microsoft-phi4-mini-q4km",
    "HuggingFace-smollm3-3b-mlx-4bit": "HuggingFace-smollm3-3b-q4km",
    "Mistral-ministral3-8b-instruct-mlx-4bit": "Mistral-ministral3-8b-instruct-q4km",
    "Mistral-ministral3-14b-instruct-mlx-4bit": "Mistral-ministral3-14b-instruct-q4km",
}
EXPECTED_MLX_IDS = set(MLX_TO_GGUF)
MIRRORED_FIELDS = (
    "provider",
    "context_window",
    "max_output_tokens",
    "features",
    "recommended_ram",
    "speed_rating",
    "accuracy_rating",
    "recommended",
    "recommended_for_onboarding",
    "tool_rendering",
    "tool_call_format",
    "local_generation",
)
MLX_9B = "Qwen-qwen35-9b-mlx-4bit"
GGUF_9B = "Qwen-qwen35-9b-q4km"


@pytest.fixture(autouse=True)
def mlx_supported(monkeypatch):
    """Every test here starts on a machine that can run MLX, so the result does not depend on the machine running the suite. Tests of the other case patch it back."""
    monkeypatch.setattr(mlx_support, "mlx_runtime_available", lambda: True)


@pytest.fixture(autouse=True)
def roomy_machine(monkeypatch):
    """Every test here also starts on a machine with enough memory for the 9B but not enough for the larger upgrade, so the starter selection does not depend on the machine running the suite. The fallback and the upgrade have their own tests."""
    monkeypatch.setattr("api.core.models.preference_models.defaults._detected_total_ram_gb", lambda: 32)


def _mlx_entries():
    """The raw registry entries, which exist on every platform. The accessors hide them where MLX cannot run."""
    return {model_id: config for model_id, config in LOCAL_HF_MODELS.items() if config.get("handler") == "mlx"}


def test_exactly_the_expected_mlx_entries_exist():
    assert set(_mlx_entries()) == EXPECTED_MLX_IDS


def test_every_gguf_entry_has_exactly_one_mlx_entry_and_is_flagged_as_superseded():
    assert set(MLX_TO_GGUF.values()) == set(LOCAL_GGUF_MODELS)
    assert len(set(MLX_TO_GGUF.values())) == len(MLX_TO_GGUF)
    for gguf_id, config in LOCAL_GGUF_MODELS.items():
        assert config.get("superseded_by_mlx") is True, gguf_id
    for config in _mlx_entries().values():
        assert "superseded_by_mlx" not in config


@pytest.mark.parametrize("mlx_id", sorted(EXPECTED_MLX_IDS))
def test_each_mlx_entry_mirrors_the_gguf_entry_for_the_same_model(mlx_id):
    mlx_config = _mlx_entries()[mlx_id]
    gguf_config = LOCAL_GGUF_MODELS[MLX_TO_GGUF[mlx_id]]
    for field in MIRRORED_FIELDS:
        assert mlx_config.get(field) == gguf_config.get(field), (mlx_id, field)
    assert "MLX 4-bit" in mlx_config["display_name"]


@pytest.mark.parametrize("model_id", sorted(EXPECTED_MLX_IDS))
def test_each_mlx_entry_obeys_the_registry_invariants(model_id):
    config = _mlx_entries()[model_id]
    assert config["handler"] == ModelHandler.MLX.value
    assert config["location"] == "local"
    assert config["capabilities"] == ["reasoning"]
    assert config["repo_url"].startswith("https://huggingface.co/mlx-community/")
    assert re.fullmatch(r"[0-9a-f]{40}", config["revision"])
    assert re.fullmatch(r"[a-z0-9-]+", config["on_disk_name"])
    assert "." not in config["on_disk_name"]
    assert config["context_window"] > 0 and config["max_output_tokens"] > 0
    assert isinstance(config["speed_rating"], int) and isinstance(config["accuracy_rating"], int)


def test_no_local_model_folder_name_is_matched_by_another_models_glob():
    names = {
        model_id: str(config["on_disk_name"])
        for model_id, config in {**LOCAL_GGUF_MODELS, **LOCAL_HF_MODELS}.items()
        if config.get("on_disk_name")
    }
    assert len(set(names.values())) == len(names)
    for first_id, first in names.items():
        for second_id, second in names.items():
            if first_id != second_id:
                assert not first.startswith(second), (first_id, second_id)


def test_the_handler_maps_to_the_mlx_model_class():
    assert HANDLER_CLASS_MAP[ModelHandler.MLX] is MlxModel


def test_a_model_folder_resolves_to_its_registry_entry_and_the_local_profile_rules():
    model = SimpleNamespace(model_path=Path("/models/qwen35-9b-mlx-4bit"))
    profile = resolve_runtime_model_profile(model)
    assert profile.model_id == "Qwen-qwen35-9b-mlx-4bit"
    assert profile.handler == "mlx"
    assert profile.location == "local"
    assert profile.tool_call_format == "function_parameter_tags"
    assert _is_local_reasoning_profile(profile)


def test_mlx_downloads_include_chat_templates_and_other_models_are_unchanged():
    mlx_allow, mlx_ignore = build_snapshot_patterns(
        "Qwen-qwen35-4b-mlx-4bit", _mlx_entries()["Qwen-qwen35-4b-mlx-4bit"]
    )
    assert {"*.safetensors", "*.json", "*.jinja", "*.txt"} <= set(mlx_allow)
    assert "*.gguf" in mlx_ignore

    default_allow, default_ignore = build_snapshot_patterns("Qwen-qwen3-4b", get_local_reasoning_models()["Qwen-qwen3-4b"])
    assert default_allow == ["*.safetensors", "*.json", "*.txt", "tokenizer.model"]
    assert default_ignore == ["*.h5", "*.bin", "*.msgpack", "*.ot", "*fp32*"]


def test_runtime_availability_requires_apple_silicon_and_both_packages(monkeypatch):
    # Undo the autouse fixture's fake so the real function runs. The package lookup is cached for the life of the process, so each step clears it, and the cache is cleared again at the end so a faked answer never leaks into another test.
    monkeypatch.undo()
    found = object()

    def both_present(name):
        return found

    def only_mlx(name):
        return found if name == "mlx" else None

    try:
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        monkeypatch.setattr(platform, "machine", lambda: "arm64")
        monkeypatch.setattr(importlib.util, "find_spec", both_present)
        mlx_support._mlx_packages_installed.cache_clear()
        assert mlx_support.mlx_runtime_available() is True

        monkeypatch.setattr(importlib.util, "find_spec", only_mlx)
        mlx_support._mlx_packages_installed.cache_clear()
        assert mlx_support.mlx_runtime_available() is False

        monkeypatch.setattr(importlib.util, "find_spec", both_present)
        mlx_support._mlx_packages_installed.cache_clear()
        monkeypatch.setattr(platform, "machine", lambda: "x86_64")
        assert mlx_support.mlx_runtime_available() is False

        monkeypatch.setattr(platform, "machine", lambda: "arm64")
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        assert mlx_support.mlx_runtime_available() is False
    finally:
        monkeypatch.undo()
        mlx_support._mlx_packages_installed.cache_clear()


def test_only_mlx_models_are_gated_by_the_runtime(monkeypatch):
    monkeypatch.setattr(mlx_support, "mlx_runtime_available", lambda: False)
    assert mlx_support.model_runtime_available({"handler": "llama_cpp"}) is True
    assert mlx_support.model_runtime_available({}) is True
    assert mlx_support.model_runtime_available({"handler": "mlx"}) is False
    monkeypatch.setattr(mlx_support, "mlx_runtime_available", lambda: True)
    assert mlx_support.model_runtime_available({"handler": "mlx"}) is True


def _available_mlx_ids(tmp_path):
    available = ModelDownloader(tmp_path).get_available_models()
    return {
        variant["model_id"]
        for provider in available.values()
        for variant in provider["variants"].values()
        if variant.get("handler") == "mlx"
    }


def test_the_available_models_list_hides_mlx_on_an_unsupported_mac(tmp_path, monkeypatch):
    monkeypatch.setattr(mlx_support, "mlx_runtime_available", lambda: False)
    assert _available_mlx_ids(tmp_path) == set()


def test_the_available_models_list_shows_mlx_on_a_supported_mac(tmp_path, monkeypatch):
    monkeypatch.setattr(mlx_support, "mlx_runtime_available", lambda: True)
    assert _available_mlx_ids(tmp_path) == EXPECTED_MLX_IDS


def test_where_mlx_cannot_run_no_mlx_model_exists_and_the_gguf_defaults_are_unchanged(monkeypatch):
    monkeypatch.setattr(mlx_support, "mlx_runtime_available", lambda: False)

    assert not any(config.get("handler") == "mlx" for config in get_local_reasoning_models().values())
    assert not any(config.get("handler") == "mlx" for config in get_downloadable_models().values())
    for mlx_id in EXPECTED_MLX_IDS:
        assert get_model(mlx_id) is None
        assert is_in_registry(mlx_id) is False
    gguf_9b = get_model(GGUF_9B)
    assert gguf_9b["recommended"] is True and gguf_9b["recommended_for_onboarding"] is True
    assert _get_default_local_reasoning_model_id() == GGUF_9B


def test_where_mlx_can_run_the_mlx_entry_is_the_default_and_the_gguf_entry_stays_available():
    local = get_local_reasoning_models()
    assert {model_id for model_id, config in local.items() if config.get("handler") == "mlx"} == EXPECTED_MLX_IDS

    mlx_9b = get_model(MLX_9B)
    assert mlx_9b["recommended"] is True and mlx_9b["recommended_for_onboarding"] is True
    gguf_9b = get_model(GGUF_9B)
    assert gguf_9b is not None
    assert gguf_9b["recommended"] is False and gguf_9b["recommended_for_onboarding"] is False
    assert GGUF_9B in get_downloadable_models() and MLX_9B in get_downloadable_models()

    flagged = [model_id for model_id, config in local.items() if config.get("recommended_for_onboarding") is True]
    assert flagged == [MLX_9B]
    assert _get_default_local_reasoning_model_id() == MLX_9B


def test_the_host_view_copies_the_entry_and_never_edits_the_registry():
    get_local_reasoning_models()
    get_model(GGUF_9B)
    assert LOCAL_GGUF_MODELS[GGUF_9B]["recommended"] is True
    assert LOCAL_GGUF_MODELS[GGUF_9B]["recommended_for_onboarding"] is True


@pytest.mark.asyncio
async def test_setup_assistant_lists_the_mlx_entry_where_mlx_runs_and_not_elsewhere(monkeypatch):
    service = SetupAssistantDiscoveryService(model_service=None)

    response = await service.collect_model_catalog_facts()
    suggested = {fact.value for fact in response.facts}
    assert MLX_9B in suggested and GGUF_9B in suggested

    monkeypatch.setattr(mlx_support, "mlx_runtime_available", lambda: False)
    response = await service.collect_model_catalog_facts()
    suggested = {fact.value for fact in response.facts}
    assert suggested.isdisjoint(EXPECTED_MLX_IDS)
    assert GGUF_9B in suggested


def _hardware(gpu_available):
    return SimpleNamespace(
        total_ram_gb=96,
        local_model_memory_budget_gb=64,
        gpu_available=gpu_available,
        gpu_backend="metal" if gpu_available else None,
        prefer_coreml_onnx=False,
        prefer_mlx_whisper=False,
        faster_whisper_available=False,
        memory_tier="high",
    )


def test_the_hardware_hint_for_an_mlx_model_names_metal_only_with_a_gpu():
    service = SetupAssistantDiscoveryService(model_service=None)
    config = {"handler": "mlx", "features": ["gpu_acceleration"], "recommended_ram": "16GB"}
    assert service._build_model_hardware_metadata(config, _hardware(True))["hardware_recommended_backend"] == "mlx_metal"
    assert service._build_model_hardware_metadata(config, _hardware(False))["hardware_recommended_backend"] == "cpu"


@pytest.mark.asyncio
async def test_the_download_route_answers_not_found_for_mlx_on_an_unsupported_mac(monkeypatch):
    from fastapi import HTTPException

    from api.routes.model_routes.predefined_routes import (
        DownloadRequest,
        ModelDownloadRequest,
        download_model,
    )

    monkeypatch.setattr(mlx_support, "mlx_runtime_available", lambda: False)
    body = DownloadRequest(request=ModelDownloadRequest(model_type="Qwen", variant="qwen35-4b-mlx-4bit"))

    with pytest.raises(HTTPException) as caught:
        await download_model(body, http_request=SimpleNamespace())

    assert caught.value.status_code == 404
    assert "not found" in caught.value.detail


def _starter_service(installed):
    return SimpleNamespace(is_model_downloaded=lambda model_type, variant: f"{model_type}-{variant}" in installed)


def _starter_reasoning(models):
    return next((entry["model_type"], entry["variant"]) for entry in models if entry["model_type"] == "Qwen")


def test_a_new_install_that_can_run_mlx_gets_the_mlx_reasoning_model():
    from api.routes.onboarding import get_starter_models

    assert _starter_reasoning(get_starter_models(_starter_service(set()))) == ("Qwen", "qwen35-9b-mlx-4bit")


def test_a_new_install_that_cannot_run_mlx_gets_the_gguf_reasoning_model(monkeypatch):
    from api.routes.onboarding import get_starter_models

    monkeypatch.setattr(mlx_support, "mlx_runtime_available", lambda: False)
    assert _starter_reasoning(get_starter_models(_starter_service(set()))) == ("Qwen", "qwen35-9b-q4km")


def test_an_install_that_already_has_the_gguf_build_is_not_asked_for_the_mlx_build():
    from api.routes.onboarding import get_starter_models

    models = get_starter_models(_starter_service({GGUF_9B}))
    assert _starter_reasoning(models) == ("Qwen", "qwen35-9b-q4km")


def test_an_install_that_already_has_the_mlx_build_keeps_it():
    from api.routes.onboarding import get_starter_models

    models = get_starter_models(_starter_service({MLX_9B}))
    assert _starter_reasoning(models) == ("Qwen", "qwen35-9b-mlx-4bit")


def test_the_starter_pack_has_one_reasoning_model_and_the_unchanged_transcription_models():
    from api.routes.onboarding import get_starter_models

    models = get_starter_models(_starter_service(set()))
    assert [(entry["model_type"], entry["variant"], entry["priority"]) for entry in models[:2]] == [
        ("OpenAI", "whisper-tiny.en", 1),
        ("NVIDIA", "parakeet-tdt-0.6b-v3-quantized", 2),
    ]
    assert len(models) == 3 and models[2]["priority"] == 3
    assert "GB" in models[2]["description"]
