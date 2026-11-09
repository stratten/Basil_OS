"""Word error rate, speed, and memory for Basil's local transcription engines on public read speech and a custom-vocabulary set.

Sets: LibriSpeech test-clean (a deterministic subset, public read speech, downloaded once to ~/.basil-bench/data) and the synthetic custom-vocabulary set in dictation_custom_set.py (macOS `say`, so results bound accuracy from above).
Each engine runs in its own subprocess so load time and peak memory are not polluted by earlier engines. Engines use Basil's own service classes; nothing is written under ~/.basil beyond what importing the backend already does, and no transcription history rows are created (the services' persisting entry points are not used).

Usage:
    PYTHONPATH=scripts:backend/src .venv/bin/python -m benchmarks.dictation_wer [--engines a,b] [--n-librispeech 100] [--smoke]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks import dictation_custom_set  # noqa: E402
from benchmarks.common.machine import REPO_ROOT  # noqa: E402
from benchmarks.common.results import build_result, metric_from_summary, write_result  # noqa: E402
from benchmarks.common.timing import PeakMemorySampler, summarize  # noqa: E402
from benchmarks.common.wer import corpus_wer, term_recall, word_errors  # noqa: E402

DATA_DIR = Path.home() / ".basil-bench" / "data"
LIBRI_URL = "https://www.openslr.org/resources/12/test-clean.tar.gz"
ENGINES: Dict[str, Tuple[str, str]] = {
    "parakeet-v3-full": ("parakeet", "NVIDIA-parakeet-tdt-0.6b-v3-full-precision"),
    "parakeet-v3-quantized": ("parakeet", "NVIDIA-parakeet-tdt-0.6b-v3-quantized"),
    "parakeet-v2-full": ("parakeet", "NVIDIA-parakeet-tdt-0.6b-v2-full-precision"),
    "parakeet-v2-quantized": ("parakeet", "NVIDIA-parakeet-tdt-0.6b-v2-quantized"),
    "whisper-tiny": ("whisper", "Whisper Tiny"),
    "whisper-base": ("whisper", "Whisper Base"),
    "whisper-small-en": ("whisper", "Whisper Small (English)"),
    "whisper-large-v3-turbo": ("whisper", "Whisper Large V3 Turbo"),
}


def fetch_librispeech(count: int) -> List[Dict[str, Any]]:
    root = DATA_DIR / "LibriSpeech" / "test-clean"
    if not root.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        archive = DATA_DIR / "test-clean.tar.gz"
        if not archive.exists():
            print(f"downloading {LIBRI_URL}", flush=True)
            urllib.request.urlretrieve(LIBRI_URL, archive)
        with tarfile.open(archive) as tar:
            tar.extractall(DATA_DIR)
    entries: List[Dict[str, Any]] = []
    for trans in sorted(root.rglob("*.trans.txt")):
        for line in trans.read_text().splitlines():
            utt_id, text = line.split(" ", 1)
            flac = trans.parent / f"{utt_id}.flac"
            if sf.info(str(flac)).duration <= 28.0:
                entries.append({"id": utt_id, "path": str(flac), "reference": text})
    step = max(1, len(entries) // count)
    return entries[::step][:count]


def synthesize_custom() -> List[Dict[str, Any]]:
    out_dir = DATA_DIR / "custom"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for sid, voice, text, terms in dictation_custom_set.SENTENCES:
        path = out_dir / f"{sid}.wav"
        if not path.exists():
            subprocess.run(["say", "-v", voice, "-o", str(path), "--data-format=LEI16@16000", text], check=True)
        rows.append({"id": sid, "path": str(path), "reference": text, "terms": terms, "voice": voice})
    return rows


def load_audio(path: str) -> np.ndarray:
    audio, rate = sf.read(path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != 16000:
        raise SystemExit(f"{path} is {rate} Hz; expected 16000")
    return np.ascontiguousarray(audio)


def build_engine(kind: str, model_id: str):
    if kind == "parakeet":
        from api.services.transcription.backends.parakeet_service import ParakeetTranscriptionService

        service = ParakeetTranscriptionService(model_id)

        def transcribe(audio: np.ndarray, path: str) -> str:
            # The synchronous, non-persisting entry point behind transcribe(): file load, adaptive strategy, and long-form chunking at 60 s and above.
            return service._transcribe_wav(path)

        return service.load_model, transcribe, service.unload_model

    from api.services.transcription.local_model.model_lifecycle import ModelManager

    manager = ModelManager()

    def transcribe_whisper(audio: np.ndarray, path: str) -> str:
        with manager.acquire_warm_pipeline(model_id, priority="live") as pipe:
            result = pipe(audio, return_timestamps=True)
        if isinstance(result, dict) and isinstance(result.get("chunks"), list):
            return "".join(chunk["text"] for chunk in result["chunks"]).strip()
        return str(result.get("text", "")).strip() if isinstance(result, dict) else str(result)

    return (lambda: manager.load_model(model_id)), transcribe_whisper, manager.unload_model


def run_engine(name: str, spec_path: Path, out_path: Path) -> None:
    kind, model_id = ENGINES[name]
    spec = json.loads(spec_path.read_text())
    load, transcribe, unload = build_engine(kind, model_id)
    with PeakMemorySampler() as memory:
        started = time.perf_counter()
        load()
        load_seconds = time.perf_counter() - started
        first_path = spec["librispeech"][0]["path"]
        transcribe(load_audio(first_path), first_path)  # warm-up, discarded
        outputs: Dict[str, List[Dict[str, Any]]] = {}
        for set_name in ("librispeech", "custom"):
            rows = []
            for item in spec[set_name]:
                audio = load_audio(item["path"])
                t0 = time.perf_counter()
                hypothesis = transcribe(audio, item["path"])
                elapsed = time.perf_counter() - t0
                rows.append({"id": item["id"], "reference": item["reference"], "hypothesis": hypothesis, "audio_seconds": len(audio) / 16000, "seconds": elapsed, "terms": item.get("terms", [])})
            outputs[set_name] = rows
        peak_mb = memory.peak_mb
    unload()
    out_path.write_text(json.dumps({"engine": name, "load_seconds": load_seconds, "peak_rss_mb": peak_mb, "outputs": outputs}))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--engines", default=",".join(ENGINES))
    parser.add_argument("--n-librispeech", type=int, default=100)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--engine-child", help="internal: run one engine and write --out")
    parser.add_argument("--spec")
    parser.add_argument("--out")
    args = parser.parse_args()

    if args.engine_child:
        run_engine(args.engine_child, Path(args.spec), Path(args.out))
        return 0

    engines = args.engines.split(",")
    count = 5 if args.smoke else args.n_librispeech
    if args.smoke:
        engines = engines[:1]
    libri = fetch_librispeech(count)
    custom = synthesize_custom()[: 5 if args.smoke else None]
    print(f"librispeech utterances {len(libri)}, custom sentences {len(custom)}, engines {engines}")
    if args.dry_run:
        return 0

    work = Path(tempfile.mkdtemp(prefix="basil-bench-wer-"))
    spec = work / "spec.json"
    spec.write_text(json.dumps({"librispeech": libri, "custom": custom}))
    env_python = str(REPO_ROOT / ".venv" / "bin" / "python")
    per_engine: List[Dict[str, Any]] = []
    for name in engines:
        out = work / f"{name}.json"
        print(f"-- {name}", flush=True)
        proc = subprocess.run([env_python, "-m", "benchmarks.dictation_wer", "--engine-child", name, "--spec", str(spec), "--out", str(out)], cwd=REPO_ROOT, capture_output=True, text=True)
        if proc.returncode != 0 or not out.exists():
            print(f"   FAILED: {proc.stderr[-600:]}")
            per_engine.append({"engine": name, "failed": True, "stderr_tail": proc.stderr[-600:]})
            continue
        data = json.loads(out.read_text())
        lib = data["outputs"]["librispeech"]
        cus = data["outputs"]["custom"]
        found = total = 0
        for row in cus:
            f, t = term_recall(row["terms"], row["hypothesis"])
            found, total = found + f, total + t
        data["summary"] = {
            "wer_librispeech": corpus_wer([(r["reference"], r["hypothesis"]) for r in lib]),
            "wer_custom": corpus_wer([(r["reference"], r["hypothesis"]) for r in cus]),
            "term_recall_custom": found / total if total else float("nan"),
            "rtf": summarize([r["seconds"] / r["audio_seconds"] for r in lib + cus]),
        }
        print(f"   WER libri {data['summary']['wer_librispeech']:.3f}  custom {data['summary']['wer_custom']:.3f}  term recall {data['summary']['term_recall_custom']:.2f}  load {data['load_seconds']:.1f}s  peak {data['peak_rss_mb'] / 1024:.1f} GB  rtf {data['summary']['rtf']['median']:.3f}", flush=True)
        per_engine.append(data)

    ok = [e for e in per_engine if not e.get("failed")]
    metrics: Dict[str, Any] = {}
    for e in ok:
        s, tag = e["summary"], e["engine"]
        metrics[f"{tag}_wer_librispeech"] = metric_from_summary(summarize([s["wer_librispeech"]]), "fraction")
        metrics[f"{tag}_wer_custom"] = metric_from_summary(summarize([s["wer_custom"]]), "fraction")
        metrics[f"{tag}_term_recall_custom"] = metric_from_summary(summarize([s["term_recall_custom"]]), "fraction")
        metrics[f"{tag}_load_time"] = metric_from_summary(summarize([e["load_seconds"]]), "s")
        metrics[f"{tag}_peak_rss"] = metric_from_summary(summarize([e["peak_rss_mb"] / 1024]), "GB")
        metrics[f"{tag}_rtf"] = metric_from_summary(s["rtf"], "x real time")
    result = build_result(
        "dictation_wer",
        mode="smoke" if args.smoke else "full",
        subject={"label": "local-transcription-engines", "engines": engines},
        parameters={"librispeech_utterances": len(libri), "custom_sentences": len(custom), "librispeech_subset": "every k-th utterance of test-clean up to 28 s", "decode": "engine defaults, no custom vocabulary"},
        metrics=metrics,
        runs=per_engine,
        notes=[
            "LibriSpeech test-clean is clean read speech, so these WER figures are optimistic for dictation. The custom set is synthetic (macOS say) and bounds accuracy from above.",
            "Parakeet runs through ParakeetTranscriptionService._transcribe_wav, the synchronous non-persisting core of transcribe(), and its time includes reading the file. Whisper runs through the warm pipeline with return_timestamps=True and no language hint. All utterances are under 30 seconds, so the long-form chunker is not exercised.",
            "Distil-Whisper is in the registry but not installed locally, so it was not measured.",
            "WER is a single deterministic pass per engine; RTF carries the per-utterance spread.",
        ],
    )
    print(f"wrote {write_result(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
