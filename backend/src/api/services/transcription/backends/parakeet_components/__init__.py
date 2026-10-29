"""Parakeet ONNX backend components.

Shared building blocks used by both the batch transcription path
(`parakeet_service.ParakeetTranscriptionService`) and the live path
(`whisper_live_core/local_agreement/parakeet_backend.ParakeetASR`).

Splitting these out keeps the two callers using a single source of truth
for feature extraction, ONNX session management, and TDT decoding so the
batch and live experiences stay aligned and so we never hold two copies
of the model in memory at once.
"""

from .parakeet_audio_features import (
    ParakeetFeatureExtractor,
    DEFAULT_FEATURE_PARAMS,
)
from .parakeet_model_manager import ParakeetModelManager
from .parakeet_decoder import (
    decode_tdt_greedy,
    detokenize_pieces,
    pieces_to_words,
    ParakeetToken,
)
from .parakeet_chunking import (
    ParakeetAudioChunk,
    WordTuple,
    build_silence_aware_parakeet_chunks,
    offset_and_filter_parakeet_words,
    deduplicate_parakeet_boundary_words,
    parakeet_word_tuples_to_text,
    parakeet_word_tuples_to_segments,
)
from .parakeet_progress import (
    PARAKEET_PROGRESS_CALLBACK_CONTEXT_KEY,
    ParakeetProgressCallback,
    ParakeetTranscriptionProgress,
)
from .parakeet_audio_diagnostics import log_parakeet_audio_coverage_diagnostics

__all__ = [
    "ParakeetFeatureExtractor",
    "DEFAULT_FEATURE_PARAMS",
    "ParakeetModelManager",
    "decode_tdt_greedy",
    "detokenize_pieces",
    "pieces_to_words",
    "ParakeetToken",
    "ParakeetAudioChunk",
    "WordTuple",
    "build_silence_aware_parakeet_chunks",
    "offset_and_filter_parakeet_words",
    "deduplicate_parakeet_boundary_words",
    "parakeet_word_tuples_to_text",
    "parakeet_word_tuples_to_segments",
    "PARAKEET_PROGRESS_CALLBACK_CONTEXT_KEY",
    "ParakeetProgressCallback",
    "ParakeetTranscriptionProgress",
    "log_parakeet_audio_coverage_diagnostics",
]
