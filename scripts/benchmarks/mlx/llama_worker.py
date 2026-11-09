"""llama.cpp engine worker using Basil's production load plan. Runs in the main Basil virtual environment.

Usage: PYTHONPATH=scripts:backend/src .venv/bin/python scripts/benchmarks/mlx/llama_worker.py --model-id Qwen-qwen3-8b-instruct-q4km --n-ctx 33280 --phase speed --out result.json
Context size is passed in so both engines run at the same context.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterator, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from worker_main import worker_main  # noqa: E402


class LlamaEngine:
    def __init__(self, model_id: str, model_path: str, n_ctx: int) -> None:
        self.model_id = model_id
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.llm: Any = None

    def load(self) -> None:
        from benchmarks.llm_bench_llama import load_kwargs, resolve_path
        from llama_cpp import Llama

        path = resolve_path(self.model_id, self.model_path or None)
        self.llm = Llama(**load_kwargs(self.model_id, path, self.n_ctx))

    def encode(self, text: str) -> List[int]:
        return list(self.llm.tokenize(text.encode("utf-8"), add_bos=False))

    def stream(self, ids: List[int], max_tokens: int) -> Iterator[str]:
        self.llm.reset()
        for chunk in self.llm.create_completion(ids, max_tokens=max_tokens, temperature=0.0, stream=True):
            yield chunk["choices"][0]["text"]

    def extra_stats(self) -> dict:
        return {}

    def close(self) -> None:
        if self.llm is not None:
            self.llm.close()
            self.llm = None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-path", default="")
    parser.add_argument("--n-ctx", type=int, default=33280)
    known, _rest = parser.parse_known_args()
    sys.exit(worker_main(LlamaEngine(known.model_id, known.model_path, known.n_ctx), "llama.cpp"))
