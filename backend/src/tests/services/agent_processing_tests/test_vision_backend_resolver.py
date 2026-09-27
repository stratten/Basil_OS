"""Tests for resolve_agent_vision_backend and local vision registry wiring."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from api.core.models.models_registry import get_downloadable_models, get_model
from api.core.models.models_registry.local_vision_registry import (
    LOCAL_VISION_MODELS,
    local_vision_files_present,
)
from api.core.models.reasoning.model_runtime_profile import RuntimeModelProfile
from api.services.agent_processing.tools.vision.backend_resolver import (
    VisionBackend,
    resolve_agent_vision_backend,
)


def test_local_vision_registry_entry_exposes_vision_handler() -> None:
    assert "Qwen-qwen25vl-7b-instruct-q4k" in LOCAL_VISION_MODELS
    cfg = get_model("Qwen-qwen25vl-7b-instruct-q4k")
    assert cfg is not None
    assert cfg.get("handler") == "llama_cpp_vision"
    assert "vision" in (cfg.get("capabilities") or [])
    assert cfg.get("manual_install_required") is False
    assert cfg.get("download_url")
    assert cfg.get("companion_downloads")


def test_local_vision_registry_entry_is_downloadable_from_catalog() -> None:
    downloadable = get_downloadable_models()
    cfg = downloadable["Qwen-qwen25vl-7b-instruct-q4k"]
    assert cfg.get("handler") == "llama_cpp_vision"
    assert cfg.get("main_model_file") == "Qwen2.5-VL-7B-Instruct-bf16-q4_k.gguf"
    assert cfg.get("mmproj_file") == "Qwen2.5-VL-7B-Instruct-mmproj-f16.gguf"

    compact_cfg = downloadable["Qwen-qwen25vl-3b-instruct-q4km"]
    assert compact_cfg.get("handler") == "llama_cpp_vision"
    assert compact_cfg.get("main_model_file") == "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
    assert compact_cfg.get("mmproj_file") == "mmproj-F16.gguf"
    assert compact_cfg.get("chat_handler") == "qwen25vl"


def test_resolve_prefers_native_when_registry_has_vision() -> None:
    prefs = MagicMock()
    prefs.models.local_vision_fallback_enabled = False
    prefs.models.local_vision_model_id = "Qwen-qwen25vl-7b-instruct-q4k"
    llm = MagicMock(model_name="gpt-5.1")
    profile = RuntimeModelProfile(
        model_id="gpt-5.1",
        registry_entry=None,
        provider="openai",
        handler=None,
        capabilities=["reasoning", "vision"],
    )
    with patch(
        "api.services.agent_processing.tools.vision.backend_resolver.resolve_runtime_model_profile",
        return_value=profile,
    ):
        assert (
            resolve_agent_vision_backend(llm, prefs, Path("/tmp/models"))
            == VisionBackend.NATIVE
        )


def test_resolve_local_fallback_when_enabled_and_files_present() -> None:
    prefs = MagicMock()
    prefs.models.local_vision_fallback_enabled = True
    prefs.models.local_vision_model_id = "Qwen-qwen25vl-7b-instruct-q4k"
    llm = MagicMock(model_name="gpt-5-nano")
    profile = RuntimeModelProfile(
        model_id="gpt-5-nano",
        registry_entry=None,
        provider="openai",
        handler=None,
        capabilities=["reasoning"],
    )
    with patch(
        "api.services.agent_processing.tools.vision.backend_resolver.resolve_runtime_model_profile",
        return_value=profile,
    ):
        with patch(
            "api.services.agent_processing.tools.vision.backend_resolver.local_vision_files_present",
            return_value=True,
        ):
            assert (
                resolve_agent_vision_backend(llm, prefs, Path("/tmp/models"))
                == VisionBackend.LOCAL_QWEN_VL
            )


def test_resolve_unavailable_when_fallback_off() -> None:
    prefs = MagicMock()
    prefs.models.local_vision_fallback_enabled = False
    prefs.models.local_vision_model_id = "Qwen-qwen25vl-7b-instruct-q4k"
    llm = MagicMock(model_name="gpt-5-nano")
    profile = RuntimeModelProfile(
        model_id="gpt-5-nano",
        registry_entry=None,
        provider="openai",
        handler=None,
        capabilities=["reasoning"],
    )
    with patch(
        "api.services.agent_processing.tools.vision.backend_resolver.resolve_runtime_model_profile",
        return_value=profile,
    ):
        assert (
            resolve_agent_vision_backend(llm, prefs, Path("/tmp/models"))
            == VisionBackend.UNAVAILABLE
        )


def test_local_vision_files_present_requires_both_ggufs(tmp_path: Path) -> None:
    cfg = LOCAL_VISION_MODELS["Qwen-qwen25vl-7b-instruct-q4k"]
    assert local_vision_files_present(tmp_path, cfg) is False
    (tmp_path / cfg["main_model_file"]).write_bytes(b"x")
    assert local_vision_files_present(tmp_path, cfg) is False
    (tmp_path / cfg["mmproj_file"]).write_bytes(b"y")
    assert local_vision_files_present(tmp_path, cfg) is True


def test_compact_local_vision_files_present_requires_main_and_projector(
    tmp_path: Path,
) -> None:
    cfg = LOCAL_VISION_MODELS["Qwen-qwen25vl-3b-instruct-q4km"]
    assert local_vision_files_present(tmp_path, cfg) is False
    (tmp_path / cfg["main_model_file"]).write_bytes(b"main")
    assert local_vision_files_present(tmp_path, cfg) is False
    (tmp_path / cfg["mmproj_file"]).write_bytes(b"mmproj")
    assert local_vision_files_present(tmp_path, cfg) is True


def test_artifact_store_normalizes_local_vision_companion_metadata(tmp_path: Path) -> None:
    from api.core.models.model_download.artifacts import ModelArtifactStore

    cfg = LOCAL_VISION_MODELS["Qwen-qwen25vl-7b-instruct-q4k"]
    store = ModelArtifactStore(tmp_path, tmp_path / "legacy")

    companions = store.get_companion_downloads(cfg)

    assert companions == [
        {
            "file": "Qwen2.5-VL-7B-Instruct-mmproj-f16.gguf",
            "download_url": (
                "https://huggingface.co/Mungert/Qwen2.5-VL-7B-Instruct-GGUF/resolve/main/"
                "Qwen2.5-VL-7B-Instruct-mmproj-f16.gguf"
            ),
        }
    ]


def test_model_downloader_requires_both_local_vision_files_for_installed_status(
    tmp_path: Path,
) -> None:
    from api.core.models.model_downloader import ModelDownloader

    dl = ModelDownloader(tmp_path)
    cfg = LOCAL_VISION_MODELS["Qwen-qwen25vl-7b-instruct-q4k"]
    provider = "Qwen"
    variant = "qwen25vl-7b-instruct-q4k"

    (tmp_path / cfg["main_model_file"]).write_bytes(b"main")
    assert provider not in dl.get_installed_models()

    (tmp_path / cfg["mmproj_file"]).write_bytes(b"mmproj")
    installed = dl.get_installed_models()
    assert installed[provider]["variants"][variant]["valid"] is True


@pytest.mark.asyncio
async def test_model_downloader_downloads_local_vision_companion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.core.models.model_downloader import ModelDownloader

    models_dir = tmp_path / "models"
    cache_dir = tmp_path / "hf-cache"
    cache_dir.mkdir()

    def fake_hf_hub_download(
        repo_id: str,
        filename: str,
        revision: str,
        local_files_only: bool,
        force_download: bool,
        resume_download: bool,
    ) -> str:
        cached_file = cache_dir / Path(filename).name
        cached_file.write_bytes(b"mmproj")
        return str(cached_file)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_hf_hub_download)

    dl = ModelDownloader(models_dir)
    cfg = LOCAL_VISION_MODELS["Qwen-qwen25vl-7b-instruct-q4k"]
    await dl._download_companion_files("Qwen", "qwen25vl-7b-instruct-q4k", cfg)

    assert (models_dir / cfg["mmproj_file"]).read_bytes() == b"mmproj"


def test_model_downloader_remove_model_deletes_local_vision_companion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

    from api.core.models.model_downloader import ModelDownloader

    models_dir = tmp_path / "models"
    dl = ModelDownloader(models_dir)
    cfg = LOCAL_VISION_MODELS["Qwen-qwen25vl-7b-instruct-q4k"]

    (models_dir / cfg["main_model_file"]).write_bytes(b"main")
    (models_dir / cfg["mmproj_file"]).write_bytes(b"mmproj")

    assert dl.remove_model("Qwen", "qwen25vl-7b-instruct-q4k") is True
    assert not (models_dir / cfg["main_model_file"]).exists()
    assert not (models_dir / cfg["mmproj_file"]).exists()
