"""Render the raw result files into one Markdown report per benchmark.

Usage (from the repository root)::

    PYTHONPATH=scripts .venv/bin/python -m benchmarks.common.render            # writes reports into the Benchmarks folder
    PYTHONPATH=scripts .venv/bin/python -m benchmarks.common.render --include-smoke

The import root is ``benchmarks`` with ``scripts/`` on the path, because the virtual environment ships an unrelated ``scripts`` package.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from .results import benchmarks_dir, load_results


def _format(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3g}" if abs(value) < 1000 else f"{value:,.0f}"
    return str(value)


def render_benchmark(benchmark: str, results: List[Dict[str, Any]]) -> str:
    metric_names: List[str] = []
    for result in results:
        for name in result["metrics"]:
            if name not in metric_names:
                metric_names.append(name)
    lines = [f"# {benchmark}", ""]
    lines.append(
        "Generated from raw JSON in `raw/`. Each cell is the median with the minimum to maximum range in parentheses. "
        "Figures are valid only for the machine named in the row."
    )
    lines.append("")
    header = ["Machine", "Subject", "Mode", "Runs"] + metric_names
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * len(header)) + " |")
    for result in results:
        cells = [
            result["machine"]["machine_id"],
            str(result["subject"].get("label", "")),
            result["mode"],
            str(len(result["runs"])),
        ]
        for name in metric_names:
            metric = result["metrics"].get(name)
            if not metric or metric["median"] is None:
                cells.append("n/a")
                continue
            cells.append(
                f"{_format(metric['median'])} {metric['unit']} ({_format(metric['min'])} to {_format(metric['max'])})"
            )
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    notes = sorted({note for result in results for note in result["notes"]})
    if notes:
        lines.append("Notes:")
        lines.extend(f"- {note}" for note in notes)
        lines.append("")
    lines.append(
        "Machine details: "
        + "; ".join(
            sorted(
                {
                    f"{r['machine']['machine_id']} = {r['machine']['chip']}, {r['machine']['memory_gb']} GB, macOS {r['machine']['macos']}, commit {r['machine']['basil_commit']}"
                    for r in results
                }
            )
        )
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-smoke", action="store_true", help="Include smoke and simulated runs (never quote these as real measurements)")
    args = parser.parse_args()

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for result in load_results():
        if result["reportable"] or args.include_smoke:
            grouped[result["benchmark"]].append(result)

    output_dir: Path = benchmarks_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    for benchmark, results in sorted(grouped.items()):
        path = output_dir / f"report_{benchmark}.md"
        path.write_text(render_benchmark(benchmark, results), encoding="utf-8")
        print(f"wrote {path}")
    if not grouped:
        print("no reportable results found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
