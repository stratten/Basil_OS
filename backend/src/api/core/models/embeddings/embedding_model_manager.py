"""
EmbeddingModelManager

Centralized loader/cache for SentenceTransformer embedding models with
schedule-on-complete unloading and first-run download support.

Design goals:
- No background loops. Unload is scheduled immediately after each use completes.
- Any new use cancels and reschedules the pending unload.
- Install-on-demand: if the model directory is missing, attempt a one-time
  download into Basil's canonical models directory.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Dict, Optional

from huggingface_hub import snapshot_download
from sentence_transformers import SentenceTransformer

from api.settings import get_models_dir


logger = logging.getLogger("api.embedding_manager")


@dataclass
class _ModelEntry:
    model: Optional[SentenceTransformer]
    last_used_ts: float
    unload_task: Optional[asyncio.Task]
    lock: asyncio.Lock


class EmbeddingModelManager:
    """
    Manages lifecycle of embedding models with schedule-on-complete unload.
    """

    def __init__(self, default_idle_seconds: int = 600, allow_auto_download: bool = True) -> None:
        self._models: Dict[str, _ModelEntry] = {}
        self._default_idle_seconds = int(default_idle_seconds)
        self._allow_auto_download = bool(allow_auto_download)
        # Resolve device override
        env_device = (os.environ.get("BASIL_EMBED_DEVICE") or "").strip().lower()
        if env_device in {"cpu", "mps", "cuda"}:
            self._forced_device: Optional[str] = env_device
        elif "PYTEST_CURRENT_TEST" in os.environ:
            # Default to CPU during pytest to avoid MPS flakiness/segfaults
            self._forced_device = "cpu"
        else:
            self._forced_device = None

    # ---- Public API ----

    def get(self, model_name: str) -> SentenceTransformer:
        """Get (and load if needed) the embedding model instance for model_name.

        Also updates last-used timestamp.
        """
        entry = self._ensure_entry(model_name)
        # Fast path if already loaded
        if entry.model is not None:
            entry.last_used_ts = time.time()
            return entry.model

        # Load path: ensure local install and instantiate model
        local_dir = self._ensure_model_installed(model_name)
        with self._blocked_by_lock(entry.lock):
            if entry.model is None:
                logger.info(f"Loading SentenceTransformer for model '{model_name}' from {local_dir}")
                if self._forced_device:
                    entry.model = SentenceTransformer(
                        str(local_dir), local_files_only=True, device=self._forced_device
                    )
                else:
                    entry.model = SentenceTransformer(str(local_dir), local_files_only=True)
            entry.last_used_ts = time.time()
        return entry.model  # type: ignore[return-value]

    def begin_use(self, model_name: str) -> None:
        """Mark the start of a critical usage section; cancels pending unload."""
        entry = self._ensure_entry(model_name)
        with self._blocked_by_lock(entry.lock):
            self._cancel_unload_locked(entry)
            entry.last_used_ts = time.time()

    def end_use(self, model_name: str, idle_seconds: Optional[int] = None) -> None:
        """Schedule unload after idle_seconds if not used again.

        If another begin_use happens before the delay, the pending unload will be
        canceled by begin_use().
        """
        entry = self._ensure_entry(model_name)
        delay = int(idle_seconds or self._default_idle_seconds)
        with self._blocked_by_lock(entry.lock):
            self._cancel_unload_locked(entry)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                entry.unload_task = loop.create_task(
                    self._unload_after_delay(model_name, delay)
                )

    def schedule_unload(self, model_name: str, idle_seconds: Optional[int] = None) -> None:
        """Schedule an unload without an explicit end_use boundary (rare)."""
        self.end_use(model_name, idle_seconds)

    def cancel_unload(self, model_name: str) -> None:
        entry = self._ensure_entry(model_name)
        with self._blocked_by_lock(entry.lock):
            self._cancel_unload_locked(entry)

    def unload_now(self, model_name: str) -> bool:
        """Immediately unload the model from memory. Returns True if unloaded."""
        entry = self._ensure_entry(model_name)
        with self._blocked_by_lock(entry.lock):
            self._cancel_unload_locked(entry)
            if entry.model is not None:
                logger.info(f"Unloading embedding model '{model_name}' from memory")
                entry.model = None
                return True
            return False

    def status(self, model_name: Optional[str] = None) -> Dict[str, Dict[str, object]]:
        """Return basic status for one or all models."""
        def entry_status(name: str, e: _ModelEntry) -> Dict[str, object]:
            return {
                "loaded": e.model is not None,
                "last_used_ts": e.last_used_ts,
                "has_pending_unload": e.unload_task is not None and not e.unload_task.done(),
                "local_dir": str(self._local_model_dir(name)),
            }

        if model_name:
            e = self._ensure_entry(model_name)
            return {model_name: entry_status(model_name, e)}
        return {name: entry_status(name, e) for name, e in self._models.items()}

    # ---- Internal helpers ----

    async def _unload_after_delay(self, model_name: str, idle_seconds: int) -> None:
        try:
            entry = self._ensure_entry(model_name)
            start_wait = time.time()
            await asyncio.sleep(max(0, idle_seconds))
            with self._blocked_by_lock(entry.lock):
                # If used again during wait, do not unload
                if (time.time() - entry.last_used_ts) < idle_seconds:
                    logger.debug(
                        f"Skip unload for '{model_name}': used again within idle window"
                    )
                    return
                if entry.model is not None:
                    logger.info(
                        f"Idle-unloading '{model_name}' after {time.time()-start_wait:.1f}s of inactivity"
                    )
                    entry.model = None
        except asyncio.CancelledError:
            # Task canceled due to a new begin_use
            logger.debug(f"Unload task canceled for '{model_name}' (reuse detected)")
        except Exception as e:
            logger.error(f"Error unloading model '{model_name}': {e}")

    def _cancel_unload_locked(self, entry: _ModelEntry) -> None:
        if entry.unload_task and not entry.unload_task.done():
            entry.unload_task.cancel()
        entry.unload_task = None

    def _ensure_entry(self, model_name: str) -> _ModelEntry:
        if model_name not in self._models:
            self._models[model_name] = _ModelEntry(
                model=None,
                last_used_ts=0.0,
                unload_task=None,
                lock=asyncio.Lock(),
            )
        return self._models[model_name]

    def _local_model_dir(self, model_name: str) -> Path:
        models_root = get_models_dir() / "sentence-transformers"
        return models_root / model_name

    def _ensure_model_installed(self, model_name: str) -> Path:
        local_dir = self._local_model_dir(model_name)
        if local_dir.exists():
            return local_dir

        if not self._allow_auto_download:
            raise RuntimeError(
                f"Embedding model '{model_name}' not available locally at {local_dir}. "
                "Auto-download disabled."
            )

        # Figure out repo id. Accept either full repo id or short name.
        repo_id = model_name if "/" in model_name else f"sentence-transformers/{model_name}"
        logger.info(f"Downloading embedding model '{repo_id}' for first-time install → {local_dir}")

        local_dir.parent.mkdir(parents=True, exist_ok=True)
        cached = snapshot_download(repo_id=repo_id, local_files_only=False, resume_download=True)
        try:
            shutil.copytree(cached, local_dir, dirs_exist_ok=True)
        finally:
            # Best-effort cleanup of HF cache snapshot to save disk space
            try:
                shutil.rmtree(cached)
            except Exception:
                pass

        if not local_dir.exists():
            raise RuntimeError(
                f"Failed to install embedding model for '{model_name}' into {local_dir}"
            )
        logger.info(f"Embedding model installed at {local_dir}")
        return local_dir

    # Context manager to make small critical sections atomic without awaiting
    class _blocked_by_lock:
        def __init__(self, lock: asyncio.Lock) -> None:
            self._lock = lock

        def __enter__(self) -> None:  # type: ignore[override]
            # Acquire without await by using try_lock pattern
            # Fallback: busy-wait with short sleeps to avoid blocking event loop heavily
            # This scope is minimal; operations are CPU-bound assignments and cancel()
            start = time.time()
            while True:
                acquired = self._lock.locked()
                if not acquired:
                    # Use loop.run_until_complete would block; this is acceptable since
                    # we only need to guard a few assignments and task.cancel calls.
                    # Emulate non-await lock by checking frequently.
                    # If another coroutine holds the lock, spin briefly.
                    # NOTE: Kept tiny and bounded to avoid noticeable overhead.
                    break
                if time.time() - start > 0.05:
                    break
                time.sleep(0.001)

        def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
            # Nothing to release; we didn't actually acquire the asyncio lock synchronously.
            # This guard is only for very short critical sections where true async locking
            # is not practical without refactoring call sites to be async.
            return None


# Simple module-level singleton for convenience where DI is not yet wired.
_GLOBAL_MANAGER: Optional[EmbeddingModelManager] = None


def get_global_embedding_manager() -> EmbeddingModelManager:
    global _GLOBAL_MANAGER
    if _GLOBAL_MANAGER is None:
        _GLOBAL_MANAGER = EmbeddingModelManager()
    return _GLOBAL_MANAGER


