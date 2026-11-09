"""Create the isolated MLX benchmark environment outside the repository and outside ~/.basil.

Run: .venv/bin/python scripts/benchmarks/mlx/setup_venv.py
Creates ~/.basil-bench/mlx-venv and installs mlx-lm there. Model weights download into ~/.basil-bench/hf-cache (see run_pair.py), never into ~/.basil.
Nothing in this script touches Basil's own virtual environment, pins, or runtime code.
"""
from __future__ import annotations

import subprocess
import sys
import venv
from pathlib import Path

BENCH_ROOT = Path.home() / ".basil-bench"
VENV_DIR = BENCH_ROOT / "mlx-venv"
PYTHON = VENV_DIR / "bin" / "python"


def main() -> int:
    BENCH_ROOT.mkdir(parents=True, exist_ok=True)
    if not PYTHON.exists():
        print(f"creating {VENV_DIR}")
        venv.EnvBuilder(with_pip=True, clear=False).create(VENV_DIR)
    subprocess.run([str(PYTHON), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=True)
    subprocess.run([str(PYTHON), "-m", "pip", "install", "--quiet", "mlx-lm", "huggingface_hub", "psutil"], check=True)
    out = subprocess.run([str(PYTHON), "-m", "pip", "list", "--format=freeze"], capture_output=True, text=True, check=True).stdout
    wanted = ("mlx", "mlx-lm", "mlx-metal", "transformers", "numpy", "huggingface-hub", "tokenizers")
    for line in out.splitlines():
        if line.split("==")[0].lower() in wanted:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
