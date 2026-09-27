from pathlib import Path

from api import settings as api_settings_module
from api.core.services import model_service as model_service_module
from api.core.services.model_download_manager import DownloadManager
from api.services.transcription.backends.parakeet_components import parakeet_model_manager


def _clear_settings_caches() -> None:
    api_settings_module.get_settings.cache_clear()
    model_service_module.get_model_service.cache_clear()


def test_get_models_dir_uses_api_settings_models_dir(monkeypatch, tmp_path: Path) -> None:
    canonical_dir = tmp_path / "canonical-models"
    monkeypatch.setenv("BASIL_MODELS_DIR", str(canonical_dir))
    _clear_settings_caches()

    try:
        resolved = api_settings_module.get_models_dir()
    finally:
        _clear_settings_caches()

    assert resolved == canonical_dir
    assert resolved.exists()


def test_model_service_and_download_manager_share_canonical_models_dir(
    monkeypatch,
    tmp_path: Path,
) -> None:
    canonical_dir = tmp_path / "models"
    misleading_cache_dir = tmp_path / "data" / "models"
    monkeypatch.setenv("BASIL_MODELS_DIR", str(canonical_dir))
    monkeypatch.setattr(
        "api.core.services.model_download_manager.api_settings.MODEL_CACHE_DIR",
        misleading_cache_dir,
    )
    _clear_settings_caches()

    try:
        model_service = model_service_module.get_model_service()
        download_manager = DownloadManager()
    finally:
        _clear_settings_caches()

    assert model_service.models_dir == canonical_dir
    assert download_manager._models_dir == canonical_dir
    assert download_manager._models_dir != misleading_cache_dir


def test_parakeet_bundle_resolution_prefers_canonical_models_dir(
    monkeypatch,
    tmp_path: Path,
) -> None:
    canonical_root = tmp_path / "models"
    data_cache_root = tmp_path / "data" / "models"
    bundle_name = "parakeet-test-bundle"
    canonical_bundle = canonical_root / bundle_name
    data_cache_bundle = data_cache_root / bundle_name
    canonical_bundle.mkdir(parents=True)
    data_cache_bundle.mkdir(parents=True)
    monkeypatch.setenv("BASIL_MODELS_DIR", str(canonical_root))
    monkeypatch.setattr(parakeet_model_manager.settings, "MODEL_CACHE_DIR", data_cache_root)
    _clear_settings_caches()

    try:
        resolved = parakeet_model_manager._resolve_bundle_dir(bundle_name)
    finally:
        _clear_settings_caches()

    assert resolved == canonical_bundle
