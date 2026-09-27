"""Chunked Parakeet post-processing transcription."""

from __future__ import annotations

import asyncio
import logging
from time import time
from typing import Any, Awaitable, Callable, Dict, List

import librosa
import numpy as np

from api.services.transcription.backends.parakeet_components.parakeet_chunking import (
    WordTuple,
    build_silence_aware_parakeet_chunks,
    deduplicate_parakeet_boundary_words,
    offset_and_filter_parakeet_words,
    parakeet_word_tuples_to_segments,
)
from api.services.transcription.backends.parakeet_service import (
    ParakeetTranscriptionService,
)
from api.core.models.models_registry import get_model_chunk_seconds


logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, float, str, float], Awaitable[None]]


def _format_elapsed_clock(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _format_seconds_with_clock(seconds: float) -> str:
    return f"{seconds:.1f}s ({_format_elapsed_clock(seconds)})"


class ParakeetChunkedTranscriber:
    """Run Parakeet over silence-aware chunks with progress updates."""

    sample_rate = 16000
    target_chunk_seconds = 30.0
    max_chunk_seconds = 40.0
    min_chunk_seconds = 18.0
    boundary_search_radius_seconds = 5.0
    analysis_window_seconds = 0.5
    overlap_seconds = 0.5

    def __init__(self, audio_path: str, audio_duration: float, model_id: str):
        self.audio_path = audio_path
        self.audio_duration = audio_duration
        self.model_id = model_id
        # Override the default chunk window with the registry-configured value
        # when the model declares one; otherwise keep the class default so
        # behavior is preserved for models without a configured chunk size.
        registry_chunk_seconds = get_model_chunk_seconds(model_id)
        if registry_chunk_seconds is not None:
            self.target_chunk_seconds = registry_chunk_seconds

    async def transcribe(self, progress_callback: ProgressCallback) -> List[Dict[str, Any]]:
        """Transcribe the configured audio file into timestamped segments."""
        loop = asyncio.get_running_loop()
        start_time = time()

        await progress_callback(
            0.02,
            0.0,
            "Loading Parakeet model for re-transcription...",
            0.0,
        )
        service = ParakeetTranscriptionService(model_id=self.model_id)
        await loop.run_in_executor(None, service.load_model)

        await progress_callback(
            0.08,
            0.0,
            "Loading meeting audio for Parakeet...",
            0.0,
        )
        audio = await loop.run_in_executor(
            None,
            lambda: librosa.load(self.audio_path, sr=self.sample_rate, mono=True)[0],
        )
        audio = audio.astype(np.float32, copy=False)
        chunks = build_silence_aware_parakeet_chunks(
            audio,
            sample_rate=self.sample_rate,
            target_chunk_seconds=self.target_chunk_seconds,
            max_chunk_seconds=self.max_chunk_seconds,
            min_chunk_seconds=self.min_chunk_seconds,
            boundary_search_radius_seconds=self.boundary_search_radius_seconds,
            analysis_window_seconds=self.analysis_window_seconds,
            overlap_seconds=self.overlap_seconds,
        )
        logger.info(
            "Parakeet chunk plan: %s chunks for %.1fs audio",
            len(chunks),
            len(audio) / self.sample_rate if audio.size else 0.0,
        )

        all_words: List[WordTuple] = []
        for chunk in chunks:
            chunk_start_time = time()
            audio_start = self._seconds_to_sample(chunk.audio_start_seconds)
            audio_end = self._seconds_to_sample(chunk.audio_end_seconds)
            chunk_audio = audio[audio_start:audio_end]

            logger.info(
                "Parakeet chunk %s/%s start: audio %.2f-%.2fs, accept %.2f-%.2fs, samples=%s",
                chunk.index + 1,
                len(chunks),
                chunk.audio_start_seconds,
                chunk.audio_end_seconds,
                chunk.accept_start_seconds,
                chunk.accept_end_seconds,
                len(chunk_audio),
            )

            local_words = await loop.run_in_executor(
                None,
                service.transcribe_array,
                chunk_audio,
            )
            accepted_words = offset_and_filter_parakeet_words(
                chunk,
                local_words,
                audio_duration_seconds=self.audio_duration,
            )
            newly_added_words = deduplicate_parakeet_boundary_words(all_words, accepted_words)
            all_words.extend(newly_added_words)

            current_time = min(chunk.accept_end_seconds, self.audio_duration)
            stage_progress = min(current_time / self.audio_duration, 1.0) if self.audio_duration > 0 else 1.0
            eta_seconds = self._estimate_remaining_seconds(start_time, stage_progress)
            # Segments newly completed this chunk so the client can render the
            # higher-quality Parakeet output incrementally. The final `complete`
            # still performs the authoritative full swap.
            new_segments = (
                self.word_tuples_to_segments(newly_added_words) if newly_added_words else []
            )
            await progress_callback(
                stage_progress,
                current_time,
                (
                    f"Re-transcribing with Parakeet: {_format_seconds_with_clock(current_time)} / "
                    f"{_format_seconds_with_clock(self.audio_duration)}"
                ),
                eta_seconds,
                new_segments,
            )

            logger.info(
                "Parakeet chunk %s/%s complete in %.1fs: local_words=%s accepted_words=%s",
                chunk.index + 1,
                len(chunks),
                time() - chunk_start_time,
                len(local_words),
                len(accepted_words),
            )

        segments = self.word_tuples_to_segments(all_words)
        await progress_callback(
            1.0,
            self.audio_duration,
            f"Parakeet re-transcription complete: {len(segments)} segments",
            0.0,
        )
        logger.info(
            "Parakeet chunked transcription complete in %.1fs: words=%s segments=%s",
            time() - start_time,
            len(all_words),
            len(segments),
        )
        return segments

    def _seconds_to_sample(self, seconds: float) -> int:
        return int(round(seconds * self.sample_rate))

    @staticmethod
    def _estimate_remaining_seconds(start_time: float, stage_progress: float) -> float:
        if stage_progress <= 0:
            return 0.0
        elapsed = time() - start_time
        total_estimate = elapsed / stage_progress
        return max(0.0, total_estimate - elapsed)

    @staticmethod
    def word_tuples_to_segments(
        word_tuples: List[WordTuple],
        max_gap_seconds: float = 0.8,
        max_segment_seconds: float = 12.0,
    ) -> List[Dict[str, Any]]:
        """Group word-level timestamp triples into readable transcript segments."""
        return parakeet_word_tuples_to_segments(
            word_tuples,
            max_gap_seconds=max_gap_seconds,
            max_segment_seconds=max_segment_seconds,
        )
