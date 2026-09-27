#!/usr/bin/env python3
"""Retrospective: would request_analyzer's interpretation have improved output?

For every historical follow-up agent task, replay RequestAnalyzer against the
EXACT context production used (the task's stored accumulated_artifacts, which is
what agent_task_workflow_result_service passes as context['chain_context']), then
record the raw prompt, the interpreted prompt, whether interpretation was
applied, the notes/criteria, and the task's ACTUAL stored outcome/summary so the
applied cases can be judged against what the agent really produced.

The analyzer only runs its LLM interpretation when chain_agentTasks is non-empty
or reference_paths are present (request_analyzer.py:94), so we replay exactly
those cases. The analyzer model is held constant (default reasoning model) as the
experimental control and reported in the output.

Usage:
    poetry run python backend/scripts/analyzer_retrospective.py            # all follow-ups
    poetry run python backend/scripts/analyzer_retrospective.py --limit 20 # first N
    poetry run python backend/scripts/analyzer_retrospective.py --out report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DB_PATH = os.path.expanduser("~/.basil/knowledge_base.db")


def _load_followups(limit: int | None) -> list[dict]:
    """Read follow-up tasks with their stored artifacts + actual outcome."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, chain_sequence_number, root_task_id, previous_task_id,
               transcribed_prompt, original_prompt, status, accumulated_artifacts,
               result_data
        FROM agent_tasks
        WHERE chain_sequence_number > 0 AND accumulated_artifacts IS NOT NULL
        ORDER BY timestamp
        """
    ).fetchall()
    conn.close()

    cases: list[dict] = []
    for row in rows:
        try:
            artifacts = json.loads(row["accumulated_artifacts"]) if row["accumulated_artifacts"] else {}
        except (json.JSONDecodeError, TypeError):
            artifacts = {}
        if not isinstance(artifacts, dict):
            continue
        chain_tasks = artifacts.get("chain_agentTasks") or []
        reference_paths = artifacts.get("reference_paths")
        # Only cases the analyzer would actually interpret.
        if not chain_tasks and not reference_paths:
            continue

        result_summary, outcome = _extract_actual_output(row["result_data"])
        cases.append({
            "id": row["id"],
            "seq": row["chain_sequence_number"],
            "root_task_id": row["root_task_id"],
            "status": row["status"],
            "prompt": row["transcribed_prompt"] or row["original_prompt"] or "",
            "artifacts": artifacts,
            "reference_paths": reference_paths,
            "chain_len": len(chain_tasks),
            "actual_outcome": outcome,
            "actual_summary": result_summary,
        })
        if limit and len(cases) >= limit:
            break
    return cases


def _extract_actual_output(result_data_raw) -> tuple[str, str | None]:
    if not result_data_raw:
        return "", None
    try:
        data = json.loads(result_data_raw) if isinstance(result_data_raw, str) else result_data_raw
    except (json.JSONDecodeError, TypeError):
        return "", None
    if not isinstance(data, dict):
        return "", None
    fr = data.get("finalizer_result") or {}
    summary = ""
    outcome = None
    if isinstance(fr, dict):
        summary = fr.get("summary_text") or ""
        outcome = fr.get("outcome")
    if not summary:
        summary = data.get("response") or ""
    return (summary or "")[:1200], outcome


def _change_ratio(a: str, b: str) -> float:
    """Cheap normalized difference so we can rank how much interpretation changed."""
    import difflib
    if not a and not b:
        return 0.0
    return round(1.0 - difflib.SequenceMatcher(None, a, b).ratio(), 3)


async def _get_analyzer_model():
    from api.dependencies import get_model_service
    from api.core.models.model_types import ModelCapability
    from api.services.model_usage_service import ModelUsageService

    model_service = get_model_service()
    usage = ModelUsageService(model_service)
    model = await usage.get_model_for_task(capabilities={ModelCapability.REASONING})
    return model


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="Cap number of cases (default: all).")
    parser.add_argument("--out", default=str(Path(__file__).parent / "analyzer_retrospective_report.json"))
    args = parser.parse_args()

    from api.services.agent_processing.lifecycle.planning.request_analyzer import RequestAnalyzer

    cases = _load_followups(args.limit)
    print(f"Loaded {len(cases)} interpretable follow-up cases from {DB_PATH}", file=sys.stderr)

    model = await _get_analyzer_model()
    model_id = getattr(model, "model_name", None) or getattr(model, "model_id", None) or str(type(model).__name__)
    print(f"Analyzer model held constant: {model_id}", file=sys.stderr)

    analyzer = RequestAnalyzer(llm_model=model)
    results: list[dict] = []
    applied_count = 0

    for i, case in enumerate(cases, 1):
        context = {
            "chain_context": case["artifacts"],  # production sets this to accumulated_artifacts
            "reference_paths": case["reference_paths"],
        }
        try:
            analysis = await analyzer.analyze_request(case["prompt"], context)
            interpreted = analysis.interpreted_agent_task
            applied = bool(analysis.interpretation_applied)
            notes = list(analysis.interpretation_notes or [])
            criteria = list(analysis.success_criteria or [])
        except Exception as exc:  # noqa: BLE001 - record failures, keep going
            interpreted, applied, notes, criteria = None, False, [f"ERROR: {exc}"], []

        if applied:
            applied_count += 1
        results.append({
            "id": case["id"],
            "seq": case["seq"],
            "status": case["status"],
            "chain_len": case["chain_len"],
            "has_reference_paths": bool(case["reference_paths"]),
            "raw_prompt": case["prompt"],
            "interpreted_prompt": interpreted,
            "interpretation_applied": applied,
            "change_ratio": _change_ratio(case["prompt"], interpreted or case["prompt"]),
            "interpretation_notes": notes,
            "success_criteria": criteria,
            "actual_outcome": case["actual_outcome"],
            "actual_status": case["status"],
            "actual_summary": case["actual_summary"],
        })
        print(f"[{i}/{len(cases)}] {case['id'][:8]} applied={applied} change={results[-1]['change_ratio']}", file=sys.stderr)

    report = {
        "db_path": DB_PATH,
        "analyzer_model": model_id,
        "total_cases": len(results),
        "applied_count": applied_count,
        "applied_rate": round(applied_count / max(len(results), 1), 3),
        "cases": results,
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nWROTE {args.out}", file=sys.stderr)
    print(f"SUMMARY: {applied_count}/{len(results)} interpretation applied "
          f"({report['applied_rate']*100:.0f}%)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
