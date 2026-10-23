from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from api.core.models.model_download.artifacts import ModelArtifactStore


def _manifest() -> dict:
    payloads = [b"one", b"two", b"three", b"four"]
    return {
        "artifact_root": "qwen-next",
        "primary_artifact": "model-00001-of-00004.gguf",
        "artifact_files": [
            {
                "file": f"model-{index:05d}-of-00004.gguf",
                "download_url": (
                    "https://huggingface.co/example/repo/resolve/main/"
                    f"model-{index:05d}-of-00004.gguf"
                ),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
            }
            for index, payload in enumerate(payloads, start=1)
        ],
    }


def test_manifest_requires_every_declared_shard(tmp_path: Path) -> None:
    store = ModelArtifactStore(tmp_path, tmp_path / "legacy")
    config = _manifest()
    root = tmp_path / config["artifact_root"]
    root.mkdir()
    (root / config["primary_artifact"]).write_bytes(b"one")

    assert store.artifact_manifest_is_complete(config, tmp_path) is False

    for item, payload in zip(config["artifact_files"], [b"one", b"two", b"three", b"four"]):
        (root / item["file"]).write_bytes(payload)

    assert store.artifact_manifest_is_complete(config, tmp_path) is True
    assert store._manifest_primary_path(config, tmp_path) == root / config["primary_artifact"]


@pytest.mark.asyncio
async def test_manifest_download_promotes_only_verified_complete_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from api.core.models.model_download.direct_file_downloader import DirectFileDownloader

    config = _manifest()
    source_files = {}
    for item, payload in zip(config["artifact_files"], [b"one", b"two", b"three", b"four"]):
        source = tmp_path / f"source-{item['file']}"
        source.write_bytes(payload)
        source_files[item["file"]] = source

    def fake_hub_download(*, filename: str, **_kwargs: object) -> str:
        return str(source_files[Path(filename).name])

    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_hub_download)
    store = ModelArtifactStore(tmp_path / "models", tmp_path / "legacy")
    store.models_dir.mkdir()
    downloader = DirectFileDownloader(
        store.models_dir,
        store,
        object(),
        object(),
    )

    progress = []

    async def update_progress(*args: object, **kwargs: object) -> None:
        progress.append((args, kwargs))

    monkeypatch.setattr(downloader, "update_progress", update_progress)
    primary = await downloader.download_artifact_manifest("Qwen", "next", config)

    assert primary.is_file()
    assert store.artifact_manifest_is_complete(config, store.models_dir) is True
    assert any(kwargs.get("status") == "completed" for _, kwargs in progress)
