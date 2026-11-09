"""Apply the pre-registered MLX decision rule to every full mlx_vs_llama_pair result and write one verdict result.

Rule (fixed before any pair was measured; do not edit after seeing data):
  Per pair, MLX meets the rule when ALL hold:
    1. decode speed ratio (MLX median over llama.cpp median) is at least 1.3, OR prefill speed ratio is at least 1.5, where the prefill ratio is the geometric mean of the ratios at 4096 and 16384 prompt tokens;
    2. MLX tool-call pass rate is at least llama.cpp's on the 20-case suite (equal or better);
    3. MLX peak resident memory is at most 1.05 times llama.cpp's (5 percent allowance for measurement noise).
  Overall on one machine: a majority of measured pairs meeting the rule is a provisional hit; otherwise a miss.
  A miss on the M5 Max parks the idea. A provisional hit does not justify in-app handler work until the same harness confirms it on the 32 GB M1 (todo m1-pass).
Run: PYTHONPATH=scripts .venv/bin/python -m benchmarks.mlx.mlx_verdict
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmarks.common.results import build_result, load_results, write_result  # noqa: E402

DECODE_THRESHOLD = 1.3
PREFILL_THRESHOLD = 1.5
MEMORY_ALLOWANCE = 1.05


def median_of(metrics: Dict[str, Any], key: str) -> Optional[float]:
    entry = metrics.get(key)
    return float(entry["median"]) if entry and entry.get("median") is not None else None


def ratio(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return a / b if a is not None and b else None


def evaluate(result: Dict[str, Any]) -> Dict[str, Any]:
    m = result["metrics"]
    decode = ratio(median_of(m, "mlx_decode"), median_of(m, "llama_decode"))
    pf4 = ratio(median_of(m, "mlx_prefill_4096"), median_of(m, "llama_prefill_4096"))
    pf16 = ratio(median_of(m, "mlx_prefill_16384"), median_of(m, "llama_prefill_16384"))
    prefill = math.sqrt(pf4 * pf16) if pf4 and pf16 else None
    tool_mlx, tool_llama = median_of(m, "mlx_toolcall_pass_rate"), median_of(m, "llama_toolcall_pass_rate")
    mem = ratio(median_of(m, "mlx_peak_rss"), median_of(m, "llama_peak_rss"))
    speed_ok = bool((decode and decode >= DECODE_THRESHOLD) or (prefill and prefill >= PREFILL_THRESHOLD))
    tool_ok = tool_mlx is not None and tool_llama is not None and tool_mlx >= tool_llama
    mem_ok = mem is not None and mem <= MEMORY_ALLOWANCE
    return {
        "pair": result["subject"]["label"],
        "decode_ratio": decode,
        "prefill_ratio_geomean_4k_16k": prefill,
        "tool_pass_mlx": tool_mlx,
        "tool_pass_llama": tool_llama,
        "peak_memory_ratio": mem,
        "speed_ok": speed_ok,
        "tool_ok": tool_ok,
        "memory_ok": mem_ok,
        "meets_rule": speed_ok and tool_ok and mem_ok,
    }


def main() -> int:
    pairs = [r for r in load_results() if r["benchmark"] == "mlx_vs_llama_pair" and r["reportable"]]
    if not pairs:
        raise SystemExit("No full mlx_vs_llama_pair results found.")
    rows = [evaluate(r) for r in pairs]
    hits = sum(1 for r in rows if r["meets_rule"])
    provisional_hit = hits * 2 > len(rows)
    for row in rows:
        fmt = lambda v: "n/a" if v is None else f"{v:.2f}"  # noqa: E731
        print(f"{row['pair']:<32} decode {fmt(row['decode_ratio'])}x  prefill {fmt(row['prefill_ratio_geomean_4k_16k'])}x  tool {fmt(row['tool_pass_mlx'])} vs {fmt(row['tool_pass_llama'])}  mem {fmt(row['peak_memory_ratio'])}x  -> {'MEETS' if row['meets_rule'] else 'does not meet'}")
    verdict = "provisional hit (needs M1 confirmation before any handler work)" if provisional_hit else "miss (the idea is parked on this machine)"
    print(f"{hits} of {len(rows)} pairs meet the rule: {verdict}")
    result = build_result(
        "mlx_verdict",
        mode="full",
        subject={"label": "mlx-vs-llama-decision-rule"},
        parameters={"decode_threshold": DECODE_THRESHOLD, "prefill_threshold": PREFILL_THRESHOLD, "memory_allowance": MEMORY_ALLOWANCE, "pairs_measured": len(rows)},
        metrics={"pairs_meeting_rule": {"unit": "pairs", "n": 1, "median": hits, "min": hits, "max": hits, "stdev": 0.0}},
        runs=rows,
        notes=[f"Verdict on this machine only: {verdict}.", "Rule fixed before measurement: decode ratio at least 1.3 or prefill ratio (geometric mean at 4096 and 16384 tokens) at least 1.5, with MLX tool-call pass rate at least llama.cpp's and peak memory at most 1.05 times, on a majority of measured pairs."],
    )
    print(f"wrote {write_result(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
