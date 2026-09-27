from __future__ import annotations

from pathlib import Path

from api.services.maintenance.legacy_memvid_cleanup import cleanup_legacy_memvid_data
from api.services.maintenance.model_artifact_pruner import (
    prune_redundant_embedding_artifacts,
)
from api.settings import get_settings


def test_embedding_pruner_removes_only_known_alternate_formats(tmp_path: Path) -> None:
    model_root = tmp_path / "sentence-transformers" / "all-MiniLM-L6-v2"
    pooling = model_root / "1_Pooling"
    pooling.mkdir(parents=True)
    retained = (
        "model.safetensors",
        "config.json",
        "config_sentence_transformers.json",
        "modules.json",
        "sentence_bert_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "vocab.txt",
        "future-runtime-file.bin",
    )
    for name in retained:
        (model_root / name).write_bytes(b"retain")
    for name in ("tf_model.h5", "pytorch_model.bin", "rust_model.ot"):
        (model_root / name).write_bytes(b"remove")
    for name in ("onnx", "openvino"):
        directory = model_root / name
        directory.mkdir()
        (directory / "weights.bin").write_bytes(b"remove")

    report = prune_redundant_embedding_artifacts(tmp_path)

    assert report["files_removed"] == 5
    assert report["bytes_removed"] == len(b"remove") * 5
    for name in retained:
        assert (model_root / name).exists()
    assert pooling.exists()
    for name in ("tf_model.h5", "pytorch_model.bin", "rust_model.ot", "onnx", "openvino"):
        assert not (model_root / name).exists()
    assert prune_redundant_embedding_artifacts(tmp_path)["files_removed"] == 0


def test_legacy_memvid_cleanup_dry_runs_then_preserves_siblings(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "data"
    target = data_root / "memvid"
    target.mkdir(parents=True)
    (target / "basil_activities.mp4").write_bytes(b"legacy")
    (data_root / "knowledge_base.db").write_bytes(b"sqlite")
    (data_root / "retrieval").mkdir()
    (data_root / "retrieval" / "index.bin").write_bytes(b"index")
    models = tmp_path / "models"
    models.mkdir()
    (models / "preserve.gguf").write_bytes(b"model")
    monkeypatch.setenv("BASIL_DATA_DIR", str(data_root))
    get_settings.cache_clear()
    try:
        dry_run = cleanup_legacy_memvid_data()
        assert dry_run["deleted"] is False
        assert dry_run["files_removed"] == 1
        assert target.exists()

        deleted = cleanup_legacy_memvid_data(delete=True)
        assert deleted["deleted"] is True
        assert not target.exists()
        assert (data_root / "knowledge_base.db").exists()
        assert (data_root / "retrieval" / "index.bin").exists()
        assert (models / "preserve.gguf").exists()
    finally:
        get_settings.cache_clear()
