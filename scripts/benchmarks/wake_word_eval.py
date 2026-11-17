"""Offline false-accept and false-reject evaluation of Basil's wake-word models (openWakeWord, the same ONNX files and threshold the app uses).

Models: the bundled Hey Basil model (hey_basil) from backend/src/api/vendor/models/wake_word and the pre-trained hey_jarvis from the openwakeword package. The detection threshold is 0.75, matching wake_word_service.py. Frames are 1280 samples (80 ms) of 16 kHz int16 audio, as the app feeds them.
Positives: the phrase synthesized with macOS `say` in several voices, speaking rates, and with and without noise (these voices are not the ElevenLabs voices the Basil models were trained on, so true-accept results are not valid for those models; only the false-accept results count). Negatives: read speech from LibriSpeech test-clean (up to the requested minutes) plus a small set of confusable phrases. CPU cost is the process CPU time per second of audio fed.
The WakeWordDetector class is not used because its constructor can download models; the model files and scoring path are the same.

Usage: PYTHONPATH=scripts:backend/src .venv/bin/python -m benchmarks.wake_word_eval [--negative-minutes 60] [--smoke]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.common.machine import REPO_ROOT  # noqa: E402
from benchmarks.common.results import build_result, metric_from_summary, write_result  # noqa: E402
from benchmarks.common.timing import summarize  # noqa: E402
from benchmarks.dictation_wer import fetch_librispeech  # noqa: E402

THRESHOLD = 0.75
FRAME = 1280
VOICES = ["Samantha", "Daniel", "Karen", "Alex", "Moira", "Fred", "Victoria", "Tessa", "Rishi", "Tom"]
POSITIVE_PHRASES = {"hey basil": ["Hey Basil", "Hey, Basil."], "hey jarvis": ["Hey Jarvis", "Hey, Jarvis."]}
CONFUSABLES = ["Hey Bazil", "Hey Hazel", "Hey Boston", "Hey Basilica", "Okay Basil", "Hey Jarvis", "Hey Marvin", "They basically said", "Hey, is that the basil", "A Jarvis"]


def model_paths() -> Dict[str, str]:
    import openwakeword

    vendor = REPO_ROOT / "backend" / "src" / "api" / "vendor" / "models" / "wake_word"
    return {
        "hey_basil": str(next(vendor.glob("hey_basil*.onnx"))),
        "hey_jarvis": str(next((Path(openwakeword.__file__).parent / "resources" / "models").glob("hey_jarvis*.onnx"))),
    }


def synth(text: str, voice: str, rate: int, path: Path) -> np.ndarray:
    subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", str(path), "--data-format=LEI16@16000", text], check=True, capture_output=True)
    audio, _rate = sf.read(str(path), dtype="float32")
    return audio if audio.ndim == 1 else audio.mean(axis=1)


def peak_scores(model: Any, audio: np.ndarray) -> Dict[str, float]:
    """Run a clip through the model frame by frame and return the maximum score per model."""
    if hasattr(model, "reset"):
        model.reset()
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    peaks: Dict[str, float] = {}
    for start in range(0, len(pcm) - FRAME + 1, FRAME):
        for name, score in model.predict(pcm[start : start + FRAME]).items():
            peaks[name] = max(peaks.get(name, 0.0), float(score))
    return peaks


def key_for(peaks: Dict[str, float], base: str) -> float:
    return max((v for k, v in peaks.items() if k.startswith(base)), default=0.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--negative-minutes", type=int, default=60)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    from openwakeword.model import Model

    paths = model_paths()
    model = Model(wakeword_models=list(paths.values()))
    work = Path(tempfile.mkdtemp(prefix="basil-bench-wake-"))
    rng = np.random.default_rng(7)
    voices = VOICES[:2] if args.smoke else VOICES
    rates = [175] if args.smoke else [160, 200]
    noise_levels = [None] if args.smoke else [None, 15.0]

    positives: List[Dict[str, Any]] = []
    for target, phrases in POSITIVE_PHRASES.items():
        for phrase in phrases:
            for voice in voices:
                for rate in rates:
                    speech = synth(phrase, voice, rate, work / "p.wav")
                    for snr in noise_levels:
                        clip = np.concatenate([np.zeros(16000, np.float32), speech, np.zeros(16000, np.float32)])
                        if snr is not None:
                            noise = rng.standard_normal(len(clip)).astype(np.float32)
                            signal_power = float(np.mean(speech**2)) + 1e-9
                            clip = clip + noise * np.sqrt(signal_power / (10 ** (snr / 10)))
                        peaks = peak_scores(model, clip)
                        positives.append({"target": target, "phrase": phrase, "voice": voice, "rate": rate, "snr_db": snr, "peaks": peaks})
    print(f"positive clips: {len(positives)}", flush=True)

    confusable_rows: List[Dict[str, Any]] = []
    for phrase in CONFUSABLES[:3] if args.smoke else CONFUSABLES:
        for voice in voices[:5]:
            speech = synth(phrase, voice, 175, work / "c.wav")
            clip = np.concatenate([np.zeros(16000, np.float32), speech, np.zeros(16000, np.float32)])
            confusable_rows.append({"phrase": phrase, "voice": voice, "peaks": peak_scores(model, clip)})

    libri = fetch_librispeech(2000)
    budget = (1 if args.smoke else args.negative_minutes) * 60.0
    fed = 0.0
    false_accepts = {name: 0 for name in paths}
    false_accept_events: List[Dict[str, Any]] = []
    clips_fed = 0
    cpu_start = time.process_time()
    for item in libri:
        if fed >= budget:
            break
        audio, rate = sf.read(item["path"], dtype="float32")
        if rate != 16000:
            continue
        peaks_per_frame: Dict[str, List[float]] = {}
        if hasattr(model, "reset"):
            model.reset()
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        last_hit = {name: -10.0 for name in paths}
        for start in range(0, len(pcm) - FRAME + 1, FRAME):
            t = fed + start / 16000
            for name, score in model.predict(pcm[start : start + FRAME]).items():
                base = next((b for b in paths if name.startswith(b)), name)
                if score > THRESHOLD and t - last_hit.get(base, -10.0) > 1.0:
                    false_accepts[base] = false_accepts.get(base, 0) + 1
                    false_accept_events.append({"model": base, "utterance": item.get("id"), "second_in_utterance": round(start / 16000, 2), "score": round(float(score), 3)})
                    last_hit[base] = t
        fed += len(audio) / 16000
        clips_fed += 1
    cpu_seconds = time.process_time() - cpu_start
    print(f"negative audio fed: {fed / 60:.1f} min; false accepts {false_accepts}", flush=True)

    metrics: Dict[str, Any] = {}
    for base in paths:
        own = [p for p in positives if (p["target"] == "hey basil" and base.startswith("hey_basil")) or (p["target"] == "hey jarvis" and base == "hey_jarvis")]
        if own:
            hits = [1.0 if key_for(p["peaks"], base) > THRESHOLD else 0.0 for p in own]
            metrics[f"{base}_true_accept_rate"] = metric_from_summary(summarize([sum(hits) / len(hits)]), "fraction")
            clean = [h for h, p in zip(hits, own) if p["snr_db"] is None]
            if clean:
                metrics[f"{base}_true_accept_rate_clean"] = metric_from_summary(summarize([sum(clean) / len(clean)]), "fraction")
        confusable_hits = [1.0 if key_for(c["peaks"], base) > THRESHOLD else 0.0 for c in confusable_rows if not (base == "hey_jarvis" and c["phrase"] in ("Hey Jarvis", "A Jarvis"))]
        if confusable_hits:
            metrics[f"{base}_confusable_false_accept_rate"] = metric_from_summary(summarize([sum(confusable_hits) / len(confusable_hits)]), "fraction")
        per_hour = false_accepts[base] / max(fed / 3600.0, 1e-9)
        metrics[f"{base}_false_accepts_per_hour_read_speech"] = metric_from_summary(summarize([per_hour]), "per hour")
    metrics["cpu_seconds_per_audio_second"] = metric_from_summary(summarize([cpu_seconds / max(fed, 1e-9)]), "ratio")

    result = build_result(
        "wake_word_eval",
        mode="smoke" if args.smoke else "full",
        subject={"label": "openwakeword-basil-models", "models": list(paths)},
        parameters={"threshold": THRESHOLD, "negative_minutes_fed": fed / 60.0, "positive_clips": len(positives), "confusable_clips": len(confusable_rows), "voices": voices, "rates_wpm": rates, "noise_snr_db": noise_levels},
        metrics=metrics,
        runs=[{"positives": positives, "confusables": confusable_rows, "false_accepts": false_accepts, "false_accept_events": false_accept_events, "negative_clips_fed": clips_fed}],
        notes=[
            "INVALID FOR THE HEY BASIL MODELS: positives are macOS say voices, and those models were trained on ElevenLabs voices (the owner's finding is that say-style synthesis is barely recognizable and a poor basis for wake-word training or testing), so true-accept rates are not a bound in either direction and must not be quoted for them. The owner reports both Hey Basil models work in daily use, inconsistently. The false-accept results use real recorded speech and stand. Noise is white noise at the stated SNR.",
            "Negatives are clean read speech, not real ambient audio such as music, TV, or meetings; a one-hour figure from real life will differ. False accepts use a one second refractory period, while the app's manager ignores detections for 3 seconds after an accepted one, so per-hour counts here are an upper bound on triggers per model.",
            "The app's own wake-word manager adds gating (capture in progress, frontend state) that is not exercised here. CPU is the detector alone on one core of this machine; microphone capture and resampling are not included.",
        ],
    )
    print(f"wrote {write_result(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
