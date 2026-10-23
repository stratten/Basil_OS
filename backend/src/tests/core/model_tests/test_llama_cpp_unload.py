"""Unloading a llama.cpp model must really release the native context."""

import threading
import time

import pytest

from api.core.models.base_model import ModelState
from api.core.models.reasoning import llama_cpp_model
from api.core.models.reasoning.llama_cpp_model import (
    LlamaCppModel,
    evict_llama_cpp_contexts_under,
)


class FakeNativeLlama:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


@pytest.fixture
def isolated_cache(monkeypatch):
    cache: dict = {}
    monkeypatch.setattr(llama_cpp_model, "_MODEL_CACHE", cache)
    monkeypatch.setattr(llama_cpp_model, "_WRAPPERS_BY_CACHE_KEY", {})
    return cache


async def wrapper_for(path, cache, llm) -> LlamaCppModel:
    cache[str(path.resolve())] = llm
    model = LlamaCppModel.__new__(LlamaCppModel)
    model.state = ModelState.UNLOADED
    model.model_path = path
    await model.load()
    return model


@pytest.mark.asyncio
async def test_unload_closes_the_native_context_and_empties_the_cache(tmp_path, isolated_cache):
    llm = FakeNativeLlama()
    model = await wrapper_for(tmp_path / "a.gguf", isolated_cache, llm)
    assert model.is_loaded

    await model.unload()

    assert llm.closed == 1
    assert isolated_cache == {}
    assert model.llm is None
    assert model.state == ModelState.UNLOADED
    assert not model.is_loaded


@pytest.mark.asyncio
async def test_unload_marks_every_wrapper_sharing_the_context(tmp_path, isolated_cache):
    llm = FakeNativeLlama()
    path = tmp_path / "shared.gguf"
    first = await wrapper_for(path, isolated_cache, llm)
    second = LlamaCppModel.__new__(LlamaCppModel)
    second.state = ModelState.UNLOADED
    second.model_path = path
    await second.load()
    assert second.llm is first.llm

    await first.unload()

    assert llm.closed == 1  # closed once, not once per wrapper
    assert second.llm is None
    assert second.state == ModelState.UNLOADED


@pytest.mark.asyncio
async def test_unload_twice_is_harmless(tmp_path, isolated_cache):
    llm = FakeNativeLlama()
    model = await wrapper_for(tmp_path / "a.gguf", isolated_cache, llm)
    await model.unload()
    await model.unload()
    assert llm.closed == 1


@pytest.mark.asyncio
async def test_a_failing_close_does_not_break_unload(tmp_path, isolated_cache):
    class Broken(FakeNativeLlama):
        def close(self) -> None:
            raise RuntimeError("native close failed")

    model = await wrapper_for(tmp_path / "a.gguf", isolated_cache, Broken())
    await model.unload()
    assert isolated_cache == {}
    assert model.state == ModelState.UNLOADED


@pytest.mark.asyncio
async def test_evict_under_a_directory_closes_only_contexts_inside_it(tmp_path, isolated_cache):
    inside = FakeNativeLlama()
    outside = FakeNativeLlama()
    model_dir = tmp_path / "model-dir"
    model_dir.mkdir()
    keep = tmp_path / "other.gguf"
    drop = model_dir / "drop.gguf"
    kept_wrapper = await wrapper_for(keep, isolated_cache, outside)
    dropped_wrapper = await wrapper_for(drop, isolated_cache, inside)

    evicted = evict_llama_cpp_contexts_under(model_dir)

    assert evicted == [str(drop.resolve())]
    assert inside.closed == 1 and outside.closed == 0
    assert dropped_wrapper.llm is None
    assert kept_wrapper.llm is outside


def test_unload_waits_for_a_generation_in_progress(tmp_path, isolated_cache):
    """The context is never closed while a call holds the per-file execution lock."""
    llm = FakeNativeLlama()
    key = str((tmp_path / "busy.gguf").resolve())
    isolated_cache[key] = llm
    lock = llama_cpp_model._execution_lock_for_key(key)

    finished = threading.Event()

    def evict() -> None:
        llama_cpp_model._evict_native_context(key)
        finished.set()

    with lock:
        thread = threading.Thread(target=evict)
        thread.start()
        time.sleep(0.2)
        assert not finished.is_set()
        assert llm.closed == 0

    thread.join(timeout=5)
    assert finished.is_set()
    assert llm.closed == 1
