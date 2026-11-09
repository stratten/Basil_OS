"""Tests for removing the Hugging Face cache copy of an installed model."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict

from api.core.models.model_download.hf_cache_cleanup import (
    discard_cached_repo,
    repo_id_from_model_config,
)
from api.core.models.model_downloader import ModelDownloader


def _write_cached_repo(cache_dir: Path, repo_id: str, commit: str, payload: bytes) -> Path:
    """Lay out one cached model repo exactly as ``huggingface_hub`` does."""
    repo_dir = cache_dir / ("models--" + repo_id.replace("/", "--"))
    blob = repo_dir / "blobs" / ("a" * 40)
    blob.parent.mkdir(parents=True)
    blob.write_bytes(payload)
    snapshot_dir = repo_dir / "snapshots" / commit
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "model.gguf").symlink_to(Path("..") / ".." / "blobs" / blob.name)
    (repo_dir / "refs").mkdir()
    (repo_dir / "refs" / "main").write_text(commit)
    return repo_dir


def test_repo_id_is_read_from_download_or_repo_url() -> None:
    assert (
        repo_id_from_model_config(
            {"download_url": "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/x.gguf"}
        )
        == "unsloth/Qwen3.5-4B-GGUF"
    )
    assert (
        repo_id_from_model_config({"repo_url": "https://huggingface.co/mlx-community/Qwen3-8B-4bit"})
        == "mlx-community/Qwen3-8B-4bit"
    )


def test_repo_id_is_none_for_non_huggingface_or_malformed_urls() -> None:
    assert repo_id_from_model_config({}) is None
    assert repo_id_from_model_config({"download_url": "https://example.com/model.gguf"}) is None
    assert repo_id_from_model_config({"repo_url": "https://huggingface.co/onlyowner"}) is None
    assert repo_id_from_model_config({"repo_url": 7}) is None


def test_discard_removes_only_the_named_repo(tmp_path: Path) -> None:
    cache_dir = tmp_path / "hub"
    target = _write_cached_repo(cache_dir, "owner/target", "1" * 40, b"x" * 2048)
    other = _write_cached_repo(cache_dir, "owner/other", "2" * 40, b"y" * 1024)

    freed = discard_cached_repo("owner/target", cache_dir=cache_dir)

    assert freed == 2048
    assert not target.exists()
    assert (other / "blobs" / ("a" * 40)).read_bytes() == b"y" * 1024
    assert (other / "snapshots" / ("2" * 40) / "model.gguf").is_symlink()


def test_discard_returns_zero_when_cache_or_repo_is_absent(tmp_path: Path) -> None:
    assert discard_cached_repo("owner/target", cache_dir=tmp_path / "missing") == 0

    cache_dir = tmp_path / "hub"
    other = _write_cached_repo(cache_dir, "owner/other", "2" * 40, b"y" * 1024)
    assert discard_cached_repo("owner/target", cache_dir=cache_dir) == 0
    assert other.exists()


def _downloader_with_fake_install(
    tmp_path: Path, monkeypatch: Any, discarded: list[str], model_cfg: Dict[str, Any]
) -> ModelDownloader:
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    monkeypatch.setattr(
        "api.core.models.model_downloader.get_model", lambda model_id: model_cfg
    )
    monkeypatch.setattr(
        "api.core.models.model_downloader.discard_cached_repo",
        lambda repo_id: discarded.append(repo_id) or 0,
    )
    downloader = ModelDownloader(tmp_path / "models")
    monkeypatch.setattr(
        downloader, "_get_model_path_for_id", lambda model_id: tmp_path / "models" / "installed.gguf"
    )

    async def fake_direct_download(*args: Any, **kwargs: Any) -> Path:
        return tmp_path / "models" / "installed.gguf"

    monkeypatch.setattr(
        downloader.direct_file_downloader, "download_direct_file", fake_direct_download
    )
    return downloader


_MODEL_CFG: Dict[str, Any] = {
    "display_name": "Fixture",
    "download_url": "https://huggingface.co/owner/fixture-GGUF/resolve/main/fixture.gguf",
}


def test_successful_download_discards_the_cache_copy(tmp_path: Path, monkeypatch: Any) -> None:
    discarded: list[str] = []
    downloader = _downloader_with_fake_install(tmp_path, monkeypatch, discarded, _MODEL_CFG)

    result = asyncio.run(downloader.download_model("reasoning", "fixture"))

    assert result == tmp_path / "models" / "installed.gguf"
    assert discarded == ["owner/fixture-GGUF"]
    assert downloader._active_repo_downloads == {}


def test_failed_download_keeps_the_cache_so_it_can_resume(tmp_path: Path, monkeypatch: Any) -> None:
    discarded: list[str] = []
    downloader = _downloader_with_fake_install(tmp_path, monkeypatch, discarded, _MODEL_CFG)

    async def failing_download(*args: Any, **kwargs: Any) -> Path:
        raise RuntimeError("network dropped")

    monkeypatch.setattr(downloader.direct_file_downloader, "download_direct_file", failing_download)

    try:
        asyncio.run(downloader.download_model("reasoning", "fixture"))
    except RuntimeError:
        pass
    else:
        raise AssertionError("the download failure must propagate")

    assert discarded == []
    assert downloader._active_repo_downloads == {}


def test_cache_is_kept_while_another_download_from_the_same_repo_runs(
    tmp_path: Path, monkeypatch: Any
) -> None:
    discarded: list[str] = []
    downloader = _downloader_with_fake_install(tmp_path, monkeypatch, discarded, _MODEL_CFG)
    downloader._active_repo_downloads["owner/fixture-GGUF"] = 1

    result = asyncio.run(downloader.download_model("reasoning", "fixture"))

    assert result == tmp_path / "models" / "installed.gguf"
    assert discarded == []
    assert downloader._active_repo_downloads == {"owner/fixture-GGUF": 1}


def test_cache_removal_failure_does_not_fail_the_install(tmp_path: Path, monkeypatch: Any) -> None:
    discarded: list[str] = []
    downloader = _downloader_with_fake_install(tmp_path, monkeypatch, discarded, _MODEL_CFG)

    def exploding_discard(repo_id: str) -> int:
        raise OSError("disk went away")

    monkeypatch.setattr("api.core.models.model_downloader.discard_cached_repo", exploding_discard)

    result = asyncio.run(downloader.download_model("reasoning", "fixture"))

    assert result == tmp_path / "models" / "installed.gguf"
