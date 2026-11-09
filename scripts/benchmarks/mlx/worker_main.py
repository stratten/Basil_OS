"""Shared command-line entry point for both engine workers (standard library plus psutil only)."""
from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import protocol  # noqa: E402


def worker_main(engine: Any, engine_name: str) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["speed", "quality", "decode_only"], required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--lengths", default="512,4096,16384,32768")
    parser.add_argument("--decode-tokens", type=int, default=256)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--rendered", help="JSON file mapping case id to a fully rendered prompt (quality phase)")
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--go-file", default="")
    args, _unknown = parser.parse_known_args()

    peak = protocol.RssPeak().start()
    gc.collect()
    started = time.perf_counter()
    engine.load()
    load_seconds = time.perf_counter() - started
    resident_after_load_mb = peak.peak_mb
    result: dict = {"engine": engine_name, "phase": args.phase, "load_seconds": load_seconds, "resident_after_load_mb": resident_after_load_mb}

    protocol.MONITOR.start()
    if args.phase == "speed":
        lengths = [int(v) for v in args.lengths.split(",")]
        result.update(protocol.measure_speed(engine, lengths, args.decode_tokens, args.runs, peak))
    elif args.phase == "quality":
        rendered = json.loads(Path(args.rendered).read_text())
        result["outputs"] = protocol.run_quality(engine, rendered, args.max_tokens, ["</tool_call>"])
    else:
        result.update(protocol.decode_only(engine, args.decode_tokens, args.go_file))

    protocol.MONITOR.stop()
    result["peak_rss_mb"] = peak.stop()
    result.update(engine.extra_stats())
    engine.close()
    Path(args.out).write_text(json.dumps(result, indent=2))
    print(f"wrote {args.out}", flush=True)
    return 0
