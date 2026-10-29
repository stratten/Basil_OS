"""Concurrent callers of EmbeddingModelManager.get must share one model load.

Two threads building SentenceTransformer at once fail with "Cannot copy out of meta tensor", which surfaced as a lost meeting-investigator record search.
"""

import threading
import time
from pathlib import Path

import pytest

from api.core.models.embeddings import embedding_model_manager as manager_module
from api.core.models.embeddings.embedding_model_manager import EmbeddingModelManager


class _SlowFakeModel:
    constructions = 0
    active = 0
    max_active = 0
    guard = threading.Lock()

    def __init__(self, *args, **kwargs) -> None:
        cls = type(self)
        with cls.guard:
            cls.constructions += 1
            cls.active += 1
            cls.max_active = max(cls.max_active, cls.active)
        time.sleep(0.15)
        with cls.guard:
            cls.active -= 1


@pytest.fixture
def fake_model(monkeypatch, tmp_path):
    _SlowFakeModel.constructions = 0
    _SlowFakeModel.active = 0
    _SlowFakeModel.max_active = 0
    monkeypatch.setattr(manager_module, "SentenceTransformer", _SlowFakeModel)
    monkeypatch.setattr(EmbeddingModelManager, "_ensure_model_installed", lambda self, name: Path(tmp_path))
    return _SlowFakeModel


def _run_threads(manager: EmbeddingModelManager, count: int):
    results = []
    errors = []
    barrier = threading.Barrier(count)

    def worker() -> None:
        try:
            barrier.wait()
            results.append(manager.get("fake-model"))
        except Exception as error:  # pragma: no cover - failure path is asserted below
            errors.append(error)

    threads = [threading.Thread(target=worker) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    return results, errors


def test_concurrent_get_loads_the_model_once(fake_model) -> None:
    manager = EmbeddingModelManager(allow_auto_download=False)

    results, errors = _run_threads(manager, 6)

    assert errors == []
    assert fake_model.constructions == 1
    assert fake_model.max_active == 1
    assert len(results) == 6
    assert all(model is results[0] for model in results)


def test_get_after_unload_loads_again_once(fake_model) -> None:
    manager = EmbeddingModelManager(allow_auto_download=False)
    first = manager.get("fake-model")
    assert manager.unload_now("fake-model") is True

    results, errors = _run_threads(manager, 4)

    assert errors == []
    assert fake_model.constructions == 2
    assert all(model is results[0] for model in results)
    assert results[0] is not first


def test_concurrent_first_use_creates_a_single_entry(fake_model) -> None:
    manager = EmbeddingModelManager(allow_auto_download=False)

    entries = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        entries.append(manager._ensure_entry("fake-model"))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(entries) == 8
    assert all(entry is entries[0] for entry in entries)


def test_failed_load_does_not_wedge_later_callers(monkeypatch, tmp_path) -> None:
    attempts = {"count": 0}

    class _FlakyModel:
        def __init__(self, *args, **kwargs) -> None:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise NotImplementedError("Cannot copy out of meta tensor")

    monkeypatch.setattr(manager_module, "SentenceTransformer", _FlakyModel)
    monkeypatch.setattr(EmbeddingModelManager, "_ensure_model_installed", lambda self, name: Path(tmp_path))
    manager = EmbeddingModelManager(allow_auto_download=False)

    with pytest.raises(NotImplementedError):
        manager.get("fake-model")

    assert isinstance(manager.get("fake-model"), _FlakyModel)
    assert attempts["count"] == 2
