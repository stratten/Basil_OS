"""Parakeet ONNX session manager.

Mirrors the shared-state pattern used by
:class:`api.services.transcription.local_model.model_lifecycle.ModelManager` for
Whisper, but for the two ONNX sessions (encoder + decoder_joint) and the
SentencePiece-style vocab that Parakeet needs. A single shared instance
backs both the batch transcription service and the live ASR backend so
RAM is never duplicated.

Why a separate manager class instead of reusing ``ModelManager``?
``ModelManager`` is hard-coded to PyTorch + HuggingFace ``pipeline``
state (``_shared_pipe``, ``_shared_processor``) which has nothing to do
with the ONNX sessions and vocab Parakeet needs. Sharing the surface
(``load_model`` / ``unload_model`` / ``schedule_unload`` /
``cancel_unload`` / ``is_model_loaded``) keeps the dispatch and lifetime
logic in :func:`schedule_unload` interchangeable with Whisper's so the
existing WebSocket idle-unload flow in
``api.routes.websocket_routes.transcription`` works without changes.

ONNX I/O contract (introspected at session-load time, not hard-coded):

* Encoder ``encoder-model.onnx`` -- maps a log-mel spectrogram and its
  valid-frame count to encoder hidden states. Typical NeMo signature is
  ``audio_signal: [B, n_mels, T]`` + ``length: [B]`` ->
  ``outputs: [B, T_enc, hidden]`` + ``encoded_lengths: [B]``. We do
  ``session.get_inputs()`` / ``session.get_outputs()`` at load time and
  cache the names so re-exports with renamed I/O still work.
* Decoder/joint ``decoder_joint-model.onnx`` -- the combined RNNT
  prediction network + joint network for TDT. We surface only the raw
  session here; the decoding loop lives in
  :mod:`parakeet_decoder` and reads ``decoder_session.get_inputs()``
  itself so input ordering changes between exports do not break us.
"""

from __future__ import annotations

import gc
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .....core.config.api_settings import settings
from .....core.logging.api_logger import setup_api_logger
from .....core.runtime.hardware_capability_service import (
    HardwareCapabilityProfile,
    HardwareCapabilityService,
)
from .....settings import get_models_dir

logger = setup_api_logger(
    __name__,
    log_file=settings.STORAGE_DIR / "logs" / "api.log" if not settings.DEBUG else None,
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
)


def _detect_execution_providers(
    hardware_profile: Optional[HardwareCapabilityProfile] = None,
) -> List[str]:
    """Return an ordered list of ONNX Runtime execution providers to try.

    We want the fastest available accelerator first and CPU as a hard
    fallback. The actual session constructor will silently drop any
    provider that is not registered in this build of onnxruntime, so
    listing extras (e.g. CUDA on a Mac) is safe.

    Order rationale:
      * CoreML on Apple Silicon -- onnxruntime ships the CoreML EP in
        the macOS wheel and it gives 2-3x speedups for FastConformer
        encoders compared to the CPU EP.
      * CUDA next, for Linux/desktop boxes with an NVIDIA GPU.
      * CPU last as a guaranteed-available fallback.
    """
    profile = hardware_profile or HardwareCapabilityService().get_profile()
    candidates: List[str] = []
    if profile.prefer_coreml_onnx:
        candidates.append("CoreMLExecutionProvider")
    if profile.cuda_available:
        candidates.append("CUDAExecutionProvider")

    candidates.append("CPUExecutionProvider")
    return candidates


def _resolve_bundle_dir(on_disk_name: str) -> Path:
    """Find the on-disk Parakeet bundle directory.

    Prefer Basil's canonical model directory while preserving a fallback
    for older data-derived model cache locations.
    """
    canonical_path = get_models_dir() / on_disk_name
    if canonical_path.exists():
        return canonical_path
    data_cache_path = Path(settings.MODEL_CACHE_DIR or settings.STORAGE_DIR / "models") / on_disk_name
    if data_cache_path.exists():
        return data_cache_path
    # Return the canonical path so the caller's "not found" error message
    # points at where the bundle is supposed to live.
    return canonical_path


class ParakeetModelManager:
    """Process-wide shared encoder + decoder_joint ONNX sessions for Parakeet.

    Class-level shared state mirrors :class:`ModelManager` so the same
    ``schedule_unload(delay_seconds)`` idle-unload flow already wired up
    for Whisper works unchanged for Parakeet. Multiple
    ``ParakeetModelManager`` instances (e.g. one for the batch service,
    one for the live ASR backend) share the same underlying sessions
    and never duplicate the ~600 MB encoder in memory.
    """

    # Shared session state.
    _shared_encoder_session: Any = None
    _shared_decoder_session: Any = None
    _shared_vocab: List[str] = []
    _shared_blank_id: int = 0
    _shared_durations: Optional[List[int]] = None  # TDT duration head support set.
    _shared_model_id: Optional[str] = None
    _shared_bundle_dir: Optional[Path] = None
    _shared_loaded: bool = False
    _shared_providers: List[str] = []

    # I/O name caches populated at load time. The decoder loop reads
    # these so input/output renames between re-exports do not break us.
    _shared_encoder_input_names: List[str] = []
    _shared_encoder_output_names: List[str] = []
    _shared_decoder_input_names: List[str] = []
    _shared_decoder_output_names: List[str] = []

    # Concurrency + lifetime.
    _model_lock = threading.Lock()
    _reference_count = 0
    _shared_unload_task: Any = None  # asyncio.Task | None

    def __init__(self):
        with self._model_lock:
            ParakeetModelManager._reference_count += 1
            logger.info(
                f"📊 ParakeetModelManager created. Active instances: "
                f"{ParakeetModelManager._reference_count}"
            )

    # -----------------------------------------------------------------
    # Public lifecycle.
    # -----------------------------------------------------------------

    def load_model(self, model_id: Optional[str] = None) -> None:
        """Load encoder + decoder ONNX sessions and the vocabulary.

        ``model_id`` is the registry key (e.g. ``"NVIDIA-parakeet-tdt-0.6b-v2"``).
        When omitted we fall back to ``preferences.models.transcription_model``
        and look the registry up by display name; the dispatch layer
        always passes the ID directly so the fallback path is for
        defensive callers only.
        """
        with self._model_lock:
            self._cancel_pending_unload_locked()

            target_id = model_id or self._lookup_model_id_from_preferences()
            if target_id is None:
                raise ValueError(
                    "No Parakeet model selected and could not be resolved "
                    "from preferences."
                )

            if (
                self._shared_loaded
                and ParakeetModelManager._shared_model_id == target_id
            ):
                logger.info(
                    f"✅ Parakeet model already loaded (shared, model_id={target_id}, "
                    f"providers={ParakeetModelManager._shared_providers})"
                )
                return

            # Switching to a different Parakeet variant or first load.
            if self._shared_loaded:
                logger.info(
                    f"🔁 Parakeet model change requested "
                    f"({ParakeetModelManager._shared_model_id} -> {target_id}); "
                    f"unloading the previous bundle."
                )
                self._unload_locked()

            self._load_locked(target_id)

    def unload_model(self) -> None:
        """Release the ONNX sessions and free memory."""
        with self._model_lock:
            self._unload_locked()

    def is_model_loaded(self) -> bool:
        return ParakeetModelManager._shared_loaded

    # -----------------------------------------------------------------
    # Idle-unload mirror of ModelManager.schedule_unload / cancel_unload.
    # -----------------------------------------------------------------

    @classmethod
    def schedule_unload(cls, delay_seconds: int) -> None:
        """Schedule an unload after ``delay_seconds``; 0 means immediate.

        Same surface as ``ModelManager.schedule_unload`` so the existing
        WebSocket-driven idle-unload code in
        ``api.routes.websocket_routes.transcription`` can dispatch to
        either Whisper or Parakeet without branching.
        """
        import asyncio

        async def unload_after_delay():
            try:
                logger.info(
                    f"⏰ Scheduling Parakeet model unload in {delay_seconds} seconds"
                )
                await asyncio.sleep(delay_seconds)
                with cls._model_lock:
                    if cls._shared_loaded:
                        logger.info(
                            f"⏰ Unloading Parakeet model after {delay_seconds}s delay"
                        )
                        cls()._unload_locked()
            except asyncio.CancelledError:
                logger.info("🚫 Scheduled Parakeet model unload was cancelled")
                raise
            except Exception as exc:
                logger.warning(f"❌ Error during scheduled Parakeet unload: {exc}")

        with cls._model_lock:
            if cls._shared_unload_task is not None and not cls._shared_unload_task.done():
                logger.info("🔄 Cancelling existing Parakeet unload task")
                cls._shared_unload_task.cancel()

            if delay_seconds == 0:
                logger.info("⚡ Unloading Parakeet model immediately")
                cls()._unload_locked()
                cls._shared_unload_task = None
            else:
                cls._shared_unload_task = asyncio.create_task(unload_after_delay())

    @classmethod
    def cancel_unload(cls) -> None:
        with cls._model_lock:
            if cls._shared_unload_task is not None and not cls._shared_unload_task.done():
                logger.info("🚫 Cancelling scheduled Parakeet model unload")
                cls._shared_unload_task.cancel()
                cls._shared_unload_task = None

    # -----------------------------------------------------------------
    # Properties exposing the shared state.
    # -----------------------------------------------------------------

    @property
    def encoder_session(self):
        return ParakeetModelManager._shared_encoder_session

    @property
    def decoder_session(self):
        return ParakeetModelManager._shared_decoder_session

    @property
    def vocab(self) -> List[str]:
        return ParakeetModelManager._shared_vocab

    @property
    def blank_id(self) -> int:
        return ParakeetModelManager._shared_blank_id

    @property
    def durations(self) -> Optional[List[int]]:
        """TDT duration head support set, e.g. ``[0, 1, 2, 3, 4]`` for v2.

        ``None`` means the bundle does not expose a duration support set
        and the decoder should treat the duration head's argmax as the
        raw frame advance.
        """
        return ParakeetModelManager._shared_durations

    @property
    def bundle_dir(self) -> Optional[Path]:
        return ParakeetModelManager._shared_bundle_dir

    @property
    def encoder_io(self) -> Tuple[List[str], List[str]]:
        return (
            ParakeetModelManager._shared_encoder_input_names,
            ParakeetModelManager._shared_encoder_output_names,
        )

    @property
    def decoder_io(self) -> Tuple[List[str], List[str]]:
        return (
            ParakeetModelManager._shared_decoder_input_names,
            ParakeetModelManager._shared_decoder_output_names,
        )

    # -----------------------------------------------------------------
    # Internal helpers (must be called with _model_lock held).
    # -----------------------------------------------------------------

    def _load_locked(self, model_id: str) -> None:
        try:
            import onnxruntime as ort  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "onnxruntime is required for Parakeet. Install it via "
                "`poetry install` (it is pinned in pyproject.toml)."
            ) from exc

        from .....core.models.models_registry import get_model

        cfg = get_model(model_id)
        if not cfg:
            raise ValueError(f"Parakeet model '{model_id}' not found in registry")

        on_disk_name = cfg.get("on_disk_name")
        if not on_disk_name:
            raise ValueError(f"Parakeet model '{model_id}' has no on_disk_name")

        bundle_dir = _resolve_bundle_dir(on_disk_name)
        if not bundle_dir.exists():
            raise FileNotFoundError(
                f"Parakeet bundle directory not found: {bundle_dir}. "
                f"Download the model first via the Models settings panel."
            )

        # The Parakeet registry entries declare a `precision` field
        # (added to TranscriptionConfig in schema.py) so we know which
        # weight files to load without inspecting the bundle dir. The
        # downloader writes only the precision-matching files into
        # `bundle_dir`, so a mismatch here would mean either:
        #   (a) the registry entry is missing `precision` (treated as
        #       fp32 with a loud warning -- legacy fallback only), or
        #   (b) the user has manually placed mismatched files into the
        #       bundle dir (we fail loudly via _find_required_file
        #       rather than silently load the wrong variant).
        precision = (cfg.get("precision") or "").lower()
        if precision == "int8":
            encoder_filenames = ["encoder-model.int8.onnx"]
            decoder_filenames = ["decoder_joint-model.int8.onnx"]
        elif precision == "fp32":
            encoder_filenames = ["encoder-model.onnx", "encoder.onnx"]
            decoder_filenames = ["decoder_joint-model.onnx", "decoder_joint.onnx"]
        else:
            logger.warning(
                f"⚠️  Parakeet registry entry '{model_id}' has no "
                f"`precision` field; defaulting to fp32 search order. "
                f"Add `precision: 'int8'` or `precision: 'fp32'` to the "
                f"entry in transcription_registry.py to silence this."
            )
            encoder_filenames = ["encoder-model.onnx", "encoder.onnx"]
            decoder_filenames = ["decoder_joint-model.onnx", "decoder_joint.onnx"]

        encoder_path = self._find_required_file(
            bundle_dir,
            encoder_filenames,
            label=f"Parakeet encoder ONNX ({precision or 'fp32-default'})",
        )
        decoder_path = self._find_required_file(
            bundle_dir,
            decoder_filenames,
            label=f"Parakeet decoder_joint ONNX ({precision or 'fp32-default'})",
        )
        vocab_path = self._find_optional_file(
            bundle_dir,
            ["vocab.txt", "tokens.txt"],
        )

        providers = _detect_execution_providers()
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = (
            ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        )

        logger.info(
            f"🔄 Loading Parakeet ONNX sessions from {bundle_dir} "
            f"(providers={providers})"
        )
        t0 = time.monotonic()
        encoder_session = ort.InferenceSession(
            str(encoder_path), sess_options=sess_options, providers=providers
        )
        decoder_session = ort.InferenceSession(
            str(decoder_path), sess_options=sess_options, providers=providers
        )
        elapsed = time.monotonic() - t0
        logger.info(
            f"✅ Parakeet ONNX sessions loaded in {elapsed:.2f}s "
            f"(encoder providers={encoder_session.get_providers()}, "
            f"decoder providers={decoder_session.get_providers()})"
        )

        vocab, blank_id = self._load_vocab(vocab_path)
        durations = self._load_durations(bundle_dir)

        ParakeetModelManager._shared_encoder_session = encoder_session
        ParakeetModelManager._shared_decoder_session = decoder_session
        ParakeetModelManager._shared_vocab = vocab
        ParakeetModelManager._shared_blank_id = blank_id
        ParakeetModelManager._shared_durations = durations
        ParakeetModelManager._shared_model_id = model_id
        ParakeetModelManager._shared_bundle_dir = bundle_dir
        ParakeetModelManager._shared_providers = list(encoder_session.get_providers())

        ParakeetModelManager._shared_encoder_input_names = [
            i.name for i in encoder_session.get_inputs()
        ]
        ParakeetModelManager._shared_encoder_output_names = [
            o.name for o in encoder_session.get_outputs()
        ]
        ParakeetModelManager._shared_decoder_input_names = [
            i.name for i in decoder_session.get_inputs()
        ]
        ParakeetModelManager._shared_decoder_output_names = [
            o.name for o in decoder_session.get_outputs()
        ]

        ParakeetModelManager._shared_loaded = True
        logger.info(
            f"📊 Parakeet vocab size={len(vocab)} blank_id={blank_id} "
            f"durations={durations} encoder_inputs={self._shared_encoder_input_names} "
            f"decoder_inputs={self._shared_decoder_input_names}"
        )

    def _unload_locked(self) -> None:
        if not ParakeetModelManager._shared_loaded:
            return
        logger.info("🧹 Unloading Parakeet ONNX sessions")
        ParakeetModelManager._shared_encoder_session = None
        ParakeetModelManager._shared_decoder_session = None
        ParakeetModelManager._shared_vocab = []
        ParakeetModelManager._shared_blank_id = 0
        ParakeetModelManager._shared_durations = None
        ParakeetModelManager._shared_model_id = None
        ParakeetModelManager._shared_bundle_dir = None
        ParakeetModelManager._shared_providers = []
        ParakeetModelManager._shared_encoder_input_names = []
        ParakeetModelManager._shared_encoder_output_names = []
        ParakeetModelManager._shared_decoder_input_names = []
        ParakeetModelManager._shared_decoder_output_names = []
        ParakeetModelManager._shared_loaded = False
        gc.collect()
        logger.info("✅ Parakeet ONNX sessions unloaded")

    def _cancel_pending_unload_locked(self) -> None:
        task = ParakeetModelManager._shared_unload_task
        if task is not None and not task.done():
            logger.info("🚫 Cancelling pending Parakeet unload due to new usage")
            task.cancel()
            ParakeetModelManager._shared_unload_task = None

    # -----------------------------------------------------------------
    # Bundle discovery utilities.
    # -----------------------------------------------------------------

    @staticmethod
    def _find_required_file(bundle_dir: Path, candidates: List[str], *, label: str) -> Path:
        for name in candidates:
            path = bundle_dir / name
            if path.exists():
                return path
        # Walk one level deep -- some community bundles nest under a
        # subdirectory matching the repo name.
        for child in bundle_dir.iterdir():
            if child.is_dir():
                for name in candidates:
                    nested = child / name
                    if nested.exists():
                        return nested
        raise FileNotFoundError(
            f"{label} not found in {bundle_dir}. Looked for {candidates}."
        )

    @staticmethod
    def _find_optional_file(bundle_dir: Path, candidates: List[str]) -> Optional[Path]:
        for name in candidates:
            path = bundle_dir / name
            if path.exists():
                return path
        for child in bundle_dir.iterdir():
            if child.is_dir():
                for name in candidates:
                    nested = child / name
                    if nested.exists():
                        return nested
        return None

    @staticmethod
    def _load_vocab(vocab_path: Optional[Path]) -> Tuple[List[str], int]:
        """Read the vocab file and pick a sensible blank id.

        The istupakov bundle writes ``vocab.txt`` as ``<token> <index>``
        per line (e.g. ``"▁would 108"``), while some other exports use
        token-only lines. We support both formats:

        - If the line ends with an integer, parse it as ``token id``.
        - Otherwise treat the whole line as the token text.

        This avoids leaking token IDs into decoded text (e.g.
        ``"would 108"``) during detokenization.

        We default the blank id to ``len(vocab) - 1`` -- the standard
        NeMo convention for RNNT/TDT decoders -- and override only if an
        explicit blank marker is found.
        """
        if vocab_path is None:
            raise FileNotFoundError(
                "Parakeet vocab.txt was not found in the bundle. "
                "The decoder cannot detokenize without it."
            )
        vocab: List[str] = []
        blank_id: Optional[int] = None
        with open(vocab_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if line == "":
                    continue

                token = line
                parsed_id: Optional[int] = None
                parts = line.rsplit(maxsplit=1)
                if len(parts) == 2:
                    try:
                        parsed_id = int(parts[1])
                        token = parts[0]
                    except ValueError:
                        # Token-only format (or token that ends in a
                        # non-id suffix). Keep full line as token.
                        token = line

                vocab.append(token)
                if token in ("<blank>", "[BLANK]", "<pad>", "<blk>"):
                    # Prefer explicit id from file if present; otherwise
                    # fall back to the token's position in vocab.
                    blank_id = parsed_id if parsed_id is not None else (len(vocab) - 1)

        resolved_blank_id = blank_id if blank_id is not None else (len(vocab) - 1)
        return vocab, resolved_blank_id

    @staticmethod
    def _load_durations(bundle_dir: Path) -> Optional[List[int]]:
        """Look for the TDT duration support set, e.g. in ``model_config.yaml``.

        For ``parakeet-tdt-0.6b-v2`` the support set is ``[0, 1, 2, 3, 4]``
        (frame advances the joint head's duration logits index into).
        We try a YAML lookup and fall back to that documented default
        because the istupakov bundle does not always include the file.
        """
        try:
            import yaml  # type: ignore
        except ImportError:
            return [0, 1, 2, 3, 4]

        for candidate in ("model_config.yaml", "config.yaml"):
            path = bundle_dir / candidate
            if not path.exists():
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg: Dict[str, Any] = yaml.safe_load(f) or {}
            except Exception:
                continue
            # NeMo nests TDT support set under model.model_defaults.tdt_durations
            # or model.loss.durations -- check both.
            for key_path in (
                ("model", "model_defaults", "tdt_durations"),
                ("model", "loss", "durations"),
                ("model", "decoder", "tdt_durations"),
            ):
                node: Any = cfg
                for key in key_path:
                    if not isinstance(node, dict):
                        node = None
                        break
                    node = node.get(key)
                if isinstance(node, list) and all(isinstance(x, int) for x in node):
                    return list(node)
        return [0, 1, 2, 3, 4]

    @staticmethod
    def _lookup_model_id_from_preferences() -> Optional[str]:
        try:
            from .....core.models.preferences import Preferences
            from .....core.models.models_registry import get_parakeet_transcription_models

            prefs = Preferences.load()
            display = prefs.models.transcription_model
            if not display:
                return None
            for model_id, cfg in get_parakeet_transcription_models().items():
                if cfg.get("display_name") == display:
                    return model_id
        except Exception as exc:
            logger.warning(
                f"Could not resolve Parakeet model id from preferences: {exc}"
            )
        return None

    def __del__(self):
        try:
            with self._model_lock:
                if ParakeetModelManager._reference_count > 0:
                    ParakeetModelManager._reference_count -= 1
        except Exception:
            pass
