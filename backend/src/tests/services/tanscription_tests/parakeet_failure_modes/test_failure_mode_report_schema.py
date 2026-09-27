"""Synthetic schema tests for the Parakeet failure-mode harness."""

from __future__ import annotations

import json

from .models import (
    AudioCoverageMetrics,
    AudioSpan,
    BasilDecoderDiagnostics,
    FailureModeReport,
    HarnessEnvironment,
    build_backend_result,
    build_text_comparisons,
)


def test_failure_mode_report_serializes_expected_top_level_keys() -> None:
    basil_run = build_backend_result(
        backend="basil_parakeet_production_conditioned",
        model_id="NVIDIA-parakeet-tdt-0.6b-v3-quantized",
        success=True,
        wall_seconds=1.2345,
        text="hello world",
        diagnostics=BasilDecoderDiagnostics(
            features_shape=[1, 128, 100],
            feature_length=100,
            encoder_hidden_shape=[1, 1024, 25],
            encoded_length=25,
            piece_count=2,
            word_count=2,
            text_chars=11,
            first_word_seconds=0.0,
            last_word_seconds=0.5,
            word_span_seconds=0.5,
            encoder_frames=25,
            first_emitted_frame=0,
            last_emitted_frame=10,
            blank_steps=5,
            nonblank_steps=2,
            forced_advances=0,
            duration_step_counts={"0": 1, "2": 6},
        ),
    )
    whisper_run = build_backend_result(
        backend="local_whisper",
        model_id="Whisper Large V3 Turbo",
        success=True,
        wall_seconds=2.0,
        text="hello world again",
    )
    report = FailureModeReport(
        audio=AudioCoverageMetrics(
            path="/tmp/example.wav",
            sample_rate=16000,
            samples=16000,
            duration_seconds=1.0,
            rms=0.1,
            peak=0.5,
            coverage_window_seconds=0.25,
            coverage_threshold=0.01,
            active_windows=4,
            total_windows=4,
            active_window_ratio=1.0,
            max_silent_run_seconds=0.0,
            active_spans=[AudioSpan(start_seconds=0.0, end_seconds=1.0)],
        ),
        runs=[basil_run, whisper_run],
        comparisons=build_text_comparisons([basil_run, whisper_run]),
        environment=HarnessEnvironment(
            python_executable="/tmp/python",
            platform="test-platform",
            onnxruntime_providers=["CPUExecutionProvider"],
            basil_parakeet_model_id="NVIDIA-parakeet-tdt-0.6b-v3-quantized",
            basil_bundle_dir="/tmp/parakeet",
            onnx_asr_version="0.11.0",
            fp32_bundle_present=False,
        ),
    )

    serialized = json.loads(json.dumps(report.to_dict(), sort_keys=True))

    assert set(serialized.keys()) == {"audio", "runs", "comparisons", "environment"}
    assert serialized["runs"][0]["backend"] == "basil_parakeet_production_conditioned"
    assert serialized["runs"][0]["diagnostics"]["duration_step_counts"] == {"0": 1, "2": 6}
    assert serialized["comparisons"][0]["left_backend"] == "basil_parakeet_production_conditioned"
    assert serialized["environment"]["onnx_asr_version"] == "0.11.0"


def test_text_comparisons_use_successful_runs_only() -> None:
    basil_run = build_backend_result(
        backend="basil_parakeet_production_conditioned",
        model_id="parakeet",
        success=True,
        wall_seconds=1.0,
        text="short transcript",
    )
    failing_run = build_backend_result(
        backend="onnx_asr_raw",
        model_id="onnx-asr",
        success=False,
        wall_seconds=0.1,
        error="missing model",
    )
    whisper_run = build_backend_result(
        backend="local_whisper",
        model_id="whisper",
        success=True,
        wall_seconds=2.0,
        text="short transcript with extra words",
    )

    comparisons = build_text_comparisons([basil_run, failing_run, whisper_run])

    assert len(comparisons) == 1
    assert comparisons[0].left_backend == "basil_parakeet_production_conditioned"
    assert comparisons[0].right_backend == "local_whisper"
    assert comparisons[0].left_estimated_words == 2
    assert comparisons[0].right_estimated_words == 5
    assert comparisons[0].levenshtein_ratio is None or 0.0 <= comparisons[0].levenshtein_ratio <= 1.0
