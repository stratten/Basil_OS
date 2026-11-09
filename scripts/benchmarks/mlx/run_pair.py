"""Run one MLX versus llama.cpp model pair end to end and write one result file.

Usage (repository root, main virtual environment):
    PYTHONPATH=scripts:backend/src .venv/bin/python -m benchmarks.mlx.run_pair --pair qwen3-8b [--approve-download] [--smoke]
Steps: render prompts, speed (MLX, then llama.cpp), two simultaneous generations per engine, quality (tool-call suite and 30 fixed prompts), score, write result.
Weights are never downloaded without --approve-download, which is set only after the owner approves the download budget. Measurement runs set HF_HUB_OFFLINE=1.
Nothing here imports MLX into Basil's environment or writes under ~/.basil.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmarks.common.machine import REPO_ROOT  # noqa: E402
from benchmarks.common.results import build_result, metric_from_summary, write_result  # noqa: E402
from benchmarks.common.timing import summarize  # noqa: E402
from benchmarks.mlx import quality_cases, tool_cases  # noqa: E402

BENCH_ROOT = Path.home() / ".basil-bench"
MLX_PYTHON = BENCH_ROOT / "mlx-venv" / "bin" / "python"
HF_HOME = BENCH_ROOT / "hf-cache"
HERE = Path(__file__).resolve().parent

PAIRS: Dict[str, Dict[str, str]] = {
    "qwen35-4b": {"label": "Qwen3.5 4B", "mlx_repo": "mlx-community/Qwen3.5-4B-4bit", "llama_id": "Qwen-qwen35-4b-q4km", "llama_path": ""},
    "qwen3-8b": {"label": "Qwen3 8B", "mlx_repo": "mlx-community/Qwen3-8B-4bit", "llama_id": "Qwen-qwen3-8b-instruct-q4km", "llama_path": ""},
    "qwen35-9b": {"label": "Qwen3.5 9B", "mlx_repo": "mlx-community/Qwen3.5-9B-4bit", "llama_id": "Qwen-qwen35-9b-q4km", "llama_path": str(BENCH_ROOT / "gguf" / "Qwen3.5-9B-Q4_K_M.gguf")},
    "qwen3-30b-a3b": {"label": "Qwen3 30B-A3B Instruct 2507", "mlx_repo": "mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit", "llama_id": "Qwen-qwen3-30b-a3b-q4km", "llama_path": str(BENCH_ROOT / "gguf" / "Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf")},
    "qwen36-35b-a3b": {"label": "Qwen3.6 35B-A3B", "mlx_repo": "mlx-community/Qwen3.6-35B-A3B-4bit", "llama_id": "Qwen-qwen36-35b-a3b-ud-q4km", "llama_path": ""},
}
LENGTHS = [512, 4096, 16384, 32768]
COOL_DOWN_SECONDS = 60


def mlx_env(offline: bool) -> Dict[str, str]:
    env = dict(os.environ, HF_HOME=str(HF_HOME), PYTHONUNBUFFERED="1")
    if offline:
        env["HF_HUB_OFFLINE"] = "1"
    return env


def llama_env() -> Dict[str, str]:
    return dict(os.environ, PYTHONPATH=f"{REPO_ROOT / 'scripts'}:{REPO_ROOT / 'backend' / 'src'}", PYTHONUNBUFFERED="1")


def mlx_cmd(repo: str, phase: str, out: Path, extra: List[str]) -> List[str]:
    return [str(MLX_PYTHON), str(HERE / "mlx_worker.py"), "--repo", repo, "--phase", phase, "--out", str(out)] + extra


def llama_cmd(pair: Dict[str, str], n_ctx: int, phase: str, out: Path, extra: List[str]) -> List[str]:
    return [str(REPO_ROOT / ".venv" / "bin" / "python"), str(HERE / "llama_worker.py"), "--model-id", pair["llama_id"], "--model-path", pair["llama_path"], "--n-ctx", str(n_ctx), "--phase", phase, "--out", str(out)] + extra


def run_to_json(cmd: List[str], env: Dict[str, str], out: Path) -> Dict[str, Any]:
    proc = subprocess.run(cmd, env=env, cwd=REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0 or not out.exists():
        raise SystemExit(f"worker failed ({proc.returncode}): {' '.join(cmd[:4])}\n{proc.stderr[-1500:]}")
    return json.loads(out.read_text())


def run_concurrent(cmds: List[List[str]], envs: List[Dict[str, str]], outs: List[Path], go_file: Path) -> Dict[str, Any]:
    go_file.unlink(missing_ok=True)
    procs = [subprocess.Popen(c, env=e, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for c, e in zip(cmds, envs)]
    for proc in procs:
        for line in proc.stdout:  # type: ignore[union-attr]
            # The llama.cpp worker imports backend code that prints a banner with a literal backslash-n, so READY can follow banner text on the same line.
            if line.strip().endswith("READY"):
                break
    go_file.write_text("go")
    for proc in procs:
        proc.communicate()
    rows = [json.loads(o.read_text()) for o in outs]
    wall = max(r["seconds"] for r in rows)
    return {"aggregate_tps": sum(r["tokens"] for r in rows) / wall, "per_process": rows}


def ensure_weights(repo: str, approved: bool) -> None:
    probe = "from huggingface_hub import snapshot_download as s; s('%s', local_files_only=True)" % repo
    cached = subprocess.run([str(MLX_PYTHON), "-c", probe], env=mlx_env(True), capture_output=True).returncode == 0
    if cached:
        return
    if not approved:
        raise SystemExit(f"Weights for {repo} are not in {HF_HOME}. Download needs --approve-download (owner approval of the download budget).")
    print(f"downloading {repo} into {HF_HOME}", flush=True)
    code = "from huggingface_hub import snapshot_download as s; print(s('%s'))" % repo
    subprocess.run([str(MLX_PYTHON), "-c", code], env=mlx_env(False), check=True)


def llama_available(pair: Dict[str, str]) -> Optional[str]:
    """Return None when the GGUF resolves on disk, otherwise a reason string."""
    code = (
        "from benchmarks.llm_bench_llama import resolve_path; "
        "p = resolve_path('%s', %r or None); print(p if p.is_file() else '')" % (pair["llama_id"], pair["llama_path"])
    )
    proc = subprocess.run([str(REPO_ROOT / ".venv" / "bin" / "python"), "-c", code], env=llama_env(), cwd=REPO_ROOT, capture_output=True, text=True)
    path = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    return None if proc.returncode == 0 and path else f"GGUF for {pair['llama_id']} is not installed under the Basil models directory"


def score_quality(outputs: Dict[str, str]) -> Dict[str, Any]:
    tool_rows = [tool_cases.score(case[0], outputs[case[0]]) for case in tool_cases.CASES]
    quality_rows = [{"case": c[0], "category": c[1], "passed": bool(c[3](outputs[c[0]]))} for c in quality_cases.CASES]
    return {
        "tool_pass": sum(r["passed"] for r in tool_rows),
        "tool_total": len(tool_rows),
        "tool_parse_ok": sum(r["parse_ok"] for r in tool_rows),
        "quality_pass": sum(r["passed"] for r in quality_rows),
        "quality_total": len(quality_rows),
        "tool_rows": tool_rows,
        "quality_rows": quality_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pair", required=True, choices=sorted(PAIRS))
    parser.add_argument("--approve-download", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    pair = PAIRS[args.pair]

    lengths, runs, decode_tokens = LENGTHS, args.runs, 256
    if args.smoke:
        lengths, runs, decode_tokens = [512, 2048], 1, 32
    n_ctx = max(lengths) + decode_tokens + 256
    missing = llama_available(pair)
    print(f"pair {args.pair}: mlx {pair['mlx_repo']} | llama {pair['llama_id']} | lengths {lengths} runs {runs} n_ctx {n_ctx}")
    if args.dry_run:
        print(f"llama side: {missing or 'GGUF present'}")
        return 0
    if missing:
        raise SystemExit(missing)
    ensure_weights(pair["mlx_repo"], args.approve_download)

    work = Path(tempfile.mkdtemp(prefix="basil-bench-pair-"))
    rendered = work / "rendered.json"
    subprocess.run([str(MLX_PYTHON), str(HERE / "render_prompts.py"), "--repo", pair["mlx_repo"], "--out", str(rendered)], env=mlx_env(True), check=True, capture_output=True)

    speed_extra = ["--lengths", ",".join(str(v) for v in lengths), "--decode-tokens", str(decode_tokens), "--runs", str(runs)]
    results: Dict[str, Dict[str, Any]] = {}
    results["mlx_speed"] = run_to_json(mlx_cmd(pair["mlx_repo"], "speed", work / "mlx_speed.json", speed_extra), mlx_env(True), work / "mlx_speed.json")
    time.sleep(0 if args.smoke else COOL_DOWN_SECONDS)
    results["llama_speed"] = run_to_json(llama_cmd(pair, n_ctx, "speed", work / "llama_speed.json", speed_extra), llama_env(), work / "llama_speed.json")
    time.sleep(0 if args.smoke else COOL_DOWN_SECONDS)

    concurrent: Dict[str, Any] = {}
    if not args.smoke:
        go = work / "go"
        outs = [work / "mlx_c0.json", work / "mlx_c1.json"]
        extra = ["--decode-tokens", str(decode_tokens), "--go-file", str(go)]
        concurrent["mlx"] = run_concurrent([mlx_cmd(pair["mlx_repo"], "decode_only", o, extra) for o in outs], [mlx_env(True)] * 2, outs, go)
        time.sleep(COOL_DOWN_SECONDS)
        outs = [work / "llama_c0.json", work / "llama_c1.json"]
        concurrent["llama"] = run_concurrent([llama_cmd(pair, n_ctx, "decode_only", o, extra) for o in outs], [llama_env()] * 2, outs, go)
        time.sleep(COOL_DOWN_SECONDS)

    quality_extra = ["--rendered", str(rendered), "--max-tokens", "256"]
    mlx_q = run_to_json(mlx_cmd(pair["mlx_repo"], "quality", work / "mlx_q.json", quality_extra), mlx_env(True), work / "mlx_q.json")
    llama_q = run_to_json(llama_cmd(pair, n_ctx, "quality", work / "llama_q.json", quality_extra), llama_env(), work / "llama_q.json")
    scores = {"mlx": score_quality(mlx_q["outputs"]), "llama": score_quality(llama_q["outputs"])}
    raw_outputs = {"mlx": mlx_q["outputs"], "llama": llama_q["outputs"]}

    metrics: Dict[str, Any] = {}

    def add(key: str, values: List[float], unit: str) -> None:
        if values:
            metrics[key] = metric_from_summary(summarize(values), unit)

    excluded = {}
    for engine, key in (("mlx", "mlx_speed"), ("llama", "llama_speed")):
        data = results[key]
        excluded[engine] = f"{data['busy_runs_excluded']} of {data['total_runs']}"
        add(f"{engine}_load_time", [data["load_seconds"]], "s")
        add(f"{engine}_decode", data["decode_tps_runs"], "tok/s")
        add(f"{engine}_peak_rss", [data["peak_rss_mb"] / 1024], "GB")
        for length, row in data["prefill"].items():
            add(f"{engine}_prefill_{length}", row["tps_runs"], "tok/s")
        if engine in concurrent:
            add(f"{engine}_two_process_aggregate_decode", [concurrent[engine]["aggregate_tps"]], "tok/s")
        s = scores[engine]
        metrics[f"{engine}_toolcall_pass_rate"] = metric_from_summary(summarize([s["tool_pass"] / s["tool_total"]]), "fraction")
        metrics[f"{engine}_quality_pass_rate"] = metric_from_summary(summarize([s["quality_pass"] / s["quality_total"]]), "fraction")

    result = build_result(
        "mlx_vs_llama_pair",
        mode="smoke" if args.smoke else "full",
        subject={"label": pair["label"], "pair": args.pair, "mlx_repo": pair["mlx_repo"], "llama_model_id": pair["llama_id"]},
        parameters={"lengths": lengths, "decode_tokens": decode_tokens, "runs": runs, "n_ctx": n_ctx, "cool_down_seconds": COOL_DOWN_SECONDS, "greedy": True, "thinking": "disabled via chat template", "same_rendered_prompts": True},
        metrics=metrics,
        runs=[{"speed": results, "concurrent": concurrent, "scores": scores, "raw_outputs": raw_outputs}],
        notes=[
            "Quantizations are comparable, not identical: MLX 4-bit (group size 64) versus llama.cpp Q4_K_M or UD-Q4_K_M.",
            "Both engines received byte-identical rendered prompts; llama.cpp ran through Basil's load plan, not its tool-call handler, so this isolates the engine, not the product path.",
            "Two-process concurrency loads the model twice per engine; llama.cpp can share mmap pages, MLX may not, so memory under concurrency is not directly comparable.",
            f"Basil's backend and client were running, which deviates from the plan's Basil-closed control. Their CPU was sampled each second and runs above 100 percent of one core were retried up to three times and, if still busy, excluded from medians. Busy runs excluded in the speed phase: MLX {excluded['mlx']}, llama.cpp {excluded['llama']}. The concurrent and quality phases were not filtered.",
        ],
    )
    print(f"wrote {write_result(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
