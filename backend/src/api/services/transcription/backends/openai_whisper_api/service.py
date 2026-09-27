"""Public OpenAI Whisper API transcription service."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any, Awaitable, Callable, Dict, List, Optional

from api.services.auth_service_client import should_route_through_auth_service

from ...base_transcription_service import BaseTranscriptionService
from ...processing import transcription_lifecycle
from .audio_preparation import (
    SILENCE_PAD_MS,
    formatting_prompt,
    prepare_audio,
)
from .auth_proxy_client import AuthProxyTranscriptionClient
from .degeneration_guard import is_degenerate_segment_run
from .direct_client import DirectOpenAITranscriptionClient
from .leading_silence_trim import trim_leading_silence_wav
from .request_policy import estimate_wav_duration_seconds
from .upload_chunking import (
    OPENAI_AUDIO_UPLOAD_BUDGET_BYTES,
    SINGLE_REQUEST_MAX_BYTES,
    WAV_CHUNK_HEADER_MARGIN_BYTES,
    is_wav_file_bytes,
    offset_timestamped_segments,
    split_wav_for_upload_budget,
)

logger = logging.getLogger(__name__)


def _format_clock(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


class OpenAIWhisperAPITranscriptionService(BaseTranscriptionService):
    """Transcription service using the OpenAI Whisper API."""

    _SILENCE_PAD_MS = SILENCE_PAD_MS
    _OPENAI_AUDIO_UPLOAD_BUDGET_BYTES = OPENAI_AUDIO_UPLOAD_BUDGET_BYTES
    _SINGLE_REQUEST_MAX_BYTES = SINGLE_REQUEST_MAX_BYTES
    _WAV_CHUNK_HEADER_MARGIN_BYTES = WAV_CHUNK_HEADER_MARGIN_BYTES

    def __init__(self, model_id: str = "openai-whisper-1"):
        super().__init__()
        self._model_id = model_id
        self._api_model_name: Optional[str] = None
        self._openrouter_id: Optional[str] = None
        self._direct_client: Optional[DirectOpenAITranscriptionClient] = None

    def load_model(self) -> None:
        """Resolve the API model name from the registry and mark as ready."""
        try:
            from api.core.models.models_registry import get_model

            cfg = get_model(self._model_id)
            if cfg:
                self._api_model_name = cfg.get("api_model_name", "whisper-1")
                self._openrouter_id = cfg.get("openrouter_id")
            else:
                self._api_model_name = "whisper-1"
                logger.warning(
                    "Model %s not found in registry, defaulting to whisper-1",
                    self._model_id,
                )
        except Exception:
            self._api_model_name = "whisper-1"

        self._direct_client = DirectOpenAITranscriptionClient(self._api_model_name)
        self._model_loaded = True
        logger.info("OpenAI Whisper API service ready (model: %s)", self._api_model_name)

    def unload_model(self) -> None:
        """No local resources to release."""
        if self._direct_client is not None:
            self._direct_client.unload()
        self._direct_client = None
        self._model_loaded = False
        logger.info("OpenAI Whisper API service unloaded")

    def _get_direct_client(self) -> DirectOpenAITranscriptionClient:
        if (
            self._direct_client is None
            or self._direct_client.api_model_name != self._api_model_name
        ):
            self._direct_client = DirectOpenAITranscriptionClient(self._api_model_name)
        return self._direct_client

    def _prepare_audio(
        self,
        audio_data: bytes,
        context_info: Optional[Dict[str, Any]] = None,
    ) -> tuple[bytes, str]:
        return prepare_audio(
            audio_data,
            context_info,
            api_model_name=self._api_model_name,
            silence_pad_ms=self._SILENCE_PAD_MS,
            log=logger,
        )

    async def _transcribe_via_auth_proxy(
        self, wav_bytes: bytes, suffix: str, language: Optional[str] = None
    ) -> str:
        client = AuthProxyTranscriptionClient(
            api_model_name=self._api_model_name,
            openrouter_id=self._openrouter_id,
        )
        return await client.transcribe_text(
            wav_bytes,
            suffix,
            language,
            formatting_prompt=formatting_prompt(self._api_model_name),
        )

    async def _transcribe_direct(
        self, wav_bytes: bytes, suffix: str, language: Optional[str] = None
    ) -> str:
        return await self._get_direct_client().transcribe_text(
            wav_bytes,
            suffix,
            language,
            formatting_prompt=formatting_prompt(self._api_model_name),
        )

    async def _transcribe_direct_segments(
        self, wav_bytes: bytes, suffix: str, language: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        # Do NOT send the formatting prompt on the timestamped-segment
        # (retranscription) path. Whisper conditions on `prompt` and emits it
        # verbatim on low-confidence/silent audio, which corrupted long meeting
        # re-transcriptions with the prompt's text. Formatting matters far less
        # than correctness here; the plain-text on-demand path keeps the prompt.
        return await self._get_direct_client().transcribe_segments(
            wav_bytes,
            suffix,
            language,
            formatting_prompt=None,
        )

    async def transcribe_segments_from_file(
        self,
        audio_path: Path,
        language: Optional[str] = None,
        progress_callback: Optional[Callable[[float, float, str, float], Awaitable[None]]] = None,
    ) -> List[Dict[str, Any]]:
        """Transcribe a meeting audio file and return timestamped segments."""
        if not self._model_loaded:
            self.load_model()

        if should_route_through_auth_service():
            raise ValueError(
                "Timestamped API retranscription is not supported through Basil Cloud yet. "
                "Use your own OpenAI API key or a local transcription model for meeting retranscription."
            )

        audio_bytes = audio_path.read_bytes()
        wav_bytes, suffix = self._prepare_audio(
            audio_bytes,
            {"original_filename": audio_path.name},
        )
        if len(wav_bytes) > self._SINGLE_REQUEST_MAX_BYTES:
            return await self._transcribe_chunked_direct_segments(
                wav_bytes,
                suffix,
                language,
                progress_callback=progress_callback,
            )
        return await self._transcribe_single_direct_segments_trimmed(
            wav_bytes,
            suffix,
            language,
        )

    async def _transcribe_single_direct_segments_trimmed(
        self, wav_bytes: bytes, suffix: str, language: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Single-request retranscription with leading-silence trim + backstop.

        whisper-1 degenerates into a non-speech "." loop when the audio opens on
        a long stretch of dead air (the normal start of a meeting recording).
        We strip that leading silence before upload and re-apply the exact
        trimmed duration as a timeline offset. Non-WAV audio cannot be trimmed
        safely, so it passes through unchanged.
        """
        if suffix != ".wav" or not is_wav_file_bytes(wav_bytes):
            return await self._transcribe_direct_segments(wav_bytes, suffix, language)

        trimmed_wav, trimmed_seconds = trim_leading_silence_wav(wav_bytes)
        segments = await self._transcribe_direct_segments(trimmed_wav, ".wav", language)

        sent_duration = estimate_wav_duration_seconds(trimmed_wav)
        if sent_duration is None:
            sent_duration = max(
                (float(seg.get("end", 0.0)) for seg in segments),
                default=0.0,
            )
        if is_degenerate_segment_run(segments, chunk_duration_seconds=sent_duration):
            logger.warning(
                "Dropping degenerate OpenAI transcription result: %s segments over "
                "%.2fs of audio looked like a non-speech loop.",
                len(segments),
                sent_duration,
            )
            return []

        total_duration = estimate_wav_duration_seconds(wav_bytes)
        if trimmed_seconds <= 0.0 and total_duration is None:
            # No trim and no reliable clamp: preserve prior behavior exactly.
            return segments

        chunk_end = (
            total_duration
            if total_duration is not None
            else trimmed_seconds
            + max((float(seg.get("end", 0.0)) for seg in segments), default=0.0)
        )
        return offset_timestamped_segments(
            segments,
            offset_seconds=trimmed_seconds,
            chunk_end_seconds=chunk_end,
        )

    async def _transcribe_chunked_direct_segments(
        self,
        wav_bytes: bytes,
        suffix: str,
        language: Optional[str] = None,
        progress_callback: Optional[Callable[[float, float, str, float], Awaitable[None]]] = None,
    ) -> List[Dict[str, Any]]:
        """Transcribe oversized meeting audio in upload-budgeted chunks."""
        if suffix != ".wav" or not is_wav_file_bytes(wav_bytes):
            raise ValueError(
                "Meeting audio is too large for the selected API transcription model "
                f"({len(wav_bytes)} bytes exceeds the "
                f"{self._OPENAI_AUDIO_UPLOAD_BUDGET_BYTES} byte safety budget), "
                "and only WAV meeting audio can be chunked safely. Use a local "
                "transcription model or retry with WAV audio."
            )

        chunks = split_wav_for_upload_budget(
            wav_bytes,
            upload_budget_bytes=self._OPENAI_AUDIO_UPLOAD_BUDGET_BYTES,
            header_margin_bytes=self._WAV_CHUNK_HEADER_MARGIN_BYTES,
        )
        if not chunks:
            return []

        logger.info(
            "OpenAI API meeting re-transcription chunking: total_bytes=%s, chunks=%s, budget=%s",
            len(wav_bytes),
            len(chunks),
            self._OPENAI_AUDIO_UPLOAD_BUDGET_BYTES,
        )
        started_at = monotonic()
        latest_eta_seconds = 0.0
        completed_audio_seconds = 0.0
        total_chunk_audio_seconds = sum(
            max(0.0, chunk_end - chunk_start)
            for _, chunk_start, chunk_end in chunks
        )
        total_chunk_bytes = sum(len(chunk_bytes) for chunk_bytes, _, _ in chunks)
        if progress_callback is not None:
            await progress_callback(
                0.20,
                0.0,
                f"Preparing {len(chunks)} audio segments...",
                latest_eta_seconds,
            )

        merged_segments: List[Dict[str, Any]] = []
        for index, (chunk_bytes, chunk_start, chunk_end) in enumerate(chunks, start=1):
            chunk_progress_start = 0.20 + (0.75 * ((index - 1) / len(chunks)))
            chunk_progress_end = 0.20 + (0.75 * (index / len(chunks)))
            chunk_audio_seconds = max(0.0, chunk_end - chunk_start)
            chunk_started_at = monotonic()
            if progress_callback is not None:
                await progress_callback(
                    chunk_progress_start,
                    chunk_start,
                    (
                        f"Transcribing audio segment {index} of {len(chunks)} "
                        f"({_format_clock(chunk_start)}-{_format_clock(chunk_end)})..."
                    ),
                    latest_eta_seconds,
                )

            logger.info(
                "Sending OpenAI API re-transcription chunk %s/%s: %.2f-%.2fs, %s bytes",
                index,
                len(chunks),
                chunk_start,
                chunk_end,
                len(chunk_bytes),
            )
            trimmed_chunk, trimmed_seconds = trim_leading_silence_wav(chunk_bytes)
            sent_duration = max(0.0, (chunk_end - chunk_start) - trimmed_seconds)
            chunk_segments = await self._transcribe_direct_segments(trimmed_chunk, ".wav", language)
            if is_degenerate_segment_run(chunk_segments, chunk_duration_seconds=sent_duration):
                logger.warning(
                    "Dropping degenerate OpenAI re-transcription chunk %s/%s "
                    "(%.2f-%.2fs): %s segments looked like a non-speech loop; "
                    "leaving a gap instead of writing repeated filler.",
                    index,
                    len(chunks),
                    chunk_start,
                    chunk_end,
                    len(chunk_segments),
                )
            else:
                merged_segments.extend(
                    offset_timestamped_segments(
                        chunk_segments,
                        offset_seconds=chunk_start + trimmed_seconds,
                        chunk_end_seconds=chunk_end,
                    )
                )
            completed_audio_seconds += chunk_audio_seconds
            elapsed_wall_seconds = max(0.001, monotonic() - started_at)
            remaining_audio_seconds = max(0.0, total_chunk_audio_seconds - completed_audio_seconds)
            processing_rate = completed_audio_seconds / elapsed_wall_seconds
            latest_eta_seconds = (
                remaining_audio_seconds / processing_rate
                if processing_rate > 0.0 and remaining_audio_seconds > 0.0
                else 0.0
            )
            logger.info(
                "Completed OpenAI API re-transcription chunk %s/%s: chunk_wall=%.2fs, "
                "completed_audio=%.2fs/%.2fs, completed_bytes=%s/%s, eta=%.1fs",
                index,
                len(chunks),
                monotonic() - chunk_started_at,
                completed_audio_seconds,
                total_chunk_audio_seconds,
                sum(len(chunk[0]) for chunk in chunks[:index]),
                total_chunk_bytes,
                latest_eta_seconds,
            )
            if progress_callback is not None:
                await progress_callback(
                    chunk_progress_end,
                    chunk_end,
                    f"Finished audio segment {index} of {len(chunks)}...",
                    latest_eta_seconds,
                )

        logger.info(
            "OpenAI API chunked timestamped transcription complete: %s chunks, %s segments",
            len(chunks),
            len(merged_segments),
        )
        return merged_segments

    async def transcribe(
        self, audio_data: bytes, context_info: Optional[Dict[str, Any]] = None
    ) -> str:
        """Transcribe audio via the OpenAI API."""
        if not self._model_loaded:
            self.load_model()

        language = context_info.get("language") if context_info else None
        model_name_for_history = f"openai/{self._api_model_name}"

        stub = await transcription_lifecycle.begin(
            audio_data,
            context_info,
            model_name=model_name_for_history,
            language=language,
        )

        try:
            if stub.is_retranscription:
                if not stub.audio_path.exists():
                    raise ValueError(f"Existing audio file not found: {stub.audio_path}")
                audio_bytes_for_api = stub.audio_path.read_bytes()
            else:
                audio_bytes_for_api = audio_data

            wav_bytes, suffix = self._prepare_audio(audio_bytes_for_api, context_info)

            start_time = datetime.now()
            if should_route_through_auth_service():
                transcribed_text = await self._transcribe_via_auth_proxy(
                    wav_bytes,
                    suffix,
                    language,
                )
            else:
                transcribed_text = await self._transcribe_direct(wav_bytes, suffix, language)
            transcribed_text = transcribed_text.strip()
            if transcribed_text:
                transcribed_text += " "
            processing_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            await transcription_lifecycle.complete(
                stub,
                transcribed_text,
                processing_time_ms=processing_time_ms,
                model_name=model_name_for_history,
            )

            return transcribed_text

        except Exception as exc:
            logger.error("OpenAI Whisper API transcription failed: %s", exc)
            try:
                await transcription_lifecycle.fail(
                    stub,
                    str(exc),
                    model_name=model_name_for_history,
                )
            except Exception as persist_exc:
                logger.warning(
                    "Also failed to record transcription failure: %s",
                    persist_exc,
                )
            raise
