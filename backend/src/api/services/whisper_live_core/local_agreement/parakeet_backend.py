"""LocalAgreement-compatible streaming backend for NVIDIA Parakeet TDT (ONNX).

This backend bridges the Phase 1 Parakeet ONNX components (feature
extractor + encoder + decoder_joint + greedy TDT decode) into the
existing :mod:`whisper_live_core` LocalAgreement streaming pipeline.

It mirrors the small surface :class:`backends.ASRBase` exposes so the
existing :class:`OnlineASRProcessor` can drive Parakeet exactly the
same way it drives :class:`backends.WhisperASR` /
:class:`backends.FasterWhisperASR`:

  * ``transcribe(audio, init_prompt="")`` → opaque "result" object
  * ``ts_words(result)`` → ``List[ASRToken]`` of word-level timings
  * ``segments_end_ts(result)`` → ``List[float]`` of segment end times
  * ``use_vad()`` → no-op (Parakeet has no built-in VAD switch)

Phase 2 (cache-aware streaming) is intentionally deferred -- this
backend re-runs the encoder + greedy decode on every LocalAgreement
window. For 0.6B v2/v3 on Apple Silicon this is fast enough to stay
within the 1-2 s chunk budget the upstream pipeline uses.
"""

from __future__ import annotations

import logging
import sys
from typing import List, Tuple

import numpy as np

from whisperlivekit.timed_objects import ASRToken

from .backends import ASRBase

logger = logging.getLogger(__name__)


class ParakeetASR(ASRBase):
    """ASRBase implementation backed by ParakeetTranscriptionService.

    The class fields and constructor signature follow the same contract
    as the other backends so :func:`backend_factory` can instantiate it
    via ``ParakeetASR(model_size=..., lan=..., cache_dir=..., model_dir=...)``.

    ``model_size`` here doubles as the Parakeet *registry id* (e.g.
    ``"NVIDIA-parakeet-tdt-0.6b-v2-quantized"`` or
    ``"NVIDIA-parakeet-tdt-0.6b-v3-quantized"``) so we can pull the
    right bundle out of Basil's canonical models directory. ``cache_dir``
    and ``model_dir`` are accepted for signature parity but are unused --
    Parakeet bundle resolution is owned by ParakeetTranscriptionService.
    """

    # `pieces_to_words` in `parakeet_decoder` calls `.strip()` on each
    # word piece before returning, which discards the SentencePiece
    # leading space marker. As a result, downstream consumers
    # (LocalAgreement n-gram comparison, OnlineASRProcessor.to_flush)
    # receive bare words like "Hello", "world" -- joining those with
    # "" produces "Helloworld". Use a single space to restore normal
    # word separation. WhisperASR uses the same convention for the
    # same reason.
    sep = " "

    def __init__(
        self,
        lan,
        model_size=None,
        cache_dir=None,
        model_dir=None,
        logfile=sys.stderr,
    ):
        # The Parakeet TDT 0.6B v2 export is English-only, while v3 is
        # multilingual (25 European languages). We accept the lang
        # argument for API parity with the Whisper backends and only
        # warn when the resolved registry id is the v2 family AND the
        # caller asked for a non-English language -- in that case the
        # v2 model will silently transcribe as English regardless. For
        # v3 (or when the registry id is unknown at construction time)
        # we pass the language through without comment.
        is_v2 = bool(model_size) and "-v2" in str(model_size)
        if is_v2 and lan and lan not in ("auto", "en"):
            logger.warning(
                "ParakeetASR was asked for language %r, but the bundled "
                "Parakeet TDT 0.6B v2 model is English-only. Continuing "
                "with English transcription.",
                lan,
            )
        super().__init__(
            lan=lan,
            model_size=model_size,
            cache_dir=cache_dir,
            model_dir=model_dir,
            logfile=logfile,
        )

    # -----------------------------------------------------------------
    # Lifecycle.
    # -----------------------------------------------------------------
    def load_model(self, model_size=None, cache_dir=None, model_dir=None):
        """Build (or reuse) the shared Parakeet service and warm the ONNX sessions.

        All three Parakeet-related modules live behind a single
        :class:`ParakeetTranscriptionService`. Because that service's
        underlying :class:`ParakeetModelManager` keeps its encoder and
        decoder_joint sessions in *class-level* shared state, multiple
        ``ParakeetASR`` instances (e.g. one per live websocket) safely
        reuse the same in-memory ONNX sessions instead of duplicating
        them per stream.
        """
        from api.services.transcription.backends.parakeet_service import (
            ParakeetTranscriptionService,
        )

        # `model_size` arrives from the upstream config_mapper as the
        # Parakeet registry id. If it's missing (e.g. someone constructed
        # the backend with default kwargs), fall back to the canonical
        # 0.6B v2 entry so the streaming session can still come up.
        registry_id = model_size or "NVIDIA-parakeet-tdt-0.6b-v2"
        service = ParakeetTranscriptionService(model_id=registry_id)
        service.load_model()
        return service

    # -----------------------------------------------------------------
    # Inference.
    # -----------------------------------------------------------------
    def transcribe(self, audio, init_prompt: str = "") -> List[Tuple[str, float, float]]:
        """Run a full forward pass over ``audio`` and return word triples.

        ``init_prompt`` is accepted for signature parity but ignored --
        Parakeet TDT is a pure RNN-T-style streaming decoder and does
        not condition on a prior prompt the way Whisper does.
        """
        if init_prompt:
            logger.debug(
                "ParakeetASR.transcribe ignoring init_prompt of length %d "
                "(Parakeet TDT does not condition on prompts).",
                len(init_prompt),
            )
        if audio is None or len(audio) == 0:
            return []

        # OnlineASRProcessor hands us a float32 mono numpy array at 16 kHz,
        # matching the contract of `ParakeetTranscriptionService.transcribe_array`.
        if not isinstance(audio, np.ndarray):
            audio = np.asarray(audio, dtype=np.float32)
        elif audio.dtype != np.float32:
            audio = audio.astype(np.float32, copy=False)

        return self.model.transcribe_array(audio)

    # -----------------------------------------------------------------
    # ASRBase result adapters.
    # -----------------------------------------------------------------
    def ts_words(self, result) -> List[ASRToken]:
        """Convert ``transcribe`` output into ``ASRToken``s used by LocalAgreement."""
        tokens: List[ASRToken] = []
        for entry in result or []:
            text, start, end = entry
            if not text:
                continue
            tokens.append(ASRToken(start, end, text))
        return tokens

    def segments_end_ts(self, result) -> List[float]:
        """LocalAgreement uses this to decide when to trim the audio buffer.

        Parakeet does not produce explicit segment boundaries (it emits a
        flat stream of word tokens), so we return each word's end time as
        a one-word "segment". This matches what FasterWhisperASR does
        when it hands back a list of single-word segments and is
        sufficient for the buffer-trimming heuristics upstream.
        """
        return [end for _text, _start, end in (result or [])]

    def use_vad(self):
        """Parakeet has no first-class VAD knob -- log and ignore."""
        logger.warning(
            "VAD was requested but ParakeetASR has no built-in VAD switch; "
            "ignoring. Upstream Silero VAD (if enabled) still runs."
        )
