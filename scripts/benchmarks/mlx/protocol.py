"""Engine-neutral measurement protocol shared by the MLX and llama.cpp workers (standard library plus psutil only).

An engine object provides:
    load() -> None
    encode(text: str) -> list[int]
    stream(ids: list[int], max_tokens: int) -> iterator of text pieces, one per generated token
    close() -> None
The same functions drive both engines so timing is computed identically. Prefill speed is prompt tokens divided by time to the first generated token (one decode step is included, for both engines). Decode speed is tokens after the first divided by the time between the first and last token.
"""
from __future__ import annotations

import os
import statistics
import threading
import time
from typing import Any, Dict, List

import sys
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmarks.common.activity import BasilCpuMonitor  # noqa: E402

MONITOR = BasilCpuMonitor()

FILLER = (
    "The harbor town woke slowly each morning as fishing boats returned with their catch, and merchants set out crates of fruit, "
    "bolts of cloth, and barrels of salted fish along the stone quay. Children ran between the stalls while old men argued about "
    "the weather, the price of rope, and whose turn it was to repair the seawall. By noon the market was crowded, and the smell of "
    "bread, tar, and wet rope drifted up the narrow streets toward the church on the hill. "
)
DECODE_PROMPT = "Write a detailed, well structured essay about the history of the printing press and its effect on society."


class RssPeak:
    """Peak resident memory of this process in MB, sampled on a thread."""

    def __init__(self, interval: float = 0.05) -> None:
        self._proc = psutil.Process(os.getpid())
        self._interval = interval
        self._stop = threading.Event()
        self.peak_mb = 0.0
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak_mb = max(self.peak_mb, self._proc.memory_info().rss / 1048576)
            time.sleep(self._interval)

    def start(self) -> "RssPeak":
        self._thread.start()
        return self

    def stop(self) -> float:
        self._stop.set()
        self._thread.join(timeout=1)
        return self.peak_mb


def filler_ids(engine: Any, count: int) -> List[int]:
    ids = engine.encode(FILLER * (count // 40 + 4))
    return ids[:count]


def timed_stream(engine: Any, ids: List[int], max_tokens: int) -> Dict[str, float]:
    started = time.perf_counter()
    first = last = None
    produced = 0
    for _piece in engine.stream(ids, max_tokens):
        now = time.perf_counter()
        first = first if first is not None else now
        last = now
        produced += 1
    if first is None or produced < 2:
        return {"ttft_s": float("nan"), "decode_tps": float("nan"), "tokens": float(produced)}
    return {"ttft_s": first - started, "decode_tps": (produced - 1) / max(last - first, 1e-9), "tokens": float(produced)}


def _median(values: List[float]) -> float:
    clean = [v for v in values if v == v]
    return statistics.median(clean) if clean else float("nan")


def quiet_stream(engine: Any, ids: List[int], max_tokens: int, attempts: int = 3) -> Dict[str, Any]:
    """timed_stream with the Basil CPU window attached; retries while Basil was busy and keeps the first quiet run or else the last one (flagged busy)."""
    row: Dict[str, Any] = {}
    for attempt in range(attempts):
        t0 = time.perf_counter()
        row = {**timed_stream(engine, ids, max_tokens), **MONITOR.window(t0, time.perf_counter()), "attempt": attempt + 1}
        if not row["busy"]:
            break
    return row


def _clean(rows: List[Dict[str, Any]], key: str) -> List[float]:
    return [r[key] for r in rows if r[key] == r[key] and not r["busy"]]


def measure_speed(engine: Any, lengths: List[int], decode_tokens: int, runs: int, peak: RssPeak) -> Dict[str, Any]:
    out: Dict[str, Any] = {"prefill": {}, "memory_peak_mb_after": {}, "busy_runs_excluded": 0, "total_runs": 0}
    short_ids = engine.encode(DECODE_PROMPT)
    timed_stream(engine, short_ids, 8)  # warm-up, discarded
    decode_runs = [quiet_stream(engine, short_ids, decode_tokens) for _ in range(runs)]
    out["decode_tps_runs"] = _clean(decode_runs, "decode_tps")
    out["decode_tps_runs_all"] = [r["decode_tps"] for r in decode_runs]
    out["decode_tokens_runs"] = [r["tokens"] for r in decode_runs]
    out["decode_tps_median"] = _median(out["decode_tps_runs"])
    out["busy_runs_excluded"] += sum(1 for r in decode_runs if r["busy"])
    out["total_runs"] += len(decode_runs)
    for length in lengths:
        ids = filler_ids(engine, length)
        rows = [quiet_stream(engine, ids, 2) for _ in range(runs)]
        for r in rows:
            r["prefill_tps"] = len(ids) / r["ttft_s"] if r["ttft_s"] == r["ttft_s"] else float("nan")
        tps = _clean(rows, "prefill_tps")
        out["prefill"][str(length)] = {"prompt_tokens": len(ids), "tps_runs": tps, "tps_runs_all": [r["prefill_tps"] for r in rows], "tps_median": _median(tps), "ttft_runs": [r["ttft_s"] for r in rows]}
        out["busy_runs_excluded"] += sum(1 for r in rows if r["busy"])
        out["total_runs"] += len(rows)
        out["memory_peak_mb_after"][str(length)] = peak.peak_mb
    return out


def generate_text(engine: Any, ids: List[int], max_tokens: int, stop: List[str]) -> str:
    text = ""
    for piece in engine.stream(ids, max_tokens):
        text += piece
        if any(s in text for s in stop):
            break
    return text


def run_quality(engine: Any, rendered: Dict[str, str], max_tokens: int, stop: List[str]) -> Dict[str, str]:
    outputs: Dict[str, str] = {}
    for case_id, prompt in rendered.items():
        outputs[case_id] = generate_text(engine, engine.encode(prompt), max_tokens, stop)
    return outputs


def decode_only(engine: Any, decode_tokens: int, go_file: str) -> Dict[str, Any]:
    """Concurrent-decode participant: warm up, signal ready, wait for the go file, then decode and report wall-clock timing."""
    short_ids = engine.encode(DECODE_PROMPT)
    timed_stream(engine, short_ids, 8)
    print("READY", flush=True)
    while not os.path.exists(go_file):
        time.sleep(0.01)
    started = time.perf_counter()
    count = sum(1 for _ in engine.stream(short_ids, decode_tokens))
    finished = time.perf_counter()
    return {"tokens": count, "wall_start": time.time() - (finished - started), "seconds": finished - started}
