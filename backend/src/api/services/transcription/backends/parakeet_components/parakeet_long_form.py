"""Long-form Parakeet transcription orchestration."""

from __future__ import annotations

import logging
from time import time
from typing import Callable, List

import numpy as np

from .parakeet_chunking import (
    WordTuple,
    build_silence_aware_parakeet_chunks,
    deduplicate_parakeet_boundary_words,
    offset_and_filter_parakeet_words,
    parakeet_word_tuples_to_text,
)
from .parakeet_progress import (
    ParakeetProgressCallback,
    ParakeetTranscriptionProgress,
)


PARAKEET_LONG_FORM_STRATEGY = "chunked_long_form"


def transcribe_long_form_parakeet_audio(
    audio: np.ndarray,
    *,
    sample_rate: int,
    infer_words: Callable[[np.ndarray], List[WordTuple]],
    progress_callback: ParakeetProgressCallback | None = None,
    logger: logging.Logger,
) -> str:
    """Run Parakeet over long audio as silence-aware bounded chunks."""

    audio_duration_seconds = audio.size / sample_rate if audio.size else 0.0
    chunks = build_silence_aware_parakeet_chunks(
        audio,
        sample_rate=sample_rate,
    )
    logger.info(
        "Parakeet long-form strategy selected: strategy=%s duration=%.2fs chunks=%s",
        PARAKEET_LONG_FORM_STRATEGY,
        audio_duration_seconds,
        len(chunks),
    )

    all_words: List[WordTuple] = []
    long_form_start = time()
    for chunk in chunks:
        chunk_start_sample = int(round(chunk.audio_start_seconds * sample_rate))
        chunk_end_sample = int(round(chunk.audio_end_seconds * sample_rate))
        chunk_audio = audio[chunk_start_sample:chunk_end_sample]
        chunk_start_time = time()

        local_words = infer_words(chunk_audio)
        accepted_words = offset_and_filter_parakeet_words(
            chunk,
            local_words,
            audio_duration_seconds=audio_duration_seconds,
        )
        new_words = deduplicate_parakeet_boundary_words(
            all_words,
            accepted_words,
        )
        all_words.extend(new_words)

        current_time = min(chunk.accept_end_seconds, audio_duration_seconds)
        stage_progress = (
            min(current_time / audio_duration_seconds, 1.0)
            if audio_duration_seconds > 0
            else 1.0
        )
        eta_seconds = _estimate_remaining_seconds(
            long_form_start,
            stage_progress,
        )
        message = (
            f"Transcribing with Parakeet: {current_time:.1f}s / "
            f"{audio_duration_seconds:.1f}s"
        )
        if progress_callback is not None:
            progress_callback(
                ParakeetTranscriptionProgress(
                    strategy=PARAKEET_LONG_FORM_STRATEGY,
                    stage_progress=stage_progress,
                    current_time_seconds=current_time,
                    audio_duration_seconds=audio_duration_seconds,
                    message=message,
                    eta_seconds=eta_seconds,
                    chunk_index=chunk.index + 1,
                    chunk_count=len(chunks),
                )
            )

        logger.info(
            "Parakeet long-form chunk %s/%s complete in %.2fs: "
            "audio %.2f-%.2fs accept %.2f-%.2fs local_words=%s "
            "accepted_words=%s new_words=%s forced_boundary=%s",
            chunk.index + 1,
            len(chunks),
            time() - chunk_start_time,
            chunk.audio_start_seconds,
            chunk.audio_end_seconds,
            chunk.accept_start_seconds,
            chunk.accept_end_seconds,
            len(local_words),
            len(accepted_words),
            len(new_words),
            chunk.used_forced_boundary,
        )

    text = parakeet_word_tuples_to_text(all_words)
    logger.info(
        "Parakeet long-form complete: duration=%.2fs chunks=%s words=%s "
        "text_chars=%s total_wall=%.2fs",
        audio_duration_seconds,
        len(chunks),
        len(all_words),
        len(text),
        time() - long_form_start,
    )
    return text


def _estimate_remaining_seconds(start_time: float, stage_progress: float) -> float:
    if stage_progress <= 0:
        return 0.0
    elapsed = time() - start_time
    total_estimate = elapsed / stage_progress
    return max(0.0, total_estimate - elapsed)
