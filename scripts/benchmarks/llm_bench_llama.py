"""llama.cpp baseline for one local GGUF model, using Basil's production load plan.

Measures, per context size: load time, resident memory, prefill speed, decode speed at short and deep context, and (optionally) two instances decoding at once.
Prefill speed comes from the time to the first generated token after an uncached prompt of about 75% of the context. Decode speed comes from the time between the first and last streamed token.
Run only with Basil idle (the script samples Basil CPU use before and after each context size and records it) and with enough free memory for the model.

Usage:
    PYTHONPATH=scripts:backend/src .venv/bin/python -m benchmarks.llm_bench_llama --model-id Qwen-qwen3-8b-instruct-q4km
    PYTHONPATH=scripts:backend/src .venv/bin/python -m benchmarks.llm_bench_llama --model-id Qwen-qwen3-30b-a3b-q4km --model-path ~/.basil/models/qwen3-30b-a3b-q4km.gguf
    add --smoke for a one-run correctness check (never reportable).
"""
from __future__ import annotations

import argparse
import gc
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.common.activity import BasilCpuMonitor  # noqa: E402
from benchmarks.common.results import build_result, metric_from_summary, write_result  # noqa: E402
from benchmarks.common.timing import PeakMemorySampler, summarize  # noqa: E402

MONITOR = BasilCpuMonitor()

FILLER = (
    "The harbor town woke slowly each morning as fishing boats returned with their catch, and merchants set out crates of fruit, "
    "bolts of cloth, and barrels of salted fish along the stone quay. Children ran between the stalls while old men argued about "
    "the weather, the price of rope, and whose turn it was to repair the seawall. By noon the market was crowded, and the smell of "
    "bread, tar, and wet rope drifted up the narrow streets toward the church on the hill. "
)
DECODE_PROMPT = "Write a detailed, well structured essay about the history of the printing press and its effect on society."


def basil_cpu_percent(seconds: float = 2.0) -> float:
    """Total CPU percent (one core = 100) used by Basil's backend and client processes, sampled over a short window."""
    procs = []
    me = os.getpid()
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(proc.info["cmdline"] or [])
        except psutil.Error:
            continue
        if proc.info["pid"] != me and ("uvicorn api.main" in cmd or "BasilClient" in cmd):
            procs.append(proc)
    for proc in procs:
        try:
            proc.cpu_percent(None)
        except psutil.Error:
            pass
    time.sleep(seconds)
    total = 0.0
    for proc in procs:
        try:
            total += proc.cpu_percent(None)
        except psutil.Error:
            pass
    return total


def resolve_path(model_id: str, override: Optional[str]) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    from api.core.models.models_registry import get_model
    from api.settings import get_settings

    config = get_model(model_id) or {}
    models_dir = Path(get_settings().models_dir)
    primary, root = config.get("primary_artifact"), config.get("artifact_root")
    if primary and root:
        return models_dir / root / primary
    matches = sorted(models_dir.glob(f"{config.get('on_disk_name') or model_id}*"))
    if not matches:
        raise SystemExit(f"No file for {model_id} in {models_dir}; pass --model-path")
    return matches[0]


def load_kwargs(model_id: str, model_path: Path, n_ctx: int) -> Dict[str, Any]:
    from api.core.models.models_registry import get_model
    from api.core.runtime.hardware_capability_service import HardwareCapabilityService
    from api.core.runtime.llama_cpp_load_plan import build_llama_cpp_load_plan

    plan = build_llama_cpp_load_plan(
        hardware_profile=HardwareCapabilityService().get_profile(),
        registry_config=get_model(model_id) or {},
        gguf_context_window=None,
        default_context_window=n_ctx,
    )
    kwargs = plan.to_llama_kwargs(model_path)
    kwargs["n_ctx"] = n_ctx
    kwargs["verbose"] = False
    return kwargs


def filler_tokens(llm: Any, count: int) -> List[int]:
    text = FILLER * (count // 40 + 4)
    tokens = llm.tokenize(text.encode("utf-8"), add_bos=True)
    return tokens[:count]


def timed_generation(llm: Any, prompt: Any, max_tokens: int) -> Dict[str, float]:
    """Stream one uncached generation. Returns time to first token, decode tokens per second, and tokens produced."""
    llm.reset()
    started = time.perf_counter()
    first = last = None
    produced = 0
    for _chunk in llm.create_completion(prompt, max_tokens=max_tokens, temperature=0.0, stream=True):
        now = time.perf_counter()
        if first is None:
            first = now
        last = now
        produced += 1
    if first is None or last is None or produced < 2:
        return {"ttft_s": float("nan"), "decode_tps": float("nan"), "tokens": float(produced)}
    return {"ttft_s": first - started, "decode_tps": (produced - 1) / max(last - first, 1e-9), "tokens": float(produced)}


def concurrent_decode(instances: List[Any], prompt_tokens: List[int], max_tokens: int) -> float:
    totals = [0] * len(instances)

    def work(index: int) -> None:
        instances[index].reset()
        count = 0
        for _chunk in instances[index].create_completion(prompt_tokens, max_tokens=max_tokens, temperature=0.0, stream=True):
            count += 1
        totals[index] = count

    threads = [threading.Thread(target=work, args=(i,)) for i in range(len(instances))]
    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return sum(totals) / max(time.perf_counter() - started, 1e-9)


def until_quiet(run_once: Any, attempts: int = 3) -> Dict[str, Any]:
    """Run once and attach the Basil CPU window; retry up to `attempts` times while Basil was busy, keeping the first quiet run or else the last one (flagged busy)."""
    row: Dict[str, Any] = {}
    for attempt in range(attempts):
        t0 = time.perf_counter()
        row = {**run_once(), **MONITOR.window(t0, time.perf_counter()), "attempt": attempt + 1}
        if not row["busy"]:
            break
    return row


def bench_context(model_id: str, model_path: Path, n_ctx: int, runs: int, decode_tokens: int, concurrent: bool) -> Dict[str, Any]:
    from llama_cpp import Llama

    cpu_before = basil_cpu_percent()
    gc.collect()
    with PeakMemorySampler() as memory:
        started = time.perf_counter()
        llm = Llama(**load_kwargs(model_id, model_path, n_ctx))
        load_seconds = time.perf_counter() - started
        resident_after_load_mb = memory.current_mb()
        short_prompt = llm.tokenize(DECODE_PROMPT.encode("utf-8"), add_bos=True)
        deep_target = int(n_ctx * 0.75)
        deep_prompt = filler_tokens(llm, deep_target)
        deep_decode = min(decode_tokens, n_ctx - deep_target - 8)
        timed_generation(llm, short_prompt, 8)  # warm-up, discarded
        short, deep = [], []
        for _ in range(runs):
            short.append(until_quiet(lambda: timed_generation(llm, short_prompt, decode_tokens)))
        for _ in range(runs):
            deep.append(until_quiet(lambda: timed_generation(llm, deep_prompt, deep_decode)))
        concurrent_rows: List[Dict[str, Any]] = []
        resident_after_runs_mb = memory.current_mb()
        if concurrent:
            second = Llama(**load_kwargs(model_id, model_path, n_ctx))
            try:
                for _ in range(max(1, runs // 2)):
                    concurrent_rows.append(until_quiet(lambda: {"tps": concurrent_decode([llm, second], short_prompt, decode_tokens)}))
            finally:
                second.close()
        peak_mb = memory.peak_mb
        llm.close()
    del llm
    gc.collect()
    cpu_after = basil_cpu_percent()
    valid = lambda rows, key, keep_busy: [r[key] for r in rows if r[key] == r[key] and (keep_busy or not r["busy"])]  # noqa: E731 - drops NaN and, unless asked, busy runs
    for r in deep:
        r["prefill_tps"] = len(deep_prompt) / r["ttft_s"] if r["ttft_s"] == r["ttft_s"] else float("nan")
    return {
        "n_ctx": n_ctx,
        "load_seconds": load_seconds,
        "resident_after_load_mb": resident_after_load_mb,
        "resident_after_runs_mb": resident_after_runs_mb,
        "peak_rss_mb": peak_mb,
        "short_decode_tps": valid(short, "decode_tps", False),
        "short_decode_tps_all": valid(short, "decode_tps", True),
        "short_tokens": valid(short, "tokens", True),
        "deep_prompt_tokens": len(deep_prompt),
        "deep_prefill_tps": valid(deep, "prefill_tps", False),
        "deep_prefill_tps_all": valid(deep, "prefill_tps", True),
        "deep_decode_tps": valid(deep, "decode_tps", False),
        "deep_decode_tps_all": valid(deep, "decode_tps", True),
        "concurrent_two_instance_tps": [r["tps"] for r in concurrent_rows if not r["busy"]] or None,
        "concurrent_two_instance_tps_all": [r["tps"] for r in concurrent_rows] or None,
        "busy_runs_excluded": sum(1 for r in short + deep + concurrent_rows if r["busy"]),
        "total_runs": len(short) + len(deep) + len(concurrent_rows),
        "basil_cpu_max_during_runs": max([r["max"] for r in short + deep + concurrent_rows] or [0.0]),
        "basil_cpu_percent_before": cpu_before,
        "basil_cpu_percent_after": cpu_after,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-path")
    parser.add_argument("--label", help="Subject label (default: the model id)")
    parser.add_argument("--quantization", default="Q4_K_M")
    parser.add_argument("--ctx-sizes", default="2048,8192,32768")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--decode-tokens", type=int, default=128)
    parser.add_argument("--concurrent-ctx", type=int, default=8192, help="Context size at which to also run two instances at once (0 disables)")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    ctx_sizes = [int(v) for v in args.ctx_sizes.split(",")]
    runs, decode_tokens = args.runs, args.decode_tokens
    if args.smoke:
        ctx_sizes, runs, decode_tokens = [2048], 1, 32
    model_path = resolve_path(args.model_id, args.model_path)
    print(f"model {model_path} ({model_path.stat().st_size / 1e9:.1f} GB), contexts {ctx_sizes}, runs {runs}", flush=True)

    MONITOR.start()
    per_context = []
    for n_ctx in ctx_sizes:
        print(f"-- n_ctx {n_ctx}", flush=True)
        row = bench_context(args.model_id, model_path, n_ctx, runs, decode_tokens, concurrent=(n_ctx == args.concurrent_ctx and not args.smoke))
        per_context.append(row)
        med = lambda values: summarize(values)["median"]  # noqa: E731
        print(
            f"   load {row['load_seconds']:.1f}s  short decode {med(row['short_decode_tps'])}  "
            f"deep prefill {med(row['deep_prefill_tps'])}  deep decode {med(row['deep_decode_tps'])}  "
            f"peak {row['peak_rss_mb'] / 1024:.1f} GB  basil cpu max {row['basil_cpu_max_during_runs']:.0f}%  busy runs excluded {row['busy_runs_excluded']}/{row['total_runs']}",
            flush=True,
        )
    MONITOR.stop()

    metrics: Dict[str, Any] = {}

    def add_metric(key: str, values: List[float], unit: str) -> None:
        if values:
            metrics[key] = metric_from_summary(summarize(values), unit)

    excluded_total = sum(row["busy_runs_excluded"] for row in per_context)
    for row in per_context:
        tag = f"ctx{row['n_ctx']}"
        add_metric(f"{tag}_load_time", [row["load_seconds"]], "s")
        add_metric(f"{tag}_short_decode", row["short_decode_tps"], "tok/s")
        add_metric(f"{tag}_deep_prefill", row["deep_prefill_tps"], "tok/s")
        add_metric(f"{tag}_deep_decode", row["deep_decode_tps"], "tok/s")
        add_metric(f"{tag}_peak_rss", [row["peak_rss_mb"] / 1024], "GB")
        add_metric(f"{tag}_two_instance_aggregate_decode", row["concurrent_two_instance_tps"] or [], "tok/s")
    result = build_result(
        "llm_bench_llama",
        mode="smoke" if args.smoke else "full",
        subject={"label": args.label or args.model_id, "model_id": args.model_id, "model_file": model_path.name, "quantization": args.quantization, "engine": "llama-cpp-python"},
        parameters={"ctx_sizes": ctx_sizes, "runs": runs, "decode_tokens": decode_tokens, "deep_prompt_fraction_of_ctx": 0.75, "temperature": 0.0, "load_plan": "build_llama_cpp_load_plan (production)", "basil_state": "backend and client running; busy runs excluded by CPU sampling"},
        metrics=metrics,
        runs=per_context,
        notes=[
            "Prefill speed is prompt tokens divided by time to first token for an uncached prompt, so it includes one decode step. Decode speed is tokens after the first divided by streaming time.",
            "Peak RSS is the benchmark process only; Metal buffers are unified memory and may not be fully attributed to RSS.",
            "Basil's backend and client were running. Their combined CPU was sampled every second; a run during which it exceeded 100 percent of one core was excluded from the medians (the unfiltered values are kept in runs as the *_all lists). A metric is missing when every run for it was excluded.",
            f"Runs excluded for Basil activity across all contexts: {excluded_total}.",
        ],
    )
    print(f"wrote {write_result(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
