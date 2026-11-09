"""MLX engine worker. Runs inside ~/.basil-bench/mlx-venv; imports nothing from Basil.

Usage (the orchestrator builds these commands): ~/.basil-bench/mlx-venv/bin/python mlx_worker.py --repo mlx-community/Qwen3-8B-4bit --phase speed --out result.json
The Hugging Face cache is taken from HF_HOME, which the orchestrator sets to ~/.basil-bench/hf-cache.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterator, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from worker_main import worker_main  # noqa: E402


class MlxEngine:
    def __init__(self, repo: str) -> None:
        self.repo = repo
        self.model: Any = None
        self.tokenizer: Any = None

    def load(self) -> None:
        from mlx_lm import load

        self.model, self.tokenizer = load(self.repo)

    def encode(self, text: str) -> List[int]:
        return list(self.tokenizer.encode(text))

    def stream(self, ids: List[int], max_tokens: int) -> Iterator[str]:
        from mlx_lm import stream_generate
        from mlx_lm.sample_utils import make_sampler

        for response in stream_generate(self.model, self.tokenizer, prompt=ids, max_tokens=max_tokens, sampler=make_sampler(temp=0.0)):
            yield response.text

    def extra_stats(self) -> dict:
        import mlx.core as mx

        peak = getattr(mx, "get_peak_memory", None) or mx.metal.get_peak_memory
        return {"mlx_peak_metal_mb": peak() / 1048576}

    def close(self) -> None:
        self.model = None
        self.tokenizer = None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--repo", required=True)
    known, _rest = parser.parse_known_args()
    sys.exit(worker_main(MlxEngine(known.repo), "mlx"))
