"""A local reasoning model that runs an MLX checkpoint folder on Apple Silicon.

It subclasses ``LlamaCppModel`` and replaces only what is specific to the engine: loading, unloading, the native-context cache, and metadata. Generation, sampling policy, telemetry, the execution lock, and reasoning-tag handling are inherited, because ``MlxChatEngine`` answers like ``llama_cpp.Llama``.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import threading
import weakref
from pathlib import Path
from typing import Any, Dict, List

from ...logging.api_logger import api_logger
from ...runtime.mlx_support import mlx_runtime_available
from ..base_model import ModelMetadata, ModelState
from ..model_types import ModelCapability
from .llama_cpp_model import LlamaCppModel, LlamaCppTokenizerWrapper, _execution_lock_for_key
from .mlx_engine import MlxChatEngine

logger = logging.getLogger(__name__)

# One engine per resolved checkpoint folder, shared by every wrapper on it, exactly like the llama.cpp cache.
_MLX_ENGINE_CACHE: Dict[str, Any] = {}
_MLX_WRAPPERS_BY_KEY: Dict[str, "weakref.WeakSet[Any]"] = {}
_MLX_CACHE_GUARD = threading.Lock()


def _build_engine(model_path: Path, context_window: int) -> Any:
    """Create the engine for one checkpoint folder. Tests replace this function."""
    return MlxChatEngine(model_path, context_window)


def _register_mlx_wrapper(cache_key: str, wrapper: Any) -> None:
    with _MLX_CACHE_GUARD:
        _MLX_WRAPPERS_BY_KEY.setdefault(cache_key, weakref.WeakSet()).add(wrapper)


def _evict_mlx_engine(cache_key: str) -> bool:
    """Close one cached engine and mark every wrapper on it unloaded.

    Waits for any generation in progress on the same folder, because generations hold the same lock. Returns True if an engine was cached.
    """
    with _execution_lock_for_key(cache_key):
        with _MLX_CACHE_GUARD:
            engine = _MLX_ENGINE_CACHE.pop(cache_key, None)
            wrappers = list(_MLX_WRAPPERS_BY_KEY.pop(cache_key, ()))
        for wrapper in wrappers:
            wrapper._mark_unloaded()
        if engine is None:
            return False
        close = getattr(engine, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.warning("Failed to close MLX engine: %s", cache_key, exc_info=True)
        return True


def evict_mlx_contexts_under(root: Path) -> List[str]:
    """Close every cached MLX engine whose folder is at or under ``root``. Used before a model's files are deleted."""
    resolved_root = Path(root).expanduser().resolve()
    with _MLX_CACHE_GUARD:
        candidates = list(_MLX_ENGINE_CACHE.keys())
    evicted: List[str] = []
    for cache_key in candidates:
        key_path = Path(cache_key)
        if key_path == resolved_root or resolved_root in key_path.parents:
            if _evict_mlx_engine(cache_key):
                evicted.append(cache_key)
    if evicted:
        gc.collect()
    return evicted


def shutdown_cached_mlx_models() -> None:
    """Close every cached MLX engine before interpreter teardown."""
    with _MLX_CACHE_GUARD:
        cache_keys = list(_MLX_ENGINE_CACHE.keys())
    for cache_key in cache_keys:
        _evict_mlx_engine(cache_key)


class MlxModel(LlamaCppModel):
    """A registry-backed local reasoning model served by MLX instead of llama.cpp."""

    def _adopt_engine(self, engine: Any, cache_key: str) -> None:
        self.llm = engine
        self.tokenizer = LlamaCppTokenizerWrapper(engine)
        _register_mlx_wrapper(cache_key, self)
        self.n_ctx = engine.n_ctx()
        self.max_context_length = self.n_ctx
        self.state = ModelState.READY

    async def load(self) -> None:
        if self.state == ModelState.READY:
            return
        if not mlx_runtime_available():
            self.state = ModelState.ERROR
            raise RuntimeError("MLX models need an Apple Silicon Mac with the mlx and mlx-lm packages installed.")
        if not Path(self.model_path).is_dir():
            self.state = ModelState.ERROR
            raise RuntimeError(f"MLX model folder not found: {self.model_path}")

        cache_key = str(Path(self.model_path).resolve())
        with self.native_execution_lock:
            cached = _MLX_ENGINE_CACHE.get(cache_key)
        if cached is not None:
            logger.info("Using cached MLX engine for %s", self.model_path)
            self._adopt_engine(cached, cache_key)
            return

        configured_context = (getattr(self, "_registry_config", None) or {}).get("context_window")
        context_window = int(configured_context) if configured_context else self.DEFAULT_CONTEXT_WINDOW
        logger.info("Loading MLX model from %s with a %s token context", self.model_path, context_window)
        self.state = ModelState.LOADING

        def load_or_reuse_engine() -> Any:
            with self.native_execution_lock:
                existing = _MLX_ENGINE_CACHE.get(cache_key)
                if existing is not None:
                    return existing
                engine = _build_engine(Path(self.model_path), context_window)
                engine.load()
                with _MLX_CACHE_GUARD:
                    _MLX_ENGINE_CACHE[cache_key] = engine
                return engine

        try:
            engine = await asyncio.to_thread(load_or_reuse_engine)
        except Exception as exc:
            api_logger.error(f"Failed to load MLX model: {exc}")
            self.state = ModelState.ERROR
            raise RuntimeError(f"Failed to load MLX model: {exc}") from exc
        self._adopt_engine(engine, cache_key)
        logger.info("Loaded MLX model %s", self.model_path.name)

    async def unload(self) -> None:
        cache_key = str(Path(self.model_path).resolve())
        await asyncio.to_thread(_evict_mlx_engine, cache_key)
        self._mark_unloaded()
        gc.collect()
        logger.info("Unloaded MLX model %s", self.model_path.name)

    def get_metadata(self) -> ModelMetadata:
        context_length = getattr(self, "n_ctx", self.DEFAULT_CONTEXT_WINDOW)
        return ModelMetadata(
            name=self.model_path.name if self.model_path else "MLX Model",
            description=f"MLX model on Apple Silicon with {context_length} token context",
            version="1.0",
            source="mlx",
            capabilities={ModelCapability.REASONING},
            parameters={"n_ctx": context_length, "quantization": "MLX", "format": "MLX"},
            requirements={"mlx-lm": ">=0.32.2"},
            memory_requirements="16GB",
            supports_gpu=True,
            context_window=context_length,
        )
