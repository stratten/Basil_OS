#!/usr/bin/env python3
"""Measure what it costs to hold several instances of one local GGUF at once.

Question this answers: could Basil run a scheduled background task and a
foreground task on two instances of the same model at the same time, instead
of making one wait for the other? That depends on how much memory a second
instance really adds, and whether two instances generate faster than one.

This is a MEASUREMENT SPIKE. It is not wired into the app and nothing in Basil
calls it. It loads real models, so it uses real memory and takes a while; run it
only on purpose, with the app closed.

What it does, for one model:

1. Builds the same llama.cpp load plan the app uses (so context size, GPU layers
   and threads match production).
2. Loads instance 1, then instance 2, ... up to ``--max-instances``, recording
   resident memory after each load and the load time.
3. Optionally (``--generate``) runs the same short prompt on one instance, then
   on all instances at the same time, to compare tokens per second.
4. Closes every instance and reports whether memory came back down.
5. Compares the result with the machine's local-model memory budget and prints
   a plain-language verdict.

Usage (from the repository root, with the backend virtual environment)::

    PYTHONPATH=backend/src .venv/bin/python scripts/measure_llama_multi_instance.py \\
        --model-id Qwen-qwen3-8b-instruct-q4km --max-instances 2 --generate

Memory numbers are the process's resident set size (RSS). Weights are usually
memory-mapped and shared between instances of the same file, so the second
instance is expected to add roughly its KV cache and compute buffers, not
another full copy of the weights. The measurement is what confirms or
contradicts that on this machine.
"""

from __future__ import annotations

import argparse
import gc
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

GIB = 1024**3


def resident_bytes() -> int:
    """Resident memory of this process in bytes."""
    try:
        import psutil  # type: ignore

        return int(psutil.Process(os.getpid()).memory_info().rss)
    except ImportError:
        import subprocess

        output = subprocess.check_output(["ps", "-o", "rss=", "-p", str(os.getpid())], text=True)
        return int(output.strip()) * 1024


def gib(value: float) -> str:
    return f"{value / GIB:.2f} GiB"


@dataclass
class Step:
    label: str
    resident: int
    seconds: float = 0.0
    note: str = ""


@dataclass
class Report:
    steps: List[Step] = field(default_factory=list)
    tokens_per_second: Dict[str, float] = field(default_factory=dict)

    def add(self, step: Step) -> None:
        self.steps.append(step)
        extra = f"  ({step.note})" if step.note else ""
        took = f"  took {step.seconds:.1f}s" if step.seconds else ""
        print(f"  {step.label:<34} resident {gib(step.resident)}{took}{extra}", flush=True)


def resolve_model_path(args: argparse.Namespace) -> Path:
    if args.model_path:
        return Path(args.model_path).expanduser().resolve()

    from api.core.models.models_registry import get_model
    from api.settings import get_settings

    config = get_model(args.model_id)
    if not config:
        raise SystemExit(f"Unknown model id: {args.model_id}")
    models_dir = Path(args.models_dir).expanduser() if args.models_dir else Path(get_settings().models_dir)
    primary = config.get("primary_artifact")
    root = config.get("artifact_root")
    if primary and root:
        path = models_dir / root / primary
    else:
        on_disk = config.get("on_disk_name") or args.model_id
        matches = sorted(models_dir.glob(f"{on_disk}*"))
        if not matches:
            raise SystemExit(f"No file starting with {on_disk} in {models_dir}")
        path = matches[0]
    if not path.is_file():
        raise SystemExit(f"Model file not found: {path}")
    return path


def build_kwargs(args: argparse.Namespace, model_path: Path) -> Dict[str, Any]:
    from api.core.models.models_registry import get_model
    from api.core.runtime.hardware_capability_service import HardwareCapabilityService
    from api.core.runtime.llama_cpp_load_plan import build_llama_cpp_load_plan

    profile = HardwareCapabilityService().get_profile()
    registry_config = get_model(args.model_id) if args.model_id else {}
    plan = build_llama_cpp_load_plan(
        hardware_profile=profile,
        registry_config=registry_config or {},
        gguf_context_window=None,
        default_context_window=args.n_ctx or 8192,
    )
    kwargs = plan.to_llama_kwargs(model_path)
    if args.n_ctx:
        kwargs["n_ctx"] = args.n_ctx
    print(
        f"Load plan: n_ctx={kwargs['n_ctx']} n_gpu_layers={kwargs['n_gpu_layers']} "
        f"n_threads={kwargs['n_threads']} use_mlock={kwargs['use_mlock']}"
    )
    print(
        f"Machine: {profile.total_ram_gb} GB RAM, local-model memory budget "
        f"{profile.local_model_memory_budget_gb} GB"
    )
    return kwargs


def generate(llm: Any, prompt: str, max_tokens: int) -> int:
    result = llm.create_chat_completion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=0.0,
    )
    usage = result.get("usage") or {}
    return int(usage.get("completion_tokens") or 0)


def measure_throughput(instances: List[Any], prompt: str, max_tokens: int) -> float:
    """Tokens per second across all instances generating at the same time."""
    totals = [0] * len(instances)

    def run(index: int) -> None:
        totals[index] = generate(instances[index], prompt, max_tokens)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(len(instances))]
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = max(time.perf_counter() - started, 1e-6)
    return sum(totals) / elapsed


def verdict(report: Report, budget_gb: int, max_instances: int) -> List[str]:
    lines: List[str] = []
    loads = [step for step in report.steps if step.label.startswith("loaded instance")]
    if len(loads) < 2:
        return ["Only one instance was measured, so there is nothing to compare."]
    baseline = next(step.resident for step in report.steps if step.label == "baseline (no model)")
    first = loads[0].resident - baseline
    added = loads[1].resident - loads[0].resident
    lines.append(f"First instance costs about {gib(first)}.")
    lines.append(f"A second instance adds about {gib(added)} ({added / max(first, 1):.0%} of the first).")
    budget_bytes = budget_gb * GIB
    if loads[1].resident - baseline <= budget_bytes:
        lines.append(f"Two instances fit inside this machine's {budget_gb} GB local-model budget.")
    else:
        lines.append(f"Two instances exceed this machine's {budget_gb} GB local-model budget.")
    single = report.tokens_per_second.get("one instance")
    both = report.tokens_per_second.get(f"{len(loads)} instances")
    if single and both:
        lines.append(
            f"Throughput: {single:.1f} tok/s with one instance, {both:.1f} tok/s total with "
            f"{len(loads)} generating together ({both / single:.2f}x)."
        )
        if both / single < 1.25:
            lines.append(
                "Running two at once barely helps total throughput: the work competes for the same "
                "GPU/CPU, so a second instance mostly trades latency between tasks."
            )
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--model-id", help="Registry id of an installed local model")
    source.add_argument("--model-path", help="Path to a GGUF file")
    parser.add_argument("--models-dir", help="Basil models directory (default: the app's setting)")
    parser.add_argument("--max-instances", type=int, default=2, help="How many instances to load (default 2)")
    parser.add_argument("--n-ctx", type=int, default=0, help="Override the context size from the load plan")
    parser.add_argument("--generate", action="store_true", help="Also compare generation speed")
    parser.add_argument("--max-tokens", type=int, default=96, help="Tokens to generate per instance")
    args = parser.parse_args()

    if args.max_instances < 2:
        parser.error("--max-instances must be at least 2 to compare anything")

    try:
        from llama_cpp import Llama
    except ImportError as exc:
        raise SystemExit(f"llama-cpp-python is not installed in this environment: {exc}")

    model_path = resolve_model_path(args)
    print(f"Model file: {model_path} ({gib(model_path.stat().st_size)} on disk)")
    kwargs = build_kwargs(args, model_path)
    prompt = "Explain in three sentences why the sky looks blue during the day."

    report = Report()
    gc.collect()
    report.add(Step("baseline (no model)", resident_bytes()))

    instances: List[Any] = []
    try:
        for index in range(1, args.max_instances + 1):
            started = time.perf_counter()
            instances.append(Llama(**kwargs))
            report.add(
                Step(
                    f"loaded instance {index}",
                    resident_bytes(),
                    seconds=time.perf_counter() - started,
                )
            )

        if args.generate:
            print("Generating (first call warms up and is not counted)...", flush=True)
            generate(instances[0], prompt, 8)
            report.tokens_per_second["one instance"] = measure_throughput(instances[:1], prompt, args.max_tokens)
            report.tokens_per_second[f"{len(instances)} instances"] = measure_throughput(
                instances, prompt, args.max_tokens
            )
            report.add(Step("after generation", resident_bytes(), note="KV cache and buffers now populated"))
    finally:
        for instance in instances:
            try:
                instance.close()
            except Exception as exc:  # noqa: BLE001 - report and keep closing the rest
                print(f"  close failed: {exc}", file=sys.stderr)
        instances.clear()
        gc.collect()
        report.add(Step("after closing every instance", resident_bytes()))

    from api.core.runtime.hardware_capability_service import HardwareCapabilityService

    budget_gb = HardwareCapabilityService().get_profile().local_model_memory_budget_gb
    print("\nResult")
    for line in verdict(report, budget_gb, args.max_instances):
        print(f"  - {line}")
    baseline = report.steps[0].resident
    final = report.steps[-1].resident
    print(f"  - Memory after closing is {gib(final - baseline)} above the starting point (should be near zero).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
