"""Render the tool-call and quality prompts once with the model's own chat template so both engines receive byte-identical prompt text.

Runs inside ~/.basil-bench/mlx-venv. Only the tokenizer and template files are fetched (a few MB), never the weights.
Usage: HF_HOME=~/.basil-bench/hf-cache ~/.basil-bench/mlx-venv/bin/python render_prompts.py --repo mlx-community/Qwen3-8B-4bit --out rendered.json
Thinking is disabled through the template's enable_thinking switch so every case measures the answer, not a reasoning trace.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import quality_cases  # noqa: E402
import tool_cases  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer

    path = snapshot_download(args.repo, allow_patterns=["*.json", "*.jinja", "*.txt", "tokenizer*", "vocab*", "merges*", "*.model"])
    tokenizer = AutoTokenizer.from_pretrained(path)

    rendered = {}
    for case_id, user_message, _tool, _args in tool_cases.CASES:
        messages = [{"role": "system", "content": tool_cases.SYSTEM}, {"role": "user", "content": user_message}]
        rendered[case_id] = tokenizer.apply_chat_template(messages, tools=tool_cases.TOOLS, add_generation_prompt=True, tokenize=False, enable_thinking=False)
    for case_id, _category, prompt, _check in quality_cases.CASES:
        messages = [{"role": "user", "content": prompt}]
        rendered[case_id] = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False, enable_thinking=False)

    Path(args.out).write_text(json.dumps(rendered, indent=2))
    print(f"rendered {len(rendered)} prompts; sample tail: {rendered['tc-01'][-120:]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
