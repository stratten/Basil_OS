"""Audio preparation helpers for OpenAI transcription requests."""

from __future__ import annotations

import io
import logging
import wave
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_FORMATS = {
    ".flac", ".m4a", ".mp3", ".mp4", ".mpeg",
    ".mpga", ".oga", ".ogg", ".wav", ".webm",
}

WHISPER_FORMATTING_PROMPT = (
    "Hello. Here is a properly formatted sentence, with punctuation and "
    "capitalization. Does that look right? Yes, it does."
)

SILENCE_PAD_MS = 400


def is_raw_pcm(data: bytes) -> bool:
    """Detect whether *data* is headerless raw PCM rather than an encoded file."""
    if len(data) < 12:
        return True
    header = data[:4]
    return header not in (
        b"RIFF",
        b"fLaC",
        b"OggS",
        b"ID3 ",
        b"\xff\xfb",
        b"\xff\xf3",
        b"\xff\xf2",
    )


def raw_pcm_to_wav(
    pcm_bytes: bytes,
    sample_rate: int = 16000,
    pad_ms: int = 0,
) -> bytes:
    """Wrap raw Float32 PCM bytes in a valid WAV container (16-bit PCM)."""
    audio = np.frombuffer(pcm_bytes, dtype=np.float32)
    audio = np.clip(audio, -1.0, 1.0)
    pcm16 = (audio * 32767).astype(np.int16)

    if pad_ms > 0:
        pad_samples = int(sample_rate * pad_ms / 1000)
        silence = np.zeros(pad_samples, dtype=np.int16)
        pcm16 = np.concatenate([silence, pcm16, silence])

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


def formatting_prompt(api_model_name: Optional[str]) -> Optional[str]:
    """Return a stylistic prompt for models that need a formatting nudge."""
    if (api_model_name or "").startswith("whisper"):
        return WHISPER_FORMATTING_PROMPT
    return None


def needs_silence_padding(api_model_name: Optional[str]) -> bool:
    """Return True when the active model is known to clip utterance edges."""
    return (api_model_name or "").startswith("gpt-4o")


def prepare_audio(
    audio_data: bytes,
    context_info: Optional[Dict[str, Any]] = None,
    *,
    api_model_name: Optional[str],
    silence_pad_ms: int = SILENCE_PAD_MS,
    log: Optional[logging.Logger] = None,
) -> tuple[bytes, str]:
    """Convert raw PCM to WAV if needed, return ``(audio_bytes, suffix)``."""
    active_logger = log or logger
    if is_raw_pcm(audio_data):
        pad_ms = silence_pad_ms if needs_silence_padding(api_model_name) else 0
        wav_bytes = raw_pcm_to_wav(audio_data, pad_ms=pad_ms)
        if pad_ms > 0:
            active_logger.info(
                "Converted %s raw PCM bytes -> %s byte WAV "
                "(padded with %s ms silence on each end for %s)",
                len(audio_data),
                len(wav_bytes),
                pad_ms,
                api_model_name,
            )
        else:
            active_logger.info(
                "Converted %s raw PCM bytes -> %s byte WAV",
                len(audio_data),
                len(wav_bytes),
            )
        return wav_bytes, ".wav"

    suffix = ".wav"
    if context_info and context_info.get("original_filename"):
        orig_ext = Path(context_info["original_filename"]).suffix.lower()
        if orig_ext in SUPPORTED_AUDIO_FORMATS:
            suffix = orig_ext
    return audio_data, suffix
