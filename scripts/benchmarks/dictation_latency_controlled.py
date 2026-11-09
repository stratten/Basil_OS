"""Controlled transcription latency by audio length, cold versus warm, through Basil's Parakeet path (backend only).

Fixtures are LibriSpeech test-clean utterances (real read speech) concatenated with 0.3 s gaps to roughly 5, 15, 30, 60, and 120 seconds, so the 60 s long-form chunker is exercised at 60 and 120.
This measures the transcription engine share of stop-to-text latency. It does NOT cover the native hotkey, audio capture, websocket, or paste path; the log-derived figures in dictation_log_latency.py cover those end to end on real use.
Cold = model load plus the first transcription after load. Warm = median of the following runs.

Usage: PYTHONPATH=scripts:backend/src .venv/bin/python -m benchmarks.dictation_latency_controlled [--model-id NVIDIA-parakeet-tdt-0.6b-v3-full-precision] [--runs 5] [--smoke]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.common.results import build_result, metric_from_summary, write_result  # noqa: E402
from benchmarks.common.timing import summarize  # noqa: E402
from benchmarks.dictation_wer import fetch_librispeech  # noqa: E402

TARGETS = [5, 15, 30, 60, 120]


def build_fixtures(targets: List[int], directory: Path) -> Dict[int, Path]:
    pool = fetch_librispeech(400)
    gap = np.zeros(int(0.3 * 16000), dtype=np.float32)
    fixtures: Dict[int, Path] = {}
    cursor = 0
    for target in targets:
        pieces: List[np.ndarray] = []
        total = 0.0
        while total < target:
            audio, rate = sf.read(pool[cursor % len(pool)]["path"], dtype="float32")
            cursor += 1
            if rate != 16000:
                continue
            pieces.extend([audio, gap])
            total += len(audio) / 16000 + 0.3
        path = directory / f"fixture_{target}s.wav"
        sf.write(str(path), np.concatenate(pieces), 16000, subtype="PCM_16")
        fixtures[target] = path
    return fixtures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model-id", default="NVIDIA-parakeet-tdt-0.6b-v3-full-precision")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    targets = [5] if args.smoke else TARGETS
    runs = 1 if args.smoke else args.runs

    from api.services.transcription.backends.parakeet_service import ParakeetTranscriptionService

    work = Path(tempfile.mkdtemp(prefix="basil-bench-latency-"))
    fixtures = build_fixtures(targets, work)
    service = ParakeetTranscriptionService(args.model_id)
    rows: List[Dict[str, Any]] = []
    metrics: Dict[str, Any] = {}
    for target in targets:
        path = fixtures[target]
        duration = sf.info(str(path)).duration
        service.unload_model()
        started = time.perf_counter()
        service.load_model()
        load_s = time.perf_counter() - started
        t0 = time.perf_counter()
        service._transcribe_wav(str(path))
        first_s = time.perf_counter() - t0
        warm = []
        for _ in range(runs):
            t0 = time.perf_counter()
            text = service._transcribe_wav(str(path))
            warm.append(time.perf_counter() - t0)
        rows.append({"target_s": target, "audio_s": duration, "load_s": load_s, "first_after_load_s": first_s, "warm_s": warm, "words": len(text.split())})
        print(f"{target:>4}s fixture ({duration:.1f}s audio): load {load_s:.2f}s  first {first_s:.2f}s  warm median {summarize(warm)['median']:.2f}s  rtf {summarize(warm)['median'] / duration:.3f}", flush=True)
        metrics[f"fixture_{target}s_warm"] = metric_from_summary(summarize(warm), "s")
        metrics[f"fixture_{target}s_cold_total"] = metric_from_summary(summarize([load_s + first_s]), "s")
    result = build_result(
        "dictation_latency_controlled",
        mode="smoke" if args.smoke else "full",
        subject={"label": args.model_id, "engine": "ParakeetTranscriptionService._transcribe_wav"},
        parameters={"targets_s": targets, "runs": runs, "fixtures": "concatenated LibriSpeech test-clean utterances, 0.3 s gaps"},
        metrics=metrics,
        runs=rows,
        notes=[
            "Backend transcription time only. Native hotkey, audio capture, websocket, and paste latency are not measured here; see dictation_log_latency for end-to-end figures from real use.",
            "Cold includes model load and the first run after load. Basil's own idle unload happens after 60 seconds, so a dictation after a pause pays this cold cost.",
        ],
    )
    print(f"wrote {write_result(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
