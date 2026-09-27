"""CLI for the Parakeet failure-mode diagnostic harness."""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
from pathlib import Path
from typing import List

if __package__ in {None, ""}:
    package_dir = Path(__file__).resolve().parent
    src_dir = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(src_dir))
    sys.path.insert(0, str(package_dir.parent))
    __package__ = "parakeet_failure_modes"

from .audio_coverage import analyze_audio_coverage
from .basil_parakeet_probe import (
    DEFAULT_BASIL_PARAKEET_MODEL,
    run_basil_parakeet_adaptive_probe,
    run_basil_parakeet_probe,
)
from .local_whisper_probe import DEFAULT_WHISPER_MODEL, run_local_whisper_probe
from .models import (
    FailureModeReport,
    HarnessEnvironment,
    build_text_comparisons,
    resolve_fp32_bundle_presence,
)
from .onnx_asr_probe import (
    get_onnx_asr_version,
    resolve_basil_parakeet_bundle_dir,
    run_onnx_asr_conditioned_probe,
    run_onnx_asr_raw_probe,
)


DEFAULT_OUTPUT_DIR = Path("/tmp/basil_parakeet_failure_modes")


async def run_harness(
    *,
    audio_path: Path,
    output_path: Path,
    parakeet_model_id: str = DEFAULT_BASIL_PARAKEET_MODEL,
    whisper_model_name: str = DEFAULT_WHISPER_MODEL,
) -> FailureModeReport:
    audio_metrics = analyze_audio_coverage(audio_path)
    runs = [
        run_basil_parakeet_probe(audio_path, model_id=parakeet_model_id),
        run_basil_parakeet_adaptive_probe(audio_path, model_id=parakeet_model_id),
        run_onnx_asr_raw_probe(audio_path, model_id=parakeet_model_id),
        run_onnx_asr_conditioned_probe(audio_path, model_id=parakeet_model_id),
        await run_local_whisper_probe(audio_path, model_name=whisper_model_name),
    ]
    report = FailureModeReport(
        audio=audio_metrics,
        runs=runs,
        comparisons=build_text_comparisons(runs),
        environment=build_environment(model_id=parakeet_model_id),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def build_environment(*, model_id: str) -> HarnessEnvironment:
    bundle_dir = _safe_bundle_dir(model_id)
    return HarnessEnvironment(
        python_executable=sys.executable,
        platform=platform.platform(),
        onnxruntime_providers=_onnxruntime_providers(),
        basil_parakeet_model_id=model_id,
        basil_bundle_dir=str(bundle_dir) if bundle_dir is not None else None,
        onnx_asr_version=get_onnx_asr_version(),
        fp32_bundle_present=resolve_fp32_bundle_presence(
            Path.home() / ".basil" / "models"
        ),
    )


def _safe_bundle_dir(model_id: str) -> Path | None:
    try:
        return resolve_basil_parakeet_bundle_dir(model_id=model_id)
    except Exception:
        return None


def _onnxruntime_providers() -> List[str]:
    try:
        import onnxruntime as ort

        return list(ort.get_available_providers())
    except Exception:
        return []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Parakeet failure-mode diagnostic harness.",
    )
    parser.add_argument(
        "--audio-path",
        required=True,
        type=Path,
        help="Path to a 16 kHz-compatible WAV recording.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path for the JSON report. Defaults under /tmp.",
    )
    parser.add_argument(
        "--parakeet-model-id",
        default=DEFAULT_BASIL_PARAKEET_MODEL,
        help="Basil Parakeet model id to inspect.",
    )
    parser.add_argument(
        "--whisper-model-name",
        default=DEFAULT_WHISPER_MODEL,
        help="Local Whisper model name for the coverage comparison.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audio_path = args.audio_path.expanduser().resolve()
    output_path = (
        args.output.expanduser().resolve()
        if args.output is not None
        else DEFAULT_OUTPUT_DIR / f"{audio_path.stem}.json"
    )
    report = asyncio.run(
        run_harness(
            audio_path=audio_path,
            output_path=output_path,
            parakeet_model_id=args.parakeet_model_id,
            whisper_model_name=args.whisper_model_name,
        )
    )
    print(f"Wrote report: {output_path}")
    for run in report.runs:
        status = "ok" if run.success else f"failed: {run.error}"
        print(f"{run.backend}: {status}; chars={run.text_chars}; words={run.estimated_words}")


if __name__ == "__main__":
    main()
