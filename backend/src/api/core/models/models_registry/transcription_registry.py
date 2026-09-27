"""
Transcription Models Registry.

Contains Whisper and Distil-Whisper transcription models.
"""

from typing import Any, Dict

TRANSCRIPTION_PROVIDER_DISPLAY_ORDER: Dict[str, int] = {
    "nvidia_parakeet": 1,
    "openai_whisper": 2,
    "distil_whisper": 3,
}

TRANSCRIPTION_MODELS: Dict[str, Any] = {
    # NVIDIA Parakeet TDT 0.6B v2 - English-only, leader on Open ASR Leaderboard.
    # Served via ONNX Runtime (no NeMo dependency); uses the pre-exported
    # community bundle at istupakov/parakeet-tdt-0.6b-v2-onnx, which ships
    # BOTH a quantized (int8) and a full-precision (fp32) variant of the
    # encoder + decoder_joint ONNX files in the same repo. We expose them
    # as two distinct registry entries so users can pick their tradeoff
    # explicitly:
    #
    #   * "Quantized" (int8)         -- ~640 MB on disk, faster CPU
    #     inference, slightly lower accuracy. Recommended default.
    #   * "Full Precision" (fp32)    -- ~2.4 GB on disk, full model
    #     accuracy, more RAM at runtime.
    #
    # Both entries share `repo_url` and `handler`; the new `precision`
    # field (added to `TranscriptionConfig` in schema.py) drives:
    #   1. `model_downloader.py`'s per-file allow-list (so we never
    #      silently pull both variants or miss the fp32 .onnx.data
    #      sidecar -- both prior bugs traced to a broad `*.onnx` glob).
    #   2. `ParakeetModelManager`'s encoder/decoder filename selection
    #      at session-load time.
    # Distinct `on_disk_name` directories so a user can install both
    # without a collision and removing one doesn't affect the other.
    # Routed to `ParakeetTranscriptionService` by the `parakeet` handler.
    "NVIDIA-parakeet-tdt-0.6b-v2-quantized": {
        "handler": "parakeet",
        "chunk_seconds": 30.0,
        "location": "local",
        "provider": "nvidia_parakeet",
        "display_name": "Parakeet TDT 0.6B v2 — Quantized (NVIDIA)",
        "capabilities": ["transcription"],
        "features": ["gpu_acceleration"],
        "repo_url": "https://huggingface.co/istupakov/parakeet-tdt-0.6b-v2-onnx",
        "revision": "main",
        "on_disk_name": "parakeet-tdt-0.6b-v2-onnx-quantized",
        "precision": "int8",
        # Sum of int8-only files in the repo: encoder-model.int8.onnx
        # (~622 MB) + decoder_joint-model.int8.onnx (~8.6 MB) +
        # nemo128.onnx preprocessor (~133 KB) + vocab.txt + small
        # configs. Verified against the HuggingFace API tree listing.
        "size": "640MB",
        "recommended_ram": "2GB",
        "speed_rating": 9,
        "accuracy_rating": 8,
    },
    "NVIDIA-parakeet-tdt-0.6b-v2-full-precision": {
        "handler": "parakeet",
        "chunk_seconds": 30.0,
        "location": "local",
        "provider": "nvidia_parakeet",
        "display_name": "Parakeet TDT 0.6B v2 — Full Precision (NVIDIA)",
        "capabilities": ["transcription"],
        "features": ["gpu_acceleration"],
        "repo_url": "https://huggingface.co/istupakov/parakeet-tdt-0.6b-v2-onnx",
        "revision": "main",
        "on_disk_name": "parakeet-tdt-0.6b-v2-onnx-full-precision",
        "precision": "fp32",
        # Sum of fp32-only files: encoder-model.onnx graph (~40 MB) +
        # encoder-model.onnx.data external-weights sidecar (~2.27 GB,
        # required by ONNX Runtime since the encoder exceeds the 2 GB
        # protobuf limit) + decoder_joint-model.onnx (~34 MB) +
        # nemo128.onnx + vocab.txt + small configs.
        "size": "2.4GB",
        "recommended_ram": "6GB",
        "speed_rating": 7,
        "accuracy_rating": 9,
    },
    # NVIDIA Parakeet TDT 0.6B v3 - Multilingual successor to v2
    # (25 European languages: en, es, fr, de, bg, hr, cs, da, nl, et,
    # fi, el, hu, it, lv, lt, mt, pl, pt, ro, sk, sl, sv, ru, uk).
    # Same nemo-conformer-tdt architecture and same `istupakov` ONNX
    # bundle layout as v2 (encoder-model[.int8].onnx,
    # encoder-model.onnx.data fp32 sidecar, decoder_joint-model[.int8]
    # .onnx, nemo128.onnx, vocab.txt, config.json), so the per-precision
    # allow-list in `model_downloader.py`, the encoder/decoder filename
    # selection in `ParakeetModelManager`, and the TDT greedy decoder in
    # `parakeet_decoder.py` all work unchanged -- only the registry
    # entries differ. The v3 bundle ships no `model_config.yaml`, so
    # `ParakeetModelManager._load_durations` falls back to the documented
    # TDT support set [0, 1, 2, 3, 4]. v3 keeps v2 alongside it because
    # v2 is English-only-trained and may have a small WER edge on pure
    # English audio at a slightly smaller download.
    "NVIDIA-parakeet-tdt-0.6b-v3-quantized": {
        "handler": "parakeet",
        "chunk_seconds": 30.0,
        "location": "local",
        "provider": "nvidia_parakeet",
        "display_name": "Parakeet TDT 0.6B v3 — Quantized (NVIDIA, multilingual)",
        "capabilities": ["transcription"],
        "features": ["gpu_acceleration"],
        "repo_url": "https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx",
        "revision": "main",
        "on_disk_name": "parakeet-tdt-0.6b-v3-onnx-quantized",
        "precision": "int8",
        # Sum of int8-only files in the v3 repo: encoder-model.int8.onnx
        # (~652 MB) + decoder_joint-model.int8.onnx (~18 MB) +
        # nemo128.onnx preprocessor (~140 KB) + vocab.txt (~93 KB) +
        # small configs. Verified against the HuggingFace API tree
        # listing.
        "size": "670MB",
        "recommended_ram": "2GB",
        "speed_rating": 9,
        "accuracy_rating": 8,
        "recommended": True,
        "recommended_for_onboarding": True,
        "recommended_reason": "Smallest download, lowest RAM, multilingual, top-of-leaderboard accuracy.",
    },
    "NVIDIA-parakeet-tdt-0.6b-v3-full-precision": {
        "handler": "parakeet",
        "chunk_seconds": 30.0,
        "location": "local",
        "provider": "nvidia_parakeet",
        "display_name": "Parakeet TDT 0.6B v3 — Full Precision (NVIDIA, multilingual)",
        "capabilities": ["transcription"],
        "features": ["gpu_acceleration"],
        "repo_url": "https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx",
        "revision": "main",
        "on_disk_name": "parakeet-tdt-0.6b-v3-onnx-full-precision",
        "precision": "fp32",
        # Sum of fp32-only files: encoder-model.onnx graph (~42 MB) +
        # encoder-model.onnx.data external-weights sidecar (~2.43 GB,
        # required by ONNX Runtime since the encoder exceeds the 2 GB
        # protobuf limit) + decoder_joint-model.onnx (~70 MB) +
        # nemo128.onnx + vocab.txt + small configs.
        "size": "2.5GB",
        "recommended_ram": "6GB",
        "speed_rating": 7,
        "accuracy_rating": 9,
    },
    # OpenAI Whisper - Tiny
    "OpenAI-whisper-tiny": {
        "handler": "whisper",
        "chunk_seconds": 30.0,
        "location": "local",
        "provider": "openai_whisper",
        "display_name": "Whisper Tiny",
        "capabilities": ["transcription"],
        "features": ["gpu_acceleration"],
        "repo_url": "https://huggingface.co/openai/whisper-tiny",
        "revision": "main",
        "on_disk_name": "whisper-tiny",
        "size": "151MB",
        "recommended_ram": "2GB",
        "speed_rating": 10,
        "accuracy_rating": 4,
    },
    "OpenAI-whisper-tiny.en": {
        "handler": "whisper",
        "chunk_seconds": 30.0,
        "location": "local",
        "provider": "openai_whisper",
        "display_name": "Whisper Tiny (English)",
        "capabilities": ["transcription"],
        "features": ["gpu_acceleration"],
        "repo_url": "https://huggingface.co/openai/whisper-tiny.en",
        "revision": "main",
        "on_disk_name": "whisper-tiny.en",
        "size": "151MB",
        "recommended_ram": "2GB",
        "speed_rating": 10,
        "accuracy_rating": 5,
    },
    # OpenAI Whisper - Base
    "OpenAI-whisper": {
        "handler": "whisper",
        "chunk_seconds": 30.0,
        "location": "local",
        "provider": "openai_whisper",
        "display_name": "Whisper Base",
        "capabilities": ["transcription"],
        "features": ["gpu_acceleration"],
        "repo_url": "https://huggingface.co/openai/whisper-base",
        "revision": "main",
        "on_disk_name": "whisper-base",
        "size": "290MB",
        "recommended_ram": "2GB",
        "speed_rating": 7,
        "accuracy_rating": 6,
    },
    "OpenAI-whisper-base.en": {
        "handler": "whisper",
        "chunk_seconds": 30.0,
        "location": "local",
        "provider": "openai_whisper",
        "display_name": "Whisper Base (English)",
        "capabilities": ["transcription"],
        "features": ["gpu_acceleration"],
        "repo_url": "https://huggingface.co/openai/whisper-base.en",
        "revision": "main",
        "on_disk_name": "whisper-base.en",
        "size": "290MB",
        "recommended_ram": "2GB",
        "speed_rating": 7,
        "accuracy_rating": 7,
    },
    # OpenAI Whisper - Small
    "OpenAI-whisper-small": {
        "handler": "whisper",
        "chunk_seconds": 30.0,
        "location": "local",
        "provider": "openai_whisper",
        "display_name": "Whisper Small",
        "capabilities": ["transcription"],
        "features": ["gpu_acceleration"],
        "repo_url": "https://huggingface.co/openai/whisper-small",
        "revision": "main",
        "on_disk_name": "whisper-small",
        "size": "967MB",
        "recommended_ram": "4GB",
        "speed_rating": 4,
        "accuracy_rating": 7,
    },
    "OpenAI-whisper-small.en": {
        "handler": "whisper",
        "chunk_seconds": 30.0,
        "location": "local",
        "provider": "openai_whisper",
        "display_name": "Whisper Small (English)",
        "capabilities": ["transcription"],
        "features": ["gpu_acceleration"],
        "repo_url": "https://huggingface.co/openai/whisper-small.en",
        "revision": "main",
        "on_disk_name": "whisper-small.en",
        "size": "967MB",
        "recommended_ram": "4GB",
        "speed_rating": 4,
        "accuracy_rating": 8,
    },
    # NOTE: Whisper Medium and Medium (English) were removed from the
    # registry. OpenAI publishes those repos at fp32 only, so the
    # actual download is ~3.06 GB each -- larger than the
    # 1.6 GB Whisper Large V3 Turbo, which dominates them on every
    # axis (multilingual, faster, comparable or better accuracy).
    # Without an existing fp32 -> fp16 conversion path in
    # `model_downloader.py`, there's no infrastructure-friendly way
    # to get Medium under Turbo's footprint, so the entries are
    # removed rather than offered as a worse-than-Turbo option.
    # OpenAI Whisper - Large
    # NOTE: Whisper Large V2 was removed from the registry. The
    # upstream repo publishes only a single fp32 `model.safetensors`
    # (~6.17 GB) on HF -- no fp16 variant -- and Large V2 is
    # Pareto-dominated by both Whisper Large V3 (smaller at ~3.1 GB
    # post-fp32-ignore-fix, higher accuracy, same speed) and Whisper
    # Large V3 Turbo (much smaller at ~1.6 GB, much faster, same
    # accuracy). Without an existing fp32 -> fp16 conversion path in
    # `model_downloader.py`, Large V2 has no use case that the V3
    # entries don't cover better, so the entry is removed rather
    # than offered as a strictly worse option.
    "OpenAI-whisper-large-v3": {
        "handler": "whisper",
        "chunk_seconds": 30.0,
        "location": "local",
        "provider": "openai_whisper",
        "display_name": "Whisper Large V3",
        "capabilities": ["transcription"],
        "features": ["gpu_acceleration"],
        "repo_url": "https://huggingface.co/openai/whisper-large-v3",
        "revision": "main",
        "on_disk_name": "whisper-large-v3",
        "size": "3.1GB",
        "recommended_ram": "16GB",
        "speed_rating": 1,
        "accuracy_rating": 10,
    },
    "OpenAI-whisper-large-v3-turbo": {
        "handler": "whisper",
        "chunk_seconds": 30.0,
        "location": "local",
        "provider": "openai_whisper",
        "display_name": "Whisper Large V3 Turbo",
        "capabilities": ["transcription"],
        "features": ["gpu_acceleration"],
        "repo_url": "https://huggingface.co/openai/whisper-large-v3-turbo",
        "revision": "main",
        "on_disk_name": "whisper-large-v3-turbo",
        "size": "1.6GB",
        "recommended_ram": "8GB",
        "speed_rating": 8,
        "accuracy_rating": 9,
    },
    # Distil-Whisper
    # NOTE on size: this repo publishes only fp32 weights (no fp16
    # variant on HF), so the download is ~3.03 GB even though the
    # in-memory fp16 footprint would be ~1.51 GB.
    "DistilWhisper-distil-large-v3.5": {
        "handler": "whisper",
        "chunk_seconds": 30.0,
        "location": "local",
        "provider": "distil_whisper",
        "display_name": "Distil-Whisper Large V3.5",
        "capabilities": ["transcription"],
        "features": ["gpu_acceleration"],
        "repo_url": "https://huggingface.co/distil-whisper/distil-large-v3.5",
        "revision": "main",
        "on_disk_name": "distil-large-v3.5",
        "size": "3.0GB",
        "recommended_ram": "8GB",
        "speed_rating": 9,
        "accuracy_rating": 9,
    },
    "DistilWhisper-distil-large-v3": {
        "handler": "whisper",
        "chunk_seconds": 30.0,
        "location": "local",
        "provider": "distil_whisper",
        "display_name": "Distil-Whisper Large V3",
        "capabilities": ["transcription"],
        "features": ["gpu_acceleration"],
        "repo_url": "https://huggingface.co/distil-whisper/distil-large-v3",
        "revision": "main",
        "on_disk_name": "distil-large-v3",
        "size": "1.5GB",
        "recommended_ram": "8GB",
        "speed_rating": 8,
        "accuracy_rating": 9,
    },
}
