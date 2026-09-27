"""
Model lifecycle management for HuggingFace transcription models.

``ModelManager`` is now a thin facade over the shared ``WarmWhisperPipeline``
cache and the ``whisper_source_resolver``. It owns construction of the
HuggingFace ASR pipeline (the one place that builds it) and exposes it through
the same public surface existing callers rely on (``shared_pipe``,
``shared_model``, ``shared_processor``, ``shared_device``, ``is_model_loaded``,
``load_model``, ``unload_model``, ``schedule_unload``, ``cancel_unload``).

The post-processing retranscription path obtains the very same warm pipeline via
``get_warm_pipeline``, so on-demand transcription and retranscription share one
resident model instead of each loading their own.
"""

from contextlib import contextmanager
from typing import Any, Iterator, Optional, Tuple
import torch
import threading
import logging

from ....core.logging.api_logger import setup_api_logger
from ....core.config.api_settings import settings
from .warm_whisper_pipeline import WarmWhisperPipeline
from .whisper_source_resolver import resolve_whisper_source, WhisperModelSource

logger = setup_api_logger(
    __name__,
    log_file=settings.STORAGE_DIR / "logs" / "api.log" if not settings.DEBUG else None,
    level=logging.DEBUG if settings.DEBUG else logging.INFO
)

# Backend tag stored in the warm cache for HuggingFace pipelines.
HF_BACKEND = "huggingface"

# Default model used when neither an explicit id nor a stored preference is
# available. Resolved through the registry like any other display name.
_DEFAULT_MODEL_DISPLAY_NAME = "Whisper Base"


class ModelManager:
    """
    Manages the lifecycle of HuggingFace transcription models.

    All resident-model state lives in the process-wide ``WarmWhisperPipeline``;
    this class is a per-service facade that resolves names, builds the HF
    pipeline when needed, and exposes the warm object via the legacy properties.
    """

    # Lightweight instance accounting retained for diagnostics/back-compat.
    _instance_lock = threading.Lock()
    _reference_count = 0

    def __init__(self):
        """Initialize the model manager and detect available device."""
        self.device = (
            "mps" if torch.backends.mps.is_available()
            else "cuda" if torch.cuda.is_available()
            else "cpu"
        )
        with ModelManager._instance_lock:
            ModelManager._reference_count += 1
            logger.debug(
                "ModelManager instance created. Active instances: %s",
                ModelManager._reference_count,
            )

    # -- resolution --------------------------------------------------------

    def _resolve_requested_name(self, model_id: Optional[str]) -> str:
        """Resolve the requested model name from arg, preferences, or default."""
        selected = model_id.strip() if model_id and model_id.strip() else None
        if selected:
            return selected

        try:
            from ....core.models.preferences import Preferences

            preferences = Preferences.load()
            preferred = preferences.models.transcription_model
            if preferred and preferred.strip():
                return preferred.strip()
        except Exception as exc:
            logger.warning(
                "Could not load transcription preference, using default '%s': %s",
                _DEFAULT_MODEL_DISPLAY_NAME,
                exc,
            )

        return _DEFAULT_MODEL_DISPLAY_NAME

    # -- HF pipeline construction (the single builder) ---------------------

    @staticmethod
    def _build_hf_pipeline(source: WhisperModelSource, device: str) -> Any:
        """Construct the HuggingFace ASR pipeline for ``source`` on ``device``.

        Prefers the local ``~/.basil/models`` directory; falls back to the
        HuggingFace repo id (allowing download) only when no local copy exists.
        The ``AutoProcessor`` is attached to the pipeline as ``_basil_processor``
        so the facade can expose it without a second resident reference.
        """
        from transformers import (
            AutoModelForSpeechSeq2Seq,
            AutoProcessor,
            pipeline as hf_pipeline,
        )

        if source.exists_locally:
            model_ref = str(source.local_dir)
            local_only = True
        elif source.repo_id:
            model_ref = source.repo_id
            local_only = False
        else:
            raise RuntimeError(
                f"No local directory or HuggingFace repo for model "
                f"'{source.display_name}' (looked in {source.local_dir})."
            )

        logger.info(
            "Loading HF Whisper '%s' from %s (local_only=%s, device=%s)",
            source.display_name,
            model_ref,
            local_only,
            device,
        )

        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            model_ref,
            torch_dtype=torch.float32,
            low_cpu_mem_usage=True,
            use_safetensors=True,
            local_files_only=local_only,
        ).to(device)

        processor = AutoProcessor.from_pretrained(
            model_ref,
            local_files_only=local_only,
        )

        pipe = hf_pipeline(
            "automatic-speech-recognition",
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            device=device,
        )
        # Attach the processor so ModelManager.shared_processor can expose it
        # without holding a separate strong reference across unloads.
        pipe._basil_processor = processor

        logger.info(
            "Loaded HF Whisper '%s' (arch=%s, vocab=%s)",
            source.display_name,
            model.config.model_type,
            model.config.vocab_size,
        )
        return pipe

    def get_warm_pipeline(
        self, model_id: Optional[str] = None
    ) -> Tuple[Any, str, str]:
        """Return ``(pipe, device, cache_key)`` for the requested model.

        Loads and caches via the shared warm cache when needed; a cache hit for
        the same model reuses the resident pipeline. This is the entry point the
        post-processing retranscription path uses too.
        """
        name = self._resolve_requested_name(model_id)
        source = resolve_whisper_source(name)

        # The HuggingFace service can only load a local-dir or HF-repo whisper
        # model. A cloud-only selection (e.g. "Whisper (OpenAI API)", no repo) or
        # any entry with neither a local copy nor a repo id is not loadable here;
        # fall back to the default base model exactly as the prior loader did
        # (it defaulted to "openai/whisper-base"). Cloud transcription is routed
        # to its own service upstream, so this only guards stray/legacy calls.
        if not source.exists_locally and not source.repo_id:
            logger.warning(
                "Model '%s' is not a loadable local/HF whisper model; "
                "falling back to '%s'",
                name,
                _DEFAULT_MODEL_DISPLAY_NAME,
            )
            source = resolve_whisper_source(_DEFAULT_MODEL_DISPLAY_NAME)

        cache_key = source.cache_key
        device = self.device

        # New usage cancels any scheduled unload (both the websocket-driven one
        # and the warm cache's own delayed unload).
        self._cancel_external_unload()

        def loader() -> Any:
            return self._build_hf_pipeline(source, device)

        pipe = WarmWhisperPipeline.get_or_load(cache_key, HF_BACKEND, device, loader)
        return pipe, device, cache_key

    @contextmanager
    def acquire_warm_pipeline(
        self,
        model_id: Optional[str] = None,
        *,
        priority: str,
    ) -> Iterator[Any]:
        """Borrow the requested HF pipeline for one inference operation."""
        name = self._resolve_requested_name(model_id)
        source = resolve_whisper_source(name)
        if not source.exists_locally and not source.repo_id:
            logger.warning(
                "Model '%s' is not a loadable local/HF whisper model; "
                "falling back to '%s'",
                name,
                _DEFAULT_MODEL_DISPLAY_NAME,
            )
            source = resolve_whisper_source(_DEFAULT_MODEL_DISPLAY_NAME)

        self._cancel_external_unload()
        with WarmWhisperPipeline.acquire_inference_lease(
            source.cache_key,
            HF_BACKEND,
            self.device,
            lambda: self._build_hf_pipeline(source, self.device),
            priority=priority,
        ) as pipe:
            yield pipe

    # -- public lifecycle API (preserved) ----------------------------------

    def load_model(self, model_id: Optional[str] = None) -> None:
        """Load the transcription model into the shared warm cache."""
        try:
            self.get_warm_pipeline(model_id)
        except Exception as exc:
            logger.error("Error loading shared Whisper model: %s", exc, exc_info=True)
            raise

    def unload_model(self) -> None:
        """Unload the resident transcription model to free memory."""
        WarmWhisperPipeline.unload()

    def is_model_loaded(self) -> bool:
        """True if a HuggingFace ASR pipeline is currently resident."""
        _, backend, _ = WarmWhisperPipeline.current()
        return WarmWhisperPipeline.is_loaded() and backend == HF_BACKEND

    @classmethod
    def schedule_unload(cls, delay_seconds: int) -> None:
        """Schedule resident-model unload after a delay. Callable from any service."""
        WarmWhisperPipeline.schedule_unload(delay_seconds)

    @classmethod
    def cancel_unload(cls) -> None:
        """Cancel any scheduled unload. Callable from any service."""
        WarmWhisperPipeline.cancel_unload()

    @staticmethod
    def _cancel_external_unload() -> None:
        """Best-effort cancel of the websocket-driven unload + warm cache unload."""
        WarmWhisperPipeline.cancel_unload()
        try:
            from api.services.transcription.local_model.model_unload_state import (
                cancel_scheduled_model_unload,
            )

            cancel_scheduled_model_unload()
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("Could not cancel websocket unload task: %s", exc)

    # -- legacy shared-state accessors (derive from the warm pipeline) ------

    @property
    def shared_pipe(self):
        """The resident HuggingFace ASR pipeline, or None if not HF/loaded."""
        obj, backend, _ = WarmWhisperPipeline.current()
        return obj if backend == HF_BACKEND else None

    @property
    def shared_model(self):
        """The resident model (``pipe.model``), or None."""
        pipe = self.shared_pipe
        return getattr(pipe, "model", None) if pipe is not None else None

    @property
    def shared_processor(self):
        """The resident ``AutoProcessor`` attached to the pipeline, or None."""
        pipe = self.shared_pipe
        return getattr(pipe, "_basil_processor", None) if pipe is not None else None

    @property
    def shared_device(self):
        """Device string the resident HF pipeline was built for, or None."""
        _, backend, device = WarmWhisperPipeline.current()
        return device if backend == HF_BACKEND else None

    def __del__(self):
        """Decrement the diagnostic instance counter on destruction."""
        try:
            with ModelManager._instance_lock:
                if ModelManager._reference_count > 0:
                    ModelManager._reference_count -= 1
        except Exception:
            pass
