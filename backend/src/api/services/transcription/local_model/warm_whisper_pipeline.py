"""
Process-wide warm cache for a single loaded Whisper inference object.

This is the one shared mechanism behind BOTH transcription stacks:

  * on-demand / file transcription (``ModelManager``), and
  * post-processing retranscription (``WhisperModelLoader``).

It keeps a single warm object resident (an HuggingFace ASR ``pipeline`` OR a
``faster_whisper.WhisperModel``), keyed by a stable cache key from
``whisper_source_resolver``. Repeated requests for the same key reuse the warm
object instead of reloading; a request for a different key evicts and replaces
it. This removes both the per-source reload and the safetensors double-load that
plagued the post-processing path.

The class-level shared state, ``threading.Lock``, and the
``schedule_unload``/``cancel_unload`` delay logic were lifted out of
``ModelManager`` so there is exactly one cache, one lock, and one unload policy.
"""
from __future__ import annotations

import asyncio
import gc
import logging
import threading
from contextlib import contextmanager
from typing import Any, Callable, Optional, Tuple

logger = logging.getLogger(__name__)


class WarmWhisperPipeline:
    """Single-slot, thread-safe cache for one loaded Whisper object."""

    # Class-level shared state - all callers share one resident object.
    _obj: Optional[Any] = None
    _key: Optional[str] = None
    _backend: Optional[str] = None
    _device: Optional[str] = None
    _loaded: bool = False

    # One condition protects cache mutation and inference ownership. The cache
    # contains one non-concurrent model, so an inference lease keeps that object
    # resident until its call returns while prioritizing live work over the next
    # background inference unit.
    _lock = threading.RLock()
    _condition = threading.Condition(_lock)
    _active_inference_leases = 0
    _waiting_live_leases = 0
    _waiting_background_leases = 0

    # Delayed-unload task management (asyncio).
    _unload_task: Optional["asyncio.Task[None]"] = None

    @classmethod
    def get_or_load(
        cls,
        cache_key: str,
        backend: str,
        device: str,
        loader: Callable[[], Any],
    ) -> Any:
        """Return the warm object for ``cache_key``, loading it if necessary.

        ``loader`` is a synchronous, heavyweight callable that constructs the
        object. It is invoked at most once per (key change) while holding the
        lock, so callers should run ``get_or_load`` inside an executor to avoid
        blocking the event loop. A cache hit cancels any pending delayed unload.

        Args:
            cache_key: Stable identity of the weights (see WhisperModelSource).
            backend: Backend tag stored alongside the object ("huggingface" or
                "faster_whisper").
            device: Device string the object was built for (diagnostics/eviction).
            loader: Zero-arg callable returning the loaded object.

        Returns:
            The loaded object (HF pipeline or faster-whisper model).
        """
        with cls._condition:
            cls._wait_for_no_active_inference_locked()
            cls._cancel_unload_locked()

            if cls._loaded and cls._key == cache_key and cls._obj is not None:
                logger.info(
                    "Warm Whisper cache hit (key=%s, backend=%s)",
                    cache_key,
                    cls._backend,
                )
                return cls._obj

            if cls._loaded:
                logger.info(
                    "Warm Whisper cache key change (%s -> %s); evicting prior object",
                    cls._key,
                    cache_key,
                )
                cls._unload_locked()

            logger.info(
                "Warm Whisper cache miss (key=%s, backend=%s); loading",
                cache_key,
                backend,
            )
            obj = loader()
            if obj is None:
                raise RuntimeError(
                    f"Whisper loader returned None for cache key {cache_key!r}"
                )

            cls._obj = obj
            cls._key = cache_key
            cls._backend = backend
            cls._device = device
            cls._loaded = True
            return obj

    @classmethod
    @contextmanager
    def acquire_inference_lease(
        cls,
        cache_key: str,
        backend: str,
        device: str,
        loader: Callable[[], Any],
        *,
        priority: str,
    ):
        """Lease one warm object for a single inference call.

        ``priority`` is either ``"live"`` for interactive transcription or
        ``"background"`` for meeting post-processing. Leases never overlap;
        once an inference call completes, waiting live work runs before the next
        background unit. Cache eviction and model swapping wait for the lease to
        release, so a caller never observes its borrowed object become ``None``.
        """
        if priority not in {"live", "background"}:
            raise ValueError(f"Unsupported Whisper inference priority: {priority!r}")

        with cls._condition:
            waiting_registered = True
            active_acquired = False
            if priority == "live":
                cls._waiting_live_leases += 1
            else:
                cls._waiting_background_leases += 1

            try:
                while (
                    cls._active_inference_leases > 0
                    or (priority == "background" and cls._waiting_live_leases > 0)
                ):
                    cls._condition.wait()

                if priority == "live":
                    cls._waiting_live_leases -= 1
                else:
                    cls._waiting_background_leases -= 1
                waiting_registered = False

                cls._active_inference_leases = 1
                active_acquired = True
                cls._cancel_unload_locked()

                if cls._loaded and cls._key == cache_key and cls._obj is not None:
                    obj = cls._obj
                else:
                    if cls._loaded:
                        cls._unload_locked()
                    obj = loader()
                    if obj is None:
                        raise RuntimeError(
                            f"Whisper loader returned None for cache key {cache_key!r}"
                        )
                    cls._obj = obj
                    cls._key = cache_key
                    cls._backend = backend
                    cls._device = device
                    cls._loaded = True
            except Exception:
                if waiting_registered and priority == "live":
                    cls._waiting_live_leases -= 1
                elif waiting_registered and priority == "background":
                    cls._waiting_background_leases -= 1
                if active_acquired:
                    cls._active_inference_leases = 0
                cls._condition.notify_all()
                raise

        try:
            yield obj
        finally:
            with cls._condition:
                cls._active_inference_leases = 0
                cls._condition.notify_all()

    @classmethod
    def has_active_inference(cls) -> bool:
        """Return whether a caller currently owns the warm inference object."""
        with cls._condition:
            return cls._active_inference_leases > 0

    @classmethod
    def wait_for_idle(cls) -> None:
        """Block the calling worker until no inference lease owns the cache."""
        with cls._condition:
            cls._wait_for_no_active_inference_locked()

    @classmethod
    def _wait_for_no_active_inference_locked(cls) -> None:
        while cls._active_inference_leases > 0:
            cls._condition.wait()

    @classmethod
    def matches(cls, cache_key: str) -> bool:
        """True if the warm object currently loaded is for ``cache_key``."""
        with cls._condition:
            return cls._loaded and cls._key == cache_key and cls._obj is not None

    @classmethod
    def is_loaded(cls) -> bool:
        with cls._condition:
            return cls._loaded and cls._obj is not None

    @classmethod
    def current(cls) -> Tuple[Optional[Any], Optional[str], Optional[str]]:
        """Return ``(object, backend, device)`` for the warm entry (or Nones)."""
        with cls._condition:
            return cls._obj, cls._backend, cls._device

    @classmethod
    def current_key(cls) -> Optional[str]:
        with cls._condition:
            return cls._key

    @classmethod
    def current_object(cls) -> Optional[Any]:
        with cls._condition:
            return cls._obj

    # -- eviction ----------------------------------------------------------

    @classmethod
    def unload(cls) -> None:
        """Evict the warm object and free memory (thread-safe)."""
        with cls._condition:
            cls._wait_for_no_active_inference_locked()
            cls._unload_locked()

    @classmethod
    def _unload_locked(cls) -> None:
        if not cls._loaded and cls._obj is None:
            return

        prior_device = cls._device
        prior_key = cls._key

        # Best-effort: move an underlying CUDA model to CPU before dropping it.
        obj = cls._obj
        try:
            model = getattr(obj, "model", None)
            if prior_device == "cuda" and model is not None and hasattr(model, "cpu"):
                model.cpu()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Warm Whisper unload: move-to-cpu failed: %s", exc)

        cls._obj = None
        cls._key = None
        cls._backend = None
        cls._device = None
        cls._loaded = False

        gc.collect()
        if prior_device == "cuda":
            try:
                import torch

                torch.cuda.empty_cache()
            except Exception:  # pragma: no cover - torch optional at runtime
                pass

        logger.info("Warm Whisper cache evicted (key=%s)", prior_key)

    # -- delayed unload scheduling ----------------------------------------

    @classmethod
    def schedule_unload(cls, delay_seconds: int) -> None:
        """Unload the warm object after ``delay_seconds`` (0 = immediate).

        Mirrors the prior ``ModelManager.schedule_unload`` behavior so existing
        callers keep working. Must be invoked from within a running event loop
        when ``delay_seconds > 0``.
        """
        if delay_seconds <= 0:
            logger.info("Warm Whisper: unloading immediately")
            cls.unload()
            with cls._lock:
                cls._unload_task = None
            return

        async def _unload_after_delay() -> None:
            try:
                logger.info("Warm Whisper: scheduling unload in %ss", delay_seconds)
                await asyncio.sleep(delay_seconds)
                if cls.is_loaded():
                    logger.info("Warm Whisper: unloading after %ss delay", delay_seconds)
                    cls.unload()
            except asyncio.CancelledError:
                logger.info("Warm Whisper: scheduled unload canceled")
                raise
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Warm Whisper: error during scheduled unload: %s", exc)

        with cls._condition:
            if cls._unload_task is not None and not cls._unload_task.done():
                cls._unload_task.cancel()
            cls._unload_task = asyncio.create_task(_unload_after_delay())

    @classmethod
    def cancel_unload(cls) -> None:
        """Cancel any pending delayed unload (thread-safe)."""
        with cls._condition:
            cls._cancel_unload_locked()

    @classmethod
    def _cancel_unload_locked(cls) -> None:
        if cls._unload_task is not None and not cls._unload_task.done():
            logger.info("Warm Whisper: canceling pending unload")
            cls._unload_task.cancel()
        cls._unload_task = None
