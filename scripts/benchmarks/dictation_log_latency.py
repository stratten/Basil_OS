#!/usr/bin/env python3
"""Measure dictation stop-to-ready latency from Basil backend logs.

For every recording the backend logs "Saved recording as float32 PCM: <wav>" when recording stops and "Entered auto-paste decision block" when the transcript is ready to paste. The gap between them is the stop-to-ready latency. The audio length comes from the WAV header, so latency can be bucketed by how long the user spoke.

Usage (repository root)::

    PYTHONPATH=scripts .venv/bin/python scripts/benchmarks/dictation_log_latency.py --log ~/Desktop/BasilDebugLogs/Basil_Backend_20261103_084342_4e84469e.log
    PYTHONPATH=scripts .venv/bin/python scripts/benchmarks/dictation_log_latency.py --log-dir ~/Desktop/BasilDebugLogs --since 2026-11-03

``--dry-run`` lists the logs that would be read. ``--smoke`` reads only the newest log and does not write a result. Read-only: it never touches the app or the recordings.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.common.results import build_result, metric_from_summary, write_result  # noqa: E402
from benchmarks.common.timing import summarize  # noqa: E402

SAVE_PATTERN = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+) .*Saved recording as float32 PCM: (\S+\.wav)")
READY_PATTERN = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+) .*Entered auto-paste decision block")
SELECTED_MODEL_PATTERN = re.compile(r"'selected_model': '([^']+)'")
BUCKETS: List[Tuple[str, float, float]] = [
    ("under_10s", 0.0, 10.0),
    ("10_to_30s", 10.0, 30.0),
    ("30_to_60s", 30.0, 60.0),
    ("over_60s", 60.0, float("inf")),
]


def parse_timestamp(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S,%f")


def wav_duration_seconds(path: str) -> Optional[float]:
    """Duration of a PCM or float WAV from its header and file size, or None when the file is gone."""
    try:
        file_path = Path(path)
        header = file_path.read_bytes()[:48]
        channels = struct.unpack("<H", header[22:24])[0]
        sample_rate = struct.unpack("<I", header[24:28])[0]
        bits = struct.unpack("<H", header[34:36])[0]
        data_bytes = file_path.stat().st_size - 44
        return data_bytes / (sample_rate * channels * (bits // 8))
    except (OSError, struct.error, ZeroDivisionError):
        return None


def extract_pairs(log_path: Path, since: Optional[datetime]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Pair each stop line with the next ready line. An unmatched stop line is dropped, not guessed at."""
    pairs: List[Dict[str, Any]] = []
    pending: Optional[Tuple[datetime, str]] = None
    selected_model: Optional[str] = None
    with log_path.open(errors="ignore") as handle:
        for line in handle:
            model_match = SELECTED_MODEL_PATTERN.search(line)
            if model_match:
                selected_model = model_match.group(1)
            save_match = SAVE_PATTERN.match(line)
            if save_match:
                pending = (parse_timestamp(save_match.group(1)), save_match.group(2))
                continue
            ready_match = READY_PATTERN.match(line)
            if ready_match and pending is not None:
                stopped_at, wav_path = pending
                pending = None
                if since is not None and stopped_at < since:
                    continue
                latency = (parse_timestamp(ready_match.group(1)) - stopped_at).total_seconds()
                pairs.append(
                    {
                        "stopped_at": stopped_at.isoformat(timespec="seconds"),
                        "audio_seconds": wav_duration_seconds(wav_path),
                        "stop_to_ready_seconds": latency,
                        "log": log_path.name,
                    }
                )
    return pairs, selected_model


def bucket_name(audio_seconds: Optional[float]) -> str:
    if audio_seconds is None:
        return "unknown_length"
    for name, low, high in BUCKETS:
        if low <= audio_seconds < high:
            return name
    return "unknown_length"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", action="append", default=[], help="A backend log file (repeatable)")
    parser.add_argument("--log-dir", help="Directory of Basil_Backend_*.log files")
    parser.add_argument("--since", help="Only count dictations on or after this date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="List the logs that would be read, then exit")
    parser.add_argument("--smoke", action="store_true", help="Read the newest log only and do not write a result")
    args = parser.parse_args()

    logs = [Path(item).expanduser() for item in args.log]
    if args.log_dir:
        found = sorted(Path(args.log_dir).expanduser().glob("Basil_Backend_*.log"), key=lambda p: p.stat().st_mtime)
        logs.extend(found[-1:] if args.smoke else found)
    if not logs:
        parser.error("give --log or --log-dir")
    since = datetime.strptime(args.since, "%Y-%m-%d") if args.since else None

    if args.dry_run:
        for path in logs:
            print(f"would read {path}")
        return 0

    pairs: List[Dict[str, Any]] = []
    models: set[str] = set()
    for path in logs:
        log_pairs, model = extract_pairs(path, since)
        pairs.extend(log_pairs)
        if model:
            models.add(model)
    if not pairs:
        print("no completed dictations found")
        return 1

    for pair in pairs:
        length = f"{pair['audio_seconds']:.1f}" if pair["audio_seconds"] is not None else "?"
        print(f"{pair['stopped_at']}  audio={length:>6}s  stop_to_ready={pair['stop_to_ready_seconds']:.1f}s")

    latencies = [pair["stop_to_ready_seconds"] for pair in pairs]
    metrics: Dict[str, Dict[str, Any]] = {"stop_to_ready": metric_from_summary(summarize(latencies), "s")}
    for name, _low, _high in BUCKETS:
        bucket = [p["stop_to_ready_seconds"] for p in pairs if bucket_name(p["audio_seconds"]) == name]
        if bucket:
            metrics[f"stop_to_ready_{name}"] = metric_from_summary(summarize(bucket), "s")
    ratios = [p["audio_seconds"] / p["stop_to_ready_seconds"] for p in pairs if p["audio_seconds"] and p["stop_to_ready_seconds"] > 0]
    if ratios:
        metrics["times_faster_than_real_time"] = metric_from_summary(summarize(ratios), "x")
    print(f"\nn={metrics['stop_to_ready']['n']} median={metrics['stop_to_ready']['median']:.2f}s "
          f"min={metrics['stop_to_ready']['min']:.2f}s max={metrics['stop_to_ready']['max']:.2f}s")

    if args.smoke:
        print("smoke mode: result not written")
        return 0

    result = build_result(
        "dictation_log_latency",
        mode="full",
        subject={"label": "+".join(sorted(models)) or "unknown-model", "models_seen_in_settings": sorted(models), "logs": [p.name for p in logs]},
        parameters={"since": args.since, "path": "dictation widget, auto-paste", "interval": "Saved recording to Entered auto-paste decision block"},
        metrics=metrics,
        runs=pairs,
        notes=["Mined from real use, not a controlled run: audio content, model warm state, and background load were not controlled."],
    )
    print(f"wrote {write_result(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
