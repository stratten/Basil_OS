"""Tests for narrowing the suggested-actions transcript to cited windows."""

from types import SimpleNamespace

from api.services.whisper_live_core.post_processing.meeting_analysis_narrowing import (
    narrow_transcript_for_suggestions,
)


def _long_transcript(segment_count: int = 400) -> dict:
    return {
        "segments": [
            {
                "start": index * 10,
                "end": index * 10 + 9,
                "speaker": "A",
                "text": f"segment-{index} " + " ".join(["word"] * 40),
            }
            for index in range(segment_count)
        ]
    }


def test_long_transcript_is_narrowed_to_the_cited_window():
    transcript = _long_transcript()

    narrowed = narrow_transcript_for_suggestions(
        transcript, [SimpleNamespace(timestamp=100.0)]
    )

    texts = " ".join(segment["text"] for segment in narrowed["segments"])
    assert 0 < len(narrowed["segments"]) < len(transcript["segments"])
    assert "segment-10 " in texts
    assert "segment-300 " not in texts
    assert len(transcript["segments"]) == 400


def test_dict_items_are_supported_and_windows_merge_across_items():
    transcript = _long_transcript()

    narrowed = narrow_transcript_for_suggestions(
        transcript, [{"timestamp": 100.0}, {"timestamp": 3000.0}]
    )

    texts = " ".join(segment["text"] for segment in narrowed["segments"])
    assert "segment-10 " in texts
    assert "segment-300 " in texts
    assert "segment-150 " not in texts


def test_missing_or_invalid_timestamps_fall_back_to_the_full_transcript():
    transcript = _long_transcript()
    for items in (
        [],
        None,
        [SimpleNamespace(timestamp=None)],
        [SimpleNamespace(timestamp=float("nan"))],
        [SimpleNamespace(timestamp=-5.0)],
        [SimpleNamespace(timestamp=100.0), SimpleNamespace(timestamp="soon")],
    ):
        assert narrow_transcript_for_suggestions(transcript, items) is transcript


def test_short_transcripts_are_never_narrowed():
    transcript = _long_transcript(segment_count=5)

    assert (
        narrow_transcript_for_suggestions(transcript, [SimpleNamespace(timestamp=10.0)])
        is transcript
    )


def test_windows_covering_everything_return_the_original_object():
    transcript = _long_transcript(segment_count=400)
    items = [SimpleNamespace(timestamp=float(second)) for second in range(0, 4000, 60)]

    assert narrow_transcript_for_suggestions(transcript, items) is transcript


def test_empty_transcript_is_returned_unchanged():
    transcript = {"segments": []}

    assert (
        narrow_transcript_for_suggestions(transcript, [SimpleNamespace(timestamp=1.0)])
        is transcript
    )
