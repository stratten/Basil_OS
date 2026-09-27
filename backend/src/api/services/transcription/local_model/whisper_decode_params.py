"""
Shared anti-hallucination / anti-repetition decode parameters for local Whisper
retranscription.

Greedy decoding with no repetition controls is Whisper's classic failure mode on
low-information or near-silent audio: it produces runaway token loops
(e.g. "very, very, very, ..."). These parameters add (1) n-gram/repetition
penalties that break loops, and (2) the temperature-fallback + quality
thresholds that make Whisper re-decode a degenerate segment instead of
committing it verbatim.

Defined once here so the HuggingFace and faster-whisper paths stay in sync and
no constants are duplicated across the post-processing transcription processor.

Verified against the project ``.venv``: transformers 4.53.1, faster-whisper
1.1.1, torch 2.5.1.
"""
from __future__ import annotations

from typing import Any, Dict

# Temperature fallback ladder. Whisper re-decodes a segment at the next
# temperature when the prior attempt trips a quality threshold below.
_TEMPERATURE_FALLBACK = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)

# Shared quality thresholds (same numeric meaning in both backends).
_COMPRESSION_RATIO_THRESHOLD = 2.4   # gzip ratio above this => likely repetition
_LOGPROB_THRESHOLD = -1.0            # avg token logprob below this => low confidence
_NO_SPEECH_THRESHOLD = 0.6           # no-speech prob above this => treat as silence

# Repetition suppression applied during generation.
_NO_REPEAT_NGRAM_SIZE = 3
_REPETITION_PENALTY = 1.15


def hf_generate_kwargs() -> Dict[str, Any]:
    """generate_kwargs for the transformers Whisper ASR pipeline.

    Passed per-call (never mutating the shared model's generation_config) so the
    warm pipeline stays safe for the unchanged on-demand transcription path.
    """
    return {
        "no_repeat_ngram_size": _NO_REPEAT_NGRAM_SIZE,
        "repetition_penalty": _REPETITION_PENALTY,
        "temperature": _TEMPERATURE_FALLBACK,
        "compression_ratio_threshold": _COMPRESSION_RATIO_THRESHOLD,
        "logprob_threshold": _LOGPROB_THRESHOLD,
        "no_speech_threshold": _NO_SPEECH_THRESHOLD,
        "condition_on_prev_tokens": False,
    }


def faster_whisper_kwargs() -> Dict[str, Any]:
    """Extra kwargs for ``faster_whisper.WhisperModel.transcribe``.

    Merged with the caller's base kwargs (language, beam_size, vad_filter). Note
    faster-whisper spells the logprob threshold ``log_prob_threshold`` and uses a
    list (not tuple) for the temperature fallback.
    """
    return {
        "condition_on_previous_text": False,
        "repetition_penalty": _REPETITION_PENALTY,
        "no_repeat_ngram_size": _NO_REPEAT_NGRAM_SIZE,
        "compression_ratio_threshold": _COMPRESSION_RATIO_THRESHOLD,
        "log_prob_threshold": _LOGPROB_THRESHOLD,
        "no_speech_threshold": _NO_SPEECH_THRESHOLD,
        "temperature": list(_TEMPERATURE_FALLBACK),
    }
