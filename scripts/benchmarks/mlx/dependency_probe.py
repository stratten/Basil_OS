#!/usr/bin/env python3
"""Can mlx-lm be installed next to Basil's pinned torch and transformers?

Resolves dependencies with ``pip install --dry-run`` in a throwaway virtual environment under ``~/.basil-bench/probe-venv``. Nothing is installed into Basil's environment, and nothing under ``~/.basil`` is touched. Only package metadata is fetched from PyPI.

Two resolutions are recorded:

1. ``mlx-lm`` alone: what the current release demands of transformers and friends.
2. ``mlx-lm`` together with Basil's pins from ``pyproject.toml`` and ``poetry.lock`` (torch 2.5.1, transformers 4.53.1, huggingface-hub 0.30.x, numpy 1.26.4, tokenizers 0.21.2, safetensors 0.5.3).

Usage (repository root)::

    PYTHONPATH=scripts .venv/bin/python scripts/benchmarks/mlx/dependency_probe.py
    PYTHONPATH=scripts .venv/bin/python scripts/benchmarks/mlx/dependency_probe.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import venv
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmarks.common.results import build_result, write_result  # noqa: E402

PROBE_DIR = Path.home() / ".basil-bench" / "probe-venv"
BASIL_PINS = [
    "torch==2.5.1",
    "transformers==4.53.1",
    "huggingface-hub>=0.30.0,<0.31",
    "numpy==1.26.4",
    "tokenizers==0.21.2",
    "safetensors==0.5.3",
]
SCENARIOS: Dict[str, List[str]] = {
    "mlx_lm_alone": ["mlx-lm"],
    "mlx_lm_with_basil_pins": ["mlx-lm", *BASIL_PINS],
}


def ensure_probe_venv() -> Path:
    python = PROBE_DIR / "bin" / "python"
    if not python.exists():
        PROBE_DIR.parent.mkdir(parents=True, exist_ok=True)
        venv.EnvBuilder(with_pip=True, clear=False).create(PROBE_DIR)
    return python


def resolve(python: Path, requirements: List[str]) -> Dict[str, Any]:
    command = [
        str(python), "-m", "pip", "install", "--dry-run", "--ignore-installed", "--quiet",
        "--report", "-", "--disable-pip-version-check", *requirements,
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=900)
    outcome: Dict[str, Any] = {"requirements": requirements, "returncode": completed.returncode}
    if completed.returncode == 0:
        report = json.loads(completed.stdout)
        outcome["resolved"] = sorted(
            f"{item['metadata']['name']}=={item['metadata']['version']}" for item in report.get("install", [])
        )
    else:
        outcome["error_tail"] = "\n".join(completed.stderr.strip().splitlines()[-12:])
    return outcome


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Print the plan and exit without creating anything")
    args = parser.parse_args()
    if args.dry_run:
        print(f"would create {PROBE_DIR} and resolve:")
        for name, requirements in SCENARIOS.items():
            print(f"  {name}: {' '.join(requirements)}")
        return 0

    python = ensure_probe_venv()
    runs: List[Dict[str, Any]] = []
    for name, requirements in SCENARIOS.items():
        print(f"resolving {name} ...", flush=True)
        outcome = resolve(python, requirements)
        outcome["scenario"] = name
        runs.append(outcome)
        status = "resolved" if outcome["returncode"] == 0 else "FAILED"
        print(f"  {status}")
        if outcome["returncode"] == 0:
            interesting = [r for r in outcome["resolved"] if r.split("==")[0].lower() in {"mlx", "mlx-lm", "mlx-metal", "transformers", "torch", "numpy", "huggingface-hub", "tokenizers"}]
            print("  " + ", ".join(interesting))
        else:
            print("  " + outcome["error_tail"].replace("\n", "\n  "))

    result = build_result(
        "mlx_dependency_probe",
        mode="full",
        subject={"label": "mlx-lm-vs-basil-pins"},
        parameters={"method": "pip install --dry-run in a throwaway venv", "venv": str(PROBE_DIR)},
        metrics={},
        runs=runs,
        notes=["Resolver outcome on the date shown. A resolved set means the pins are not contradictory at the metadata level, not that mlx-lm runs correctly with them."],
    )
    print(f"wrote {write_result(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
