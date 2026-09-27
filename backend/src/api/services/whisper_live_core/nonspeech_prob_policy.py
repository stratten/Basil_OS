"""Per-source non-speech probability threshold policy for the live decoder.

The SimulStreaming decoder stops a new segment when Whisper's ``no_speech``
probability at the start-of-transcript position exceeds this threshold
(see ``AlignAtt.infer`` / ``self.nonspeech_prob``). It is the decode-stage
companion to the VAD *input* gate in ``vad_threshold_policy``.

This is exposed as a per-source knob so the threshold can be tuned for produced
(system) audio independently of the microphone path WITHOUT mutating the
``AlignAttConfig`` that is shared across pooled model instances. It currently
returns the decoder default (parity) for every source: lowering it for system
audio would make the gate more aggressive and risk re-dropping the borderline
produced speech the lenient VAD was specifically added to keep, so any
behavior-changing value should be chosen from evidence rather than assumed.
The actual degeneration-loop suppression is handled separately, on decoder
output, by ``repetition_degeneration_guard``.

Pure function, no torch/model imports, so the decision is unit-testable.
"""
from __future__ import annotations

from typing import Optional

# Matches ``AlignAttConfig.nonspeech_prob`` and the historical behavior (the gate
# threshold applied to every source before this knob existed).
DEFAULT_NONSPEECH_PROB = 0.5


def nonspeech_prob_for_source(source: Optional[str]) -> float:
    """Return the ``no_speech`` gate threshold for the given audio source name.

    Returns :data:`DEFAULT_NONSPEECH_PROB` for every source today (parity with
    prior behavior). The signature is source-aware so the threshold can be split
    per source later without touching call sites.
    """
    return DEFAULT_NONSPEECH_PROB
