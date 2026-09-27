"""Report models for the Parakeet failure-mode diagnostic harness."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class AudioSpan:
    start_seconds: float
    end_seconds: float


@dataclass
class AudioCoverageMetrics:
    path: str
    sample_rate: int
    samples: int
    duration_seconds: float
    rms: float
    peak: float
    coverage_window_seconds: float
    coverage_threshold: float
    active_windows: int
    total_windows: int
    active_window_ratio: float
    max_silent_run_seconds: float
    active_spans: List[AudioSpan] = field(default_factory=list)


@dataclass
class BasilDecoderDiagnostics:
    features_shape: Optional[List[int]] = None
    feature_length: Optional[int] = None
    encoder_hidden_shape: Optional[List[int]] = None
    encoded_length: Optional[int] = None
    piece_count: int = 0
    word_count: int = 0
    text_chars: int = 0
    first_word_seconds: Optional[float] = None
    last_word_seconds: Optional[float] = None
    word_span_seconds: Optional[float] = None
    encoder_frames: Optional[int] = None
    first_emitted_frame: Optional[int] = None
    last_emitted_frame: Optional[int] = None
    blank_steps: int = 0
    nonblank_steps: int = 0
    forced_advances: int = 0
    duration_step_counts: Dict[str, int] = field(default_factory=dict)


@dataclass
class BackendRunResult:
    backend: str
    model_id: str
    success: bool
    wall_seconds: float
    text: str = ""
    text_chars: int = 0
    estimated_words: int = 0
    error: Optional[str] = None
    diagnostics: Optional[BasilDecoderDiagnostics] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TextComparison:
    left_backend: str
    right_backend: str
    left_text_chars: int
    right_text_chars: int
    left_estimated_words: int
    right_estimated_words: int
    levenshtein_ratio: Optional[float]


@dataclass
class HarnessEnvironment:
    python_executable: str
    platform: str
    onnxruntime_providers: List[str]
    basil_parakeet_model_id: str
    basil_bundle_dir: Optional[str]
    onnx_asr_version: Optional[str]
    fp32_bundle_present: bool


@dataclass
class FailureModeReport:
    audio: AudioCoverageMetrics
    runs: List[BackendRunResult]
    comparisons: List[TextComparison]
    environment: HarnessEnvironment

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_backend_result(
    *,
    backend: str,
    model_id: str,
    success: bool,
    wall_seconds: float,
    text: str = "",
    error: Optional[str] = None,
    diagnostics: Optional[BasilDecoderDiagnostics] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> BackendRunResult:
    normalized_text = " ".join(text.strip().split())
    return BackendRunResult(
        backend=backend,
        model_id=model_id,
        success=success,
        wall_seconds=round(wall_seconds, 3),
        text=normalized_text,
        text_chars=len(normalized_text),
        estimated_words=len(normalized_text.split()),
        error=error,
        diagnostics=diagnostics,
        metadata=metadata or {},
    )


def build_text_comparisons(runs: List[BackendRunResult]) -> List[TextComparison]:
    successful_runs = [run for run in runs if run.success]
    comparisons: List[TextComparison] = []
    for left_index, left in enumerate(successful_runs):
        for right in successful_runs[left_index + 1 :]:
            comparisons.append(
                TextComparison(
                    left_backend=left.backend,
                    right_backend=right.backend,
                    left_text_chars=left.text_chars,
                    right_text_chars=right.text_chars,
                    left_estimated_words=left.estimated_words,
                    right_estimated_words=right.estimated_words,
                    levenshtein_ratio=compute_levenshtein_ratio(left.text, right.text),
                )
            )
    return comparisons


def compute_levenshtein_ratio(left: str, right: str) -> Optional[float]:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    try:
        from Levenshtein import ratio

        return round(float(ratio(left, right)), 4)
    except Exception:
        return None


def resolve_fp32_bundle_presence(models_dir: Path) -> bool:
    return (models_dir / "parakeet-tdt-0.6b-v3-onnx-full-precision").exists()
