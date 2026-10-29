import pytest

from api.services.whisper_live_core.post_processing.transcript_merger import (
    ProcessingProgress,
)


def _progress(active_stages):
    return ProcessingProgress(
        stage="transcription",
        stage_progress=0.0,
        current_time=0.0,
        total_time=100.0,
        message="Testing progress",
        eta_seconds=0.0,
        active_stages=active_stages,
    )


def test_transcribe_only_progress_excludes_unused_diarization_and_merging_stages():
    progress = _progress(("loading", "transcription"))
    progress.loading_complete = 1.0
    progress.transcription_complete = 0.70

    assert progress.calculate_overall_progress() == pytest.approx(0.85)


def test_default_progress_preserves_full_post_processing_stage_average():
    progress = ProcessingProgress(
        stage="transcription",
        stage_progress=0.0,
        current_time=0.0,
        total_time=100.0,
        message="Testing progress",
        eta_seconds=0.0,
    )
    progress.loading_complete = 1.0
    progress.transcription_complete = 0.70

    assert progress.calculate_overall_progress() == pytest.approx(0.425)


def test_diarize_only_progress_uses_loading_diarization_and_merging_stages():
    progress = _progress(("loading", "diarization", "merging"))
    progress.loading_complete = 1.0
    progress.diarization_complete = 0.5
    progress.merging_complete = 0.0

    assert progress.calculate_overall_progress() == pytest.approx(0.5)
