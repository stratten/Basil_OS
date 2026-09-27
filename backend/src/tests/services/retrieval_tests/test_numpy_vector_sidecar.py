"""Tests for atomic, exact NumPy retrieval-vector generations."""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from api.services.retrieval import indexer, numpy_vector_sidecar, service
from api.services.retrieval.numpy_vector_sidecar import NumpyVectorSidecar


def _sidecar(tmp_path) -> NumpyVectorSidecar:
    return NumpyVectorSidecar(str(tmp_path / "knowledge.db"), "all-MiniLM-L6-v2")


def _vectors() -> np.ndarray:
    return np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)


def test_publish_and_load_memory_mapped_float32_generation(tmp_path):
    sidecar = _sidecar(tmp_path)
    sidecar.publish("generation-a", _vectors(), 2, 2)

    loaded = sidecar.load("generation-a", 2, 2)

    assert isinstance(loaded, np.memmap)
    assert loaded.dtype == np.float32
    assert loaded.flags.writeable is False
    assert np.array_equal(loaded, _vectors())
    manifest = json.loads(sidecar.manifest_path.read_text())
    assert manifest["format"] == NumpyVectorSidecar.FORMAT
    assert manifest["vector_file"] == "generation-a.npy"


def test_publish_rejects_wrong_dtype_or_shape(tmp_path):
    sidecar = _sidecar(tmp_path)

    with pytest.raises(ValueError, match="float32"):
        sidecar.publish("generation-a", _vectors().astype(np.float64), 2, 2)
    with pytest.raises(ValueError, match="shape"):
        sidecar.publish("generation-a", _vectors(), 3, 2)


def test_load_rejects_mismatched_generation_metadata(tmp_path):
    sidecar = _sidecar(tmp_path)
    sidecar.publish("generation-a", _vectors(), 2, 2)

    assert sidecar.load("generation-b", 2, 2) is None
    assert sidecar.load("generation-a", 3, 2) is None
    assert sidecar.load("generation-a", 2, 3) is None


def test_snapshot_and_restore_recovers_previous_generation(tmp_path):
    sidecar = _sidecar(tmp_path)
    sidecar.publish("generation-a", _vectors(), 2, 2)
    previous_manifest = sidecar.snapshot_current_manifest()
    sidecar.publish("generation-b", _vectors() * 2, 2, 2)

    sidecar.restore_current_manifest(previous_manifest)

    restored = sidecar.load("generation-a", 2, 2)
    assert restored is not None
    assert np.array_equal(restored, _vectors())
    assert sidecar.load("generation-b", 2, 2) is None


def test_empty_generation_removes_only_current_numpy_vector(tmp_path):
    sidecar = _sidecar(tmp_path)
    sidecar.publish("generation-a", _vectors(), 2, 2)
    old_vector = sidecar.root / "old.npy"
    old_vector.write_bytes(b"old generation")

    sidecar.remove_current_generation()

    assert not sidecar.manifest_path.exists()
    assert not (sidecar.root / "generation-a.npy").exists()
    assert old_vector.exists()


def test_legacy_faiss_manifest_is_stale_then_cleaned_after_numpy_publish(tmp_path):
    sidecar = _sidecar(tmp_path)
    sidecar.root.mkdir(parents=True)
    legacy_index = sidecar.root / "legacy.faiss"
    legacy_index.write_bytes(b"legacy")
    sidecar.manifest_path.write_text(
        json.dumps(
            {
                "generation_id": "legacy",
                "model": sidecar.model,
                "dimension": 2,
                "document_count": 2,
                "index_file": legacy_index.name,
            }
        )
    )

    assert sidecar.load("legacy", 2, 2) is None
    sidecar.publish("generation-a", _vectors(), 2, 2)
    sidecar.remove_legacy_faiss_generations()

    assert sidecar.load("generation-a", 2, 2) is not None
    assert not legacy_index.exists()


def test_retrieval_runtime_modules_do_not_import_faiss():
    runtime_sources = (
        inspect.getsource(indexer),
        inspect.getsource(service),
        inspect.getsource(numpy_vector_sidecar),
    )

    assert all("import faiss" not in source for source in runtime_sources)
    assert all("from faiss" not in source for source in runtime_sources)


def test_local_embedding_then_numpy_similarity_stays_alive():
    model_root = (
        Path.home()
        / ".basil"
        / "models"
        / "sentence-transformers"
        / "all-MiniLM-L6-v2"
    )
    if not (model_root / "config.json").is_file():
        pytest.skip("The packaged local all-MiniLM-L6-v2 model is not installed.")

    source_root = Path(__file__).parents[3]
    script = """
import asyncio
import numpy as np

from api.core.models.embeddings.embedding_model_manager import (
    get_global_embedding_manager,
)

async def main():
    manager = get_global_embedding_manager()
    manager.begin_use("all-MiniLM-L6-v2")
    try:
        query = manager.get("all-MiniLM-L6-v2").encode(
            ["meeting notes"],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        matrix = np.zeros((2, query.shape[1]), dtype=np.float32)
        matrix[0] = query[0]
        scores = matrix @ query[0]
        assert int(np.argmax(scores)) == 0
    finally:
        manager.end_use("all-MiniLM-L6-v2")

asyncio.run(main())
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(source_root)
    environment["BASIL_EMBED_DEVICE"] = "cpu"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=source_root.parent,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
