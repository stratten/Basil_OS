"""Tier 2 provider for users without a streaming key: overlapping audio windows sent through the Basil account proxy."""

from __future__ import annotations

import asyncio
import io
import logging
import re
import wave
from array import array
from typing import AsyncIterator, Awaitable, Callable, Optional

from .models import (
    CONNECTION_BASIL_ACCOUNT,
    EVENT_FINAL,
    PCM_BYTES_PER_SAMPLE,
    PCM_SAMPLE_RATE,
    AsrEvent,
    CloudAsrError,
)

logger = logging.getLogger(__name__)

CHUNKED_REGISTRY_MODEL_ID = "openai-gpt-4o-mini-transcribe"
WINDOW_SECONDS = 6.0
OVERLAP_SECONDS = 1.0
MIN_FINAL_WINDOW_SECONDS = 1.0
MAX_OVERLAP_WORDS = 12
MAX_PENDING_WINDOWS = 5
SILENCE_PEAK_THRESHOLD = 300
CHUNK_CLOSE_DRAIN_SECONDS = 20.0
MAX_ERROR_TEXT_CHARS = 200

TranscribeWindow = Callable[[bytes], Awaitable[str]]
_END = object()
_WORD_STRIP = re.compile(r"[^\w']+", re.UNICODE)


def normalized_word(word: str) -> str:
    return _WORD_STRIP.sub("", word.lower())


def trim_overlap(previous_text: str, new_text: str, max_words: int = MAX_OVERLAP_WORDS) -> str:
    """Drop the leading words of ``new_text`` that repeat the trailing words of ``previous_text``."""
    previous_words = [normalized_word(word) for word in previous_text.split()]
    new_words = new_text.split()
    new_normalized = [normalized_word(word) for word in new_words]
    for size in range(min(max_words, len(previous_words), len(new_words)), 0, -1):
        if previous_words[-size:] == new_normalized[:size] and any(new_normalized[:size]):
            return " ".join(new_words[size:])
    return " ".join(new_words)


def pcm_to_wav(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(PCM_BYTES_PER_SAMPLE)
        writer.setframerate(PCM_SAMPLE_RATE)
        writer.writeframes(pcm)
    return buffer.getvalue()


def peak_amplitude(pcm: bytes) -> int:
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % PCM_BYTES_PER_SAMPLE)])
    return max((abs(sample) for sample in samples), default=0)


async def transcribe_through_proxy(wav_bytes: bytes) -> str:
    """Send one WAV window through the Auth Service using the registered mini transcription model's identifiers."""
    from api.core.models.models_registry.cloud_transcription_registry import CLOUD_TRANSCRIPTION_MODELS
    from api.services.transcription.backends.openai_whisper_api.audio_preparation import formatting_prompt
    from api.services.transcription.backends.openai_whisper_api.auth_proxy_client import AuthProxyTranscriptionClient

    config = CLOUD_TRANSCRIPTION_MODELS.get(CHUNKED_REGISTRY_MODEL_ID)
    if config is None:
        raise CloudAsrError("The Basil account transcription model is not available.")
    client = AuthProxyTranscriptionClient(
        api_model_name=config.get("api_model_name"),
        openrouter_id=config.get("openrouter_id"),
    )
    return await client.transcribe_text(
        wav_bytes, ".wav", None, formatting_prompt=formatting_prompt(config.get("api_model_name"))
    )


class ChunkedProxyProvider:
    name = CONNECTION_BASIL_ACCOUNT

    def __init__(
        self,
        *,
        transcribe: Optional[TranscribeWindow] = None,
        window_seconds: float = WINDOW_SECONDS,
        overlap_seconds: float = OVERLAP_SECONDS,
        close_drain_seconds: float = CHUNK_CLOSE_DRAIN_SECONDS,
    ) -> None:
        self._transcribe = transcribe or transcribe_through_proxy
        self._window_bytes = int(window_seconds * PCM_SAMPLE_RATE) * PCM_BYTES_PER_SAMPLE
        self._overlap_bytes = int(overlap_seconds * PCM_SAMPLE_RATE) * PCM_BYTES_PER_SAMPLE
        self._min_final_bytes = int(MIN_FINAL_WINDOW_SECONDS * PCM_SAMPLE_RATE) * PCM_BYTES_PER_SAMPLE
        self._close_drain_seconds = close_drain_seconds
        self._fresh = bytearray()
        self._tail = b""
        self._fresh_start_bytes = 0
        self._previous_text = ""
        self._windows: asyncio.Queue = asyncio.Queue()
        self._events: asyncio.Queue = asyncio.Queue()
        self._worker: Optional[asyncio.Task] = None
        self._failure: Optional[CloudAsrError] = None

    async def open(self) -> None:
        self._worker = asyncio.create_task(self._work())

    async def send_audio(self, pcm: bytes) -> None:
        if self._failure is not None:
            raise self._failure
        self._fresh.extend(pcm)
        while len(self._fresh) >= self._window_bytes:
            if self._windows.qsize() >= MAX_PENDING_WINDOWS:
                self._failure = CloudAsrError("Cloud transcription is falling behind.")
                raise self._failure
            self._submit(bytes(self._fresh[: self._window_bytes]))
            del self._fresh[: self._window_bytes]

    def _submit(self, fresh: bytes) -> None:
        start_bytes = self._fresh_start_bytes
        self._windows.put_nowait((self._tail + fresh, start_bytes, len(fresh)))
        self._tail = fresh[-self._overlap_bytes :] if self._overlap_bytes else b""
        self._fresh_start_bytes += len(fresh)

    async def events(self) -> AsyncIterator[AsrEvent]:
        while True:
            item = await self._events.get()
            if item is _END:
                break
            yield item
        if self._failure is not None:
            raise self._failure

    async def close(self) -> None:
        if len(self._fresh) >= self._min_final_bytes and self._failure is None:
            self._submit(bytes(self._fresh))
        self._fresh.clear()
        self._windows.put_nowait(_END)
        if self._worker is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._worker), timeout=self._close_drain_seconds)
            except asyncio.TimeoutError:
                self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        self._events.put_nowait(_END)

    async def _work(self) -> None:
        try:
            while True:
                window = await self._windows.get()
                if window is _END:
                    return
                audio, start_bytes, fresh_bytes = window
                await self._transcribe_window(audio, start_bytes, fresh_bytes)
        except asyncio.CancelledError:
            raise
        except CloudAsrError as error:
            self._failure = error
        except Exception as error:
            self._failure = CloudAsrError(str(error)[:MAX_ERROR_TEXT_CHARS] or "Cloud transcription failed.")
            logger.warning("Chunked cloud transcription failed: %s", type(error).__name__)
        finally:
            self._events.put_nowait(_END)

    async def _transcribe_window(self, audio: bytes, start_bytes: int, fresh_bytes: int) -> None:
        if peak_amplitude(audio) < SILENCE_PEAK_THRESHOLD:
            self._previous_text = ""
            return
        wav_bytes = pcm_to_wav(audio)
        try:
            text = await self._transcribe(wav_bytes)
        except ConnectionError:
            await asyncio.sleep(1.0)
            text = await self._transcribe(wav_bytes)
        raw_text = (text or "").strip()
        text = trim_overlap(self._previous_text, raw_text)
        self._previous_text = raw_text
        if not text:
            return
        scale = float(PCM_BYTES_PER_SAMPLE * PCM_SAMPLE_RATE)
        self._events.put_nowait(
            AsrEvent(EVENT_FINAL, text, start_bytes / scale, (start_bytes + fresh_bytes) / scale, True)
        )
