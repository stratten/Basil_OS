"""Parakeet ONNX transcription service.

Implements :class:`BaseTranscriptionService` for the NVIDIA Parakeet TDT
0.6B v2 model running through ONNX Runtime. Drops in alongside
:class:`HuggingFaceTranscriptionService` and
:class:`OpenAIWhisperAPITranscriptionService` so the dispatch layer in
:mod:`api.dependencies` can return any of the three based on the user's
preference.

The actual ONNX work (encoder + TDT decode) lives in
:mod:`parakeet_components`; this module is a thin coordinator that
* resolves the model id from the registry,
* drives the shared :class:`ParakeetModelManager` lifecycle,
* persists audio + history rows via :mod:`transcription_lifecycle`
  exactly like the HF and cloud services do, and
* returns the same plain-text string contract that the rest of Basil
  expects from ``transcribe(audio_data, context_info) -> str``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from time import time
from typing import Any, Dict, List, Optional, Tuple

import librosa
import numpy as np

from ..base_transcription_service import BaseTranscriptionService
from ..processing import transcription_lifecycle
from ..processing.audio_utils import rms_normalize_audio
from .parakeet_components import (
    PARAKEET_PROGRESS_CALLBACK_CONTEXT_KEY,
    ParakeetFeatureExtractor,
    ParakeetModelManager,
    ParakeetProgressCallback,
    decode_tdt_greedy,
    log_parakeet_audio_coverage_diagnostics,
    pieces_to_words,
)
from .parakeet_components.parakeet_decoder import detokenize_pieces
from .parakeet_components.parakeet_adaptive_transcription import (
    ParakeetPipelineTranscript,
    run_adaptive_parakeet_transcription,
)
from .parakeet_components.parakeet_long_form import transcribe_long_form_parakeet_audio

from ....core.config.api_settings import settings
from ....core.logging.api_logger import setup_api_logger

logger = setup_api_logger(
    __name__,
    log_file=settings.STORAGE_DIR / "logs" / "api.log" if not settings.DEBUG else None,
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
)


PARAKEET_TARGET_SAMPLE_RATE: int = 16000
PARAKEET_LONG_FORM_THRESHOLD_SECONDS: float = 60.0


class ParakeetTranscriptionService(BaseTranscriptionService):
    """Local Parakeet transcription via ONNX Runtime.

    A single instance is cheap because all heavy state lives on the
    class-level :class:`ParakeetModelManager`. The dispatch layer can
    safely construct one per call or share one via ``app.state`` --
    either way the underlying ONNX sessions are loaded once.
    """

    def __init__(self, model_id: Optional[str] = None):
        super().__init__()
        self._model_id: Optional[str] = model_id
        self._model_manager = ParakeetModelManager()
        self._feature_extractor: Optional[ParakeetFeatureExtractor] = None

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def load_model(self) -> None:
        """Load the configured Parakeet bundle into memory.

        ``model_id`` resolution order: explicit constructor arg ->
        ``preferences.models.transcription_model`` (resolved by the
        manager). Idempotent and safe to call repeatedly; the manager
        handles "already loaded" detection.
        """
        target_id = self._model_id or self._resolve_model_id_from_preferences()
        self._model_manager.load_model(target_id)
        self._model_loaded = self._model_manager.is_model_loaded()
        if self._model_loaded and self._feature_extractor is None:
            self._feature_extractor = self._build_feature_extractor()

    def unload_model(self) -> None:
        self._model_manager.unload_model()
        self._model_loaded = False

    def is_model_loaded(self) -> bool:
        return self._model_manager.is_model_loaded()

    @classmethod
    def schedule_unload(cls, delay_seconds: int) -> None:
        """Mirror of :meth:`HuggingFaceTranscriptionService.schedule_unload`.

        Keeps the WebSocket idle-unload code interchangeable between
        Whisper and Parakeet.
        """
        ParakeetModelManager.schedule_unload(delay_seconds)

    @classmethod
    def cancel_unload(cls) -> None:
        ParakeetModelManager.cancel_unload()

    # -----------------------------------------------------------------
    # Transcription
    # -----------------------------------------------------------------

    async def transcribe(
        self,
        audio_data: bytes,
        context_info: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Transcribe ``audio_data`` and return the recognized text.

        Persistence semantics match :class:`HuggingFaceTranscriptionService`:
        the audio is saved to disk and (for non-suggestion contexts) a
        ``pending`` history row is created BEFORE the model runs, so a
        crash mid-inference leaves a recoverable state for the user.
        """
        if not self.is_model_loaded():
            logger.info("ℹ️ Parakeet model not loaded; loading now before transcribing...")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.load_model)
            if not self.is_model_loaded():
                raise ValueError("Parakeet model failed to load.")
        # Defensive: feature extractor builds lazily on first load.
        if self._feature_extractor is None:
            self._feature_extractor = self._build_feature_extractor()

        context_for_lifecycle = dict(context_info or {})
        progress_callback = context_for_lifecycle.pop(
            PARAKEET_PROGRESS_CALLBACK_CONTEXT_KEY,
            None,
        )
        language = context_for_lifecycle.get("language")

        model_name_for_history = self._history_model_name()

        stub = await transcription_lifecycle.begin(
            audio_data,
            context_for_lifecycle,
            model_name=model_name_for_history,
            language=language if language and language != "auto" else None,
        )

        try:
            wav_path = stub.audio_path
            if stub.is_retranscription and not wav_path.exists():
                raise ValueError(f"Existing audio file not found: {wav_path}")

            start_time = datetime.now()

            loop = asyncio.get_running_loop()
            text = await loop.run_in_executor(
                None,
                self._transcribe_wav,
                str(wav_path),
                progress_callback,
            )

            processing_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            # Match the trailing-space convention used by
            # HuggingFaceTranscriptionService so downstream consumers
            # (autocomplete, voice listener) see consistent output.
            if text:
                text = text + " "

            await transcription_lifecycle.complete(
                stub,
                text,
                processing_time_ms=processing_time_ms,
                model_name=model_name_for_history,
            )

            logger.info(
                f"✅ Parakeet transcription complete ({len(text)} chars, "
                f"{processing_time_ms} ms)"
            )
            return text

        except Exception as exc:
            logger.error(f"❌ Parakeet transcription failed: {exc}")
            try:
                await transcription_lifecycle.fail(
                    stub,
                    str(exc),
                    model_name=model_name_for_history,
                )
            except Exception as persist_exc:
                logger.warning(
                    f"Also failed to record Parakeet failure: {persist_exc}"
                )
            raise

    # -----------------------------------------------------------------
    # Inference (sync, runs in executor).
    # -----------------------------------------------------------------

    def _transcribe_wav(
        self,
        wav_path: str,
        progress_callback: Optional[ParakeetProgressCallback] = None,
    ) -> str:
        """Run the encoder + TDT decoder on a single WAV file.

        Centralised so the live ASR backend can call the same shared
        pipeline (it bypasses this method and uses the lower-level
        components directly to avoid the file-IO round trip, but the
        feature extraction and decoding parameters stay in lock-step).
        """
        audio, sr = librosa.load(wav_path, sr=PARAKEET_TARGET_SAMPLE_RATE, mono=True)
        if audio.size == 0:
            logger.warning(f"Parakeet: empty audio at {wav_path}")
            return ""

        log_parakeet_audio_coverage_diagnostics(
            audio,
            sample_rate=sr,
            source=f"wav:{Path(wav_path).name}",
            logger=logger,
        )
        audio_duration_seconds = (
            audio.size / PARAKEET_TARGET_SAMPLE_RATE if audio.size else 0.0
        )
        if audio_duration_seconds >= PARAKEET_LONG_FORM_THRESHOLD_SECONDS:
            return transcribe_long_form_parakeet_audio(
                audio.astype(np.float32, copy=False),
                sample_rate=sr,
                infer_words=self.transcribe_array,
                progress_callback=progress_callback,
                logger=logger,
            )

        adaptive_result = run_adaptive_parakeet_transcription(
            audio.astype(np.float32, copy=False),
            sample_rate=sr,
            infer_transcript=self._infer_pipeline_transcript,
        )
        logger.info(
            "Parakeet adaptive result: selected=%s baseline_suspect=%s "
            "coverage_score=%.3f reasons=%s runs=%s",
            adaptive_result.selected_strategy,
            adaptive_result.baseline_suspect,
            adaptive_result.selected_run.coverage.coverage_score,
            adaptive_result.selected_run.coverage.reasons,
            [
                {
                    "strategy": run.strategy,
                    "score": run.coverage.coverage_score,
                    "words": run.coverage.word_count,
                    "chars": run.coverage.text_chars,
                    "reasons": run.coverage.reasons,
                }
                for run in adaptive_result.runs
            ],
        )
        return adaptive_result.text

    def _infer_pipeline(self, audio: np.ndarray) -> str:
        return self._infer_pipeline_transcript(audio).text

    def _infer_pipeline_transcript(self, audio: np.ndarray) -> ParakeetPipelineTranscript:
        """Feature extraction -> encoder -> TDT decoder -> text.

        ``audio`` must be 1-D float32 mono at 16 kHz. Returns the
        de-tokenized transcript (no trailing space; the caller adds
        one).
        """
        assert self._feature_extractor is not None
        encoder_session = self._model_manager.encoder_session
        decoder_session = self._model_manager.decoder_session
        if encoder_session is None or decoder_session is None:
            raise RuntimeError(
                "Parakeet ONNX sessions are not available -- did the model "
                "fail to load?"
            )

        pipeline_start = time()
        features, length = self._feature_extractor.compute(audio)
        logger.info(
            "Parakeet direct feature extraction: audio_duration=%.2fs features_shape=%s length=%s",
            audio.size / PARAKEET_TARGET_SAMPLE_RATE if audio.size else 0.0,
            getattr(features, "shape", None),
            length.tolist() if hasattr(length, "tolist") else length,
        )

        encoder_inputs = self._build_encoder_feed(features, length)
        encoder_output_names = self._model_manager.encoder_io[1]
        encoder_start = time()
        try:
            encoder_outputs = encoder_session.run(
                encoder_output_names, encoder_inputs
            )
        except Exception as exc:
            logger.error(
                f"Parakeet encoder ONNX run failed (input shapes: "
                f"{[(k, v.shape, v.dtype) for k, v in encoder_inputs.items()]}): "
                f"{exc}"
            )
            raise
        logger.info(
            "Parakeet direct encoder run complete in %.2fs: outputs=%s",
            time() - encoder_start,
            [getattr(output, "shape", None) for output in encoder_outputs],
        )

        outputs_by_name = dict(zip(encoder_output_names, encoder_outputs))
        encoder_hidden, encoded_lengths = self._extract_encoder_outputs(
            outputs_by_name, fallback_length=int(length[0])
        )
        logger.info(
            "Parakeet direct encoder coverage: hidden_shape=%s encoded_lengths=%s fallback_length=%s",
            getattr(encoder_hidden, "shape", None),
            encoded_lengths.tolist() if hasattr(encoded_lengths, "tolist") else encoded_lengths,
            int(length[0]),
        )

        decoder_start = time()
        tokens = decode_tdt_greedy(
            encoder_hidden,
            encoded_lengths,
            decoder_session,
            vocab=self._model_manager.vocab,
            blank_id=self._model_manager.blank_id,
            durations=self._model_manager.durations,
            decoder_input_names=self._model_manager.decoder_io[0],
            decoder_output_names=self._model_manager.decoder_io[1],
        )
        text = detokenize_pieces(tokens)
        words = pieces_to_words(tokens)
        logger.info(
            "Parakeet direct decoder coverage: decoder_wall=%.2fs pieces=%s words=%s "
            "text_chars=%s total_wall=%.2fs",
            time() - decoder_start,
            len(tokens),
            len(words),
            len(text),
            time() - pipeline_start,
        )
        if words:
            logger.info(
                "Parakeet direct word timeline: first=%.2fs last=%.2fs span=%.2fs",
                words[0].start_sec,
                words[-1].end_sec,
                max(0.0, words[-1].end_sec - words[0].start_sec),
            )
        return ParakeetPipelineTranscript(text=text, words=words)

    def transcribe_array(self, audio: np.ndarray) -> List[Tuple[str, float, float]]:
        """Run the full pipeline on an in-memory float32 audio array.

        Returns word-level ``(text, start_sec, end_sec)`` triples.
        Used by the live ASR backend (:mod:`whisper_live_core`
        ``parakeet_backend``) to feed ``ts_words`` without any file IO.
        """
        if not self.is_model_loaded():
            self.load_model()
        if self._feature_extractor is None:
            self._feature_extractor = self._build_feature_extractor()
        assert self._feature_extractor is not None

        encoder_session = self._model_manager.encoder_session
        decoder_session = self._model_manager.decoder_session
        if encoder_session is None or decoder_session is None:
            raise RuntimeError("Parakeet ONNX sessions not loaded")

        transcribe_start = time()
        logger.info(
            "Parakeet transcribe_array start: samples=%s duration=%.2fs",
            audio.size,
            audio.size / PARAKEET_TARGET_SAMPLE_RATE if audio.size else 0.0,
        )

        feature_start = time()
        features, length = self._feature_extractor.compute(audio)
        logger.info(
            "Parakeet feature extraction complete in %.2fs: features_shape=%s length=%s",
            time() - feature_start,
            getattr(features, "shape", None),
            length.tolist() if hasattr(length, "tolist") else length,
        )

        encoder_inputs = self._build_encoder_feed(features, length)
        encoder_output_names = self._model_manager.encoder_io[1]
        encoder_start = time()
        encoder_outputs = encoder_session.run(encoder_output_names, encoder_inputs)
        logger.info(
            "Parakeet encoder run complete in %.2fs: outputs=%s",
            time() - encoder_start,
            [getattr(output, "shape", None) for output in encoder_outputs],
        )

        outputs_by_name = dict(zip(encoder_output_names, encoder_outputs))
        encoder_hidden, encoded_lengths = self._extract_encoder_outputs(
            outputs_by_name, fallback_length=int(length[0])
        )

        decoder_start = time()
        pieces = decode_tdt_greedy(
            encoder_hidden,
            encoded_lengths,
            decoder_session,
            vocab=self._model_manager.vocab,
            blank_id=self._model_manager.blank_id,
            durations=self._model_manager.durations,
            decoder_input_names=self._model_manager.decoder_io[0],
            decoder_output_names=self._model_manager.decoder_io[1],
        )
        logger.info(
            "Parakeet decoder run complete in %.2fs: pieces=%s",
            time() - decoder_start,
            len(pieces),
        )

        word_start = time()
        words = pieces_to_words(pieces)
        logger.info(
            "Parakeet word conversion complete in %.2fs: words=%s total_elapsed=%.2fs",
            time() - word_start,
            len(words),
            time() - transcribe_start,
        )
        return [(w.text, w.start_sec, w.end_sec) for w in words]

    # -----------------------------------------------------------------
    # ONNX feed/output adapters.
    # -----------------------------------------------------------------

    def _build_encoder_feed(
        self, features: np.ndarray, length: np.ndarray
    ) -> Dict[str, np.ndarray]:
        """Map our (features, length) tensors to the encoder's named inputs.

        Looks up the actual input names from the manager so re-exports
        with renamed inputs (e.g. ``audio_signal`` vs ``input``) work
        without a code change.
        """
        encoder_input_names = self._model_manager.encoder_io[0]
        feed: Dict[str, np.ndarray] = {}
        for name in encoder_input_names:
            lname = name.lower()
            if "length" in lname:
                feed[name] = length
            else:
                # Anything else is the spectrogram input.
                feed[name] = features
        return feed

    @staticmethod
    def _extract_encoder_outputs(
        outputs_by_name: Dict[str, np.ndarray],
        *,
        fallback_length: int,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Pull (encoder_hidden, encoded_lengths) out of the encoder output dict.

        Heuristics: the hidden tensor is rank-3 ``[B, T, D]``; the
        length tensor is rank-1 ``[B]``. If the bundle does not emit a
        length tensor we synthesise one from the input mel length
        (worst case the decoder over-runs into zero-padded frames,
        which it will still see as silence).
        """
        encoder_hidden: Optional[np.ndarray] = None
        encoded_lengths: Optional[np.ndarray] = None
        for name, value in outputs_by_name.items():
            arr = np.asarray(value)
            if arr.ndim == 3 and encoder_hidden is None:
                encoder_hidden = arr
            elif arr.ndim == 1 and encoded_lengths is None:
                encoded_lengths = arr.astype(np.int64)
        if encoder_hidden is None:
            raise RuntimeError(
                f"Could not find rank-3 encoder hidden output among "
                f"{list(outputs_by_name.keys())}"
            )
        if encoded_lengths is None:
            encoded_lengths = np.asarray([encoder_hidden.shape[1]], dtype=np.int64)
            logger.debug(
                f"Encoder did not emit explicit lengths; using full T={int(encoded_lengths[0])}"
            )
        return encoder_hidden, encoded_lengths

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _resolve_model_id_from_preferences(self) -> Optional[str]:
        try:
            from ...core.models.preferences import Preferences
            from ...core.models.models_registry import get_parakeet_transcription_models

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

    def _history_model_name(self) -> str:
        """Stable name string for the transcription history row."""
        return f"nvidia/{self._model_id}" if self._model_id else "nvidia/parakeet"

    def _build_feature_extractor(self) -> ParakeetFeatureExtractor:
        """Build a feature extractor, optionally seeded by the bundle's YAML.

        Falls back to defaults when the bundle does not ship a
        ``preprocessor_config.yaml`` (the istupakov bundle does ship
        one).
        """
        bundle_dir = self._model_manager.bundle_dir
        if bundle_dir is not None:
            yaml_path = bundle_dir / "preprocessor_config.yaml"
            if yaml_path.exists():
                return ParakeetFeatureExtractor.from_preprocessor_yaml(yaml_path)
        return ParakeetFeatureExtractor()

