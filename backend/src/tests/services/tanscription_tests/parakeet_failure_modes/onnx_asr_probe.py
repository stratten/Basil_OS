"""onnx-asr oracle probe for Parakeet failure-mode diagnostics."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
from time import monotonic
from typing import Optional

from api.services.transcription.backends.parakeet_components.parakeet_model_manager import (
    _resolve_bundle_dir,
)
from api.core.models.models_registry import get_model

from .basil_parakeet_probe import (
    DEFAULT_BASIL_PARAKEET_MODEL,
    load_basil_conditioned_audio,
)
from .audio_coverage import load_mono_audio
from .models import BackendRunResult, build_backend_result


ONNX_ASR_MODEL_NAME = "nemo-parakeet-tdt-0.6b-v3"


def run_onnx_asr_raw_probe(
    audio_path: Path,
    *,
    model_id: str = DEFAULT_BASIL_PARAKEET_MODEL,
) -> BackendRunResult:
    return _run_onnx_asr_probe(
        audio_path,
        backend="onnx_asr_raw",
        model_id=model_id,
        use_basil_conditioning=False,
    )


def run_onnx_asr_conditioned_probe(
    audio_path: Path,
    *,
    model_id: str = DEFAULT_BASIL_PARAKEET_MODEL,
) -> BackendRunResult:
    return _run_onnx_asr_probe(
        audio_path,
        backend="onnx_asr_basil_conditioned",
        model_id=model_id,
        use_basil_conditioning=True,
    )


def resolve_basil_parakeet_bundle_dir(
    *,
    model_id: str = DEFAULT_BASIL_PARAKEET_MODEL,
) -> Path:
    model = get_model(model_id)
    if not model:
        raise RuntimeError(f"Unknown Basil Parakeet model id: {model_id}")
    on_disk_name = model.get("on_disk_name")
    if not on_disk_name:
        raise RuntimeError(f"Basil Parakeet model has no on_disk_name: {model_id}")
    return _resolve_bundle_dir(str(on_disk_name))


def get_onnx_asr_version() -> Optional[str]:
    try:
        return metadata.version("onnx-asr")
    except metadata.PackageNotFoundError:
        return None


def _run_onnx_asr_probe(
    audio_path: Path,
    *,
    backend: str,
    model_id: str,
    use_basil_conditioning: bool,
) -> BackendRunResult:
    started_at = monotonic()
    try:
        import onnx_asr

        bundle_dir = resolve_basil_parakeet_bundle_dir(model_id=model_id)
        model = onnx_asr.load_model(
            ONNX_ASR_MODEL_NAME,
            str(bundle_dir),
            quantization="int8",
        )
        if use_basil_conditioning:
            audio = load_basil_conditioned_audio(audio_path)
            text = model.recognize(audio, sample_rate=16000)
        else:
            audio, _ = load_mono_audio(audio_path)
            text = model.recognize(audio, sample_rate=16000)
        return build_backend_result(
            backend=backend,
            model_id=ONNX_ASR_MODEL_NAME,
            success=True,
            wall_seconds=monotonic() - started_at,
            text=text,
        )
    except Exception as exc:
        return build_backend_result(
            backend=backend,
            model_id=ONNX_ASR_MODEL_NAME,
            success=False,
            wall_seconds=monotonic() - started_at,
            error=f"{type(exc).__name__}: {exc}",
        )
