"""Synthetic-voice meeting ground truth: a known three-speaker script, spoken with distinct macOS voices, transcribed by a local engine, plus a dry-run of the Meeting Companion gate over the true turn timings.

What it measures: word error rate for the whole concatenated meeting audio (one continuous stream, as a meeting recording would be) and per speaker turn; and how often and why the Companion gate would evaluate over the scripted timeline (no model is called, so this is trigger behavior, not suggestion quality).
What it does not measure: speaker diarization (the turns are transcribed from known boundaries, not separated from mixed audio), live capture through the app, or Companion suggestion precision (needs a model). Voices are synthetic, so word error rates bound real-meeting accuracy from above.

Usage: PYTHONPATH=scripts:backend/src .venv/bin/python -m benchmarks.meeting_ground_truth [--engine parakeet-v3-quantized]
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.common.results import build_result, metric_from_summary, write_result  # noqa: E402
from benchmarks.common.timing import summarize  # noqa: E402
from benchmarks.common.wer import corpus_wer  # noqa: E402
from benchmarks.dictation_wer import build_engine, ENGINES  # noqa: E402

PAUSE_SECONDS = 0.8

# (speaker, voice, text). The script contains two direct questions, one action item, and one named decision so the Companion gate has realistic material.
SCRIPT: List[Tuple[str, str, str]] = [
    ("Priya", "Samantha", "Thanks everyone for joining. Today we need to decide the release date for the billing service."),
    ("Daniel", "Daniel", "I think the engineering work is done, but the migration script still needs a rehearsal on the staging database."),
    ("Karen", "Karen", "Can someone tell me how long the rehearsal usually takes? Last time it ran for almost three hours."),
    ("Daniel", "Daniel", "It should be closer to ninety minutes now that we added the parallel loader."),
    ("Priya", "Samantha", "Good. What is the risk if we ship on Friday instead of waiting until Monday?"),
    ("Karen", "Karen", "Support has two people out on Friday, so any incident would be slow to handle. I would rather wait for Monday."),
    ("Daniel", "Daniel", "Then Monday it is. I will run the rehearsal on Thursday and post the results in the channel."),
    ("Priya", "Samantha", "Decision recorded. We ship the billing service on Monday the ninth. Daniel owns the rehearsal, and Karen will brief support."),
    ("Karen", "Karen", "Agreed. I will send the briefing to the support team on Friday morning."),
    ("Priya", "Samantha", "Great, that is everything. Thanks all."),
]


def synth(text: str, voice: str, path: Path) -> np.ndarray:
    subprocess.run(["say", "-v", voice, "-r", "175", "-o", str(path), "--data-format=LEI16@16000", text], check=True, capture_output=True)
    audio, _rate = sf.read(str(path), dtype="float32")
    return audio if audio.ndim == 1 else audio.mean(axis=1)


async def gate_dry_run(timeline: List[Dict[str, Any]]) -> Dict[str, Any]:
    from api.services.meeting_companion.replay import replay, segments_to_turns

    segments = [{"start": row["start"], "end": row["end"], "text": row["text"], "speaker": "microphone" if row["speaker"] == "Priya" else row["speaker"]} for row in timeline]
    turns = segments_to_turns(segments)
    report = await replay(turns, mode="active")
    return {"turn_count": report.turn_count, "seconds_covered": report.seconds_covered, "trigger_counts": report.trigger_counts, "steps": [{"time": s.time, "trigger": s.trigger, "reason": s.reason} for s in report.steps]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--engine", default="parakeet-v3-quantized", choices=sorted(ENGINES))
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="basil-bench-meeting-"))
    kind, model_id = ENGINES[args.engine]
    load, transcribe, unload = build_engine(kind, model_id)

    clips: List[np.ndarray] = []
    timeline: List[Dict[str, Any]] = []
    cursor = 0.0
    silence = np.zeros(int(PAUSE_SECONDS * 16000), np.float32)
    for index, (speaker, voice, text) in enumerate(SCRIPT):
        audio = synth(text, voice, work / f"t{index}.wav")
        timeline.append({"index": index, "speaker": speaker, "text": text, "start": cursor, "end": cursor + len(audio) / 16000})
        clips.extend([audio, silence])
        cursor += len(audio) / 16000 + PAUSE_SECONDS
    full = np.concatenate(clips)
    sf.write(str(work / "meeting.wav"), full, 16000)

    def run(audio: np.ndarray, name: str) -> str:
        path = work / name
        sf.write(str(path), audio, 16000)
        return transcribe(audio, str(path))

    load()
    run(full[: 16000 * 3], "warm.wav")
    whole_hypothesis = run(full, "meeting.wav")
    per_turn = []
    for row in timeline:
        segment = full[int(row["start"] * 16000) : int(row["end"] * 16000)]
        per_turn.append({"speaker": row["speaker"], "reference": row["text"], "hypothesis": run(segment, f"seg{row['index']}.wav")})
    unload()

    reference_all = " ".join(row["text"] for row in timeline)
    wer_whole = corpus_wer([(reference_all, whole_hypothesis)])
    wer_turns = corpus_wer([(row["reference"], row["hypothesis"]) for row in per_turn])
    by_speaker = {name: corpus_wer([(r["reference"], r["hypothesis"]) for r in per_turn if r["speaker"] == name]) for name in sorted({r["speaker"] for r in per_turn})}
    gate = asyncio.run(gate_dry_run(timeline))
    print(f"engine {args.engine}: whole-stream WER {wer_whole:.3f}, per-turn WER {wer_turns:.3f}, by speaker {by_speaker}")
    print(f"companion gate over {gate['turn_count']} turns / {gate['seconds_covered']:.0f}s: {gate['trigger_counts']}")

    metrics: Dict[str, Any] = {
        "wer_whole_stream": metric_from_summary(summarize([wer_whole]), "fraction"),
        "wer_per_turn": metric_from_summary(summarize([wer_turns]), "fraction"),
        "meeting_audio_seconds": metric_from_summary(summarize([float(len(full) / 16000)]), "s"),
        "companion_gate_evaluations": metric_from_summary(summarize([float(len(gate["steps"]))]), "count"),
    }
    for name, value in by_speaker.items():
        metrics[f"wer_speaker_{name.lower()}"] = metric_from_summary(summarize([value]), "fraction")
    result = build_result(
        "meeting_ground_truth",
        mode="full",
        subject={"label": f"{args.engine} on a synthetic three-speaker meeting", "engine": args.engine},
        parameters={"turns": len(SCRIPT), "voices": sorted({v for _s, v, _t in SCRIPT}), "pause_seconds": PAUSE_SECONDS},
        metrics=metrics,
        runs=[{"timeline": timeline, "whole_hypothesis": whole_hypothesis, "per_turn": per_turn, "companion_gate": gate}],
        notes=[
            "Synthetic voices, clean audio, no overlap or crosstalk: word error rates are an optimistic bound. One meeting, one run: no spread.",
            "Diarization and live capture were not exercised; per-turn transcription starts from known boundaries. The Companion result is gate behavior over the true timeline with no model call, not suggestion precision.",
        ],
    )
    print(f"wrote {write_result(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
