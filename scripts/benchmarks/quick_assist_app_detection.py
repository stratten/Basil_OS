#!/usr/bin/env python3
"""Table test of the Quick Assist context classifier.

Feeds labeled (app name, OCR text) cases through the real ``AssistantSessionContextEnhancer.enhance_suggestion_context`` and compares the detected context type with what a reasonable person would want. Reports accuracy overall and by group, precision and recall per context type, and lists every miss.

It is offline and deterministic: no model is loaded, no network is used, and personalization is disabled so no database is read. The cases are synthetic, so the result bounds how well the heuristics generalize and does not replace a sample of real screens.

Usage (repository root)::

    PYTHONPATH=scripts:backend/src .venv/bin/python scripts/benchmarks/quick_assist_app_detection.py
    PYTHONPATH=scripts:backend/src .venv/bin/python scripts/benchmarks/quick_assist_app_detection.py --dry-run
    PYTHONPATH=scripts:backend/src .venv/bin/python scripts/benchmarks/quick_assist_app_detection.py --smoke
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "src"))

from benchmarks.common.results import build_result, metric_from_summary, write_result  # noqa: E402
from benchmarks.common.timing import summarize  # noqa: E402
from quick_assist_cases_browser import BROWSER_CASES  # noqa: E402
from quick_assist_cases_native import NATIVE_CASES  # noqa: E402

TYPES = ["email", "social_media", "document", "code", "other"]


def build_enhancer() -> Any:
    """Create the enhancer with personalization disabled so no database or profile is read."""
    sys.modules["api.core.knowledge.personalization_service"] = None  # makes the import inside __init__ fail and be caught
    logging.disable(logging.CRITICAL)
    from api.services.assistant_sessions.context_enhancers.assistant_session_context_enhancer import (
        AssistantSessionContextEnhancer,
    )

    enhancer = AssistantSessionContextEnhancer()

    async def no_personalization(*_args: Any, **_kwargs: Any) -> None:
        return None

    enhancer._get_personalization_context = no_personalization  # type: ignore[method-assign]
    return enhancer


def normalize(detected: str) -> str:
    """Collapse sub-types such as email_compose or code_swift into the five top-level classes."""
    value = (detected or "").lower()
    for prefix, top_level in (("email", "email"), ("social", "social_media"), ("document", "document"), ("code", "code")):
        if value.startswith(prefix):
            return top_level
    return "other"


def classify(enhancer: Any, app_name: str, ocr_text: str) -> Dict[str, str]:
    result = asyncio.run(
        enhancer.enhance_suggestion_context(ocr_text, "reply to this", text_selection=None, app_name=app_name)
    )
    raw = str(result.get("context_type", ""))
    return {"raw": raw, "detected": normalize(raw)}


def fraction(correct: int, total: int) -> float:
    return correct / total if total else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Print the case counts and exit")
    parser.add_argument("--smoke", action="store_true", help="Run five cases and do not write a result")
    args = parser.parse_args()

    cases = list(NATIVE_CASES) + list(BROWSER_CASES)
    if args.dry_run:
        print(f"{len(cases)} cases: {len(NATIVE_CASES)} native, {len(BROWSER_CASES)} browser")
        print("groups:", dict(Counter(case[4] for case in cases)))
        return 0
    if args.smoke:
        cases = cases[:5]

    enhancer = build_enhancer()
    rows: List[Dict[str, Any]] = []
    for case_id, app_name, ocr_text, expected, group, note in cases:
        outcome = classify(enhancer, app_name, ocr_text)
        detected = outcome["detected"]
        rows.append(
            {
                "case_id": case_id,
                "app_name": app_name,
                "group": group,
                "expected": expected,
                "detected": detected,
                "raw_context_type": outcome["raw"],
                "correct": detected == expected,
                "judgment": bool(note),
                "note": note,
            }
        )

    firm = [row for row in rows if not row["judgment"]]
    judgment = [row for row in rows if row["judgment"]]
    metrics: Dict[str, Dict[str, Any]] = {
        "accuracy_firm_labels": metric_from_summary(summarize([fraction(sum(r["correct"] for r in firm), len(firm))]), "fraction"),
        "accuracy_judgment_labels": metric_from_summary(summarize([fraction(sum(r["correct"] for r in judgment), len(judgment))]), "fraction"),
        "accuracy_all": metric_from_summary(summarize([fraction(sum(r["correct"] for r in rows), len(rows))]), "fraction"),
    }
    by_group: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_group[row["group"]].append(row)
    for group, group_rows in sorted(by_group.items()):
        metrics[f"accuracy_group_{group}"] = metric_from_summary(
            summarize([fraction(sum(r["correct"] for r in group_rows), len(group_rows))]), "fraction"
        )
    for kind in TYPES:
        true_positive = sum(1 for r in rows if r["detected"] == kind and r["expected"] == kind)
        predicted = sum(1 for r in rows if r["detected"] == kind)
        actual = sum(1 for r in rows if r["expected"] == kind)
        if predicted:
            metrics[f"precision_{kind}"] = metric_from_summary(summarize([true_positive / predicted]), "fraction")
        if actual:
            metrics[f"recall_{kind}"] = metric_from_summary(summarize([true_positive / actual]), "fraction")

    print(f"cases={len(rows)} firm={len(firm)} judgment={len(judgment)}")
    for name, metric in metrics.items():
        print(f"{name:42s} {metric['median']:.2f}")
    print("\nmisses:")
    for row in rows:
        if not row["correct"]:
            tag = " (judgment)" if row["judgment"] else ""
            print(f"  {row['case_id']:7s} {row['app_name'] or '<none>':22s} expected={row['expected']:12s} detected={row['detected']}{tag}  [{row['group']}]")

    if args.smoke:
        print("smoke mode: result not written")
        return 0

    result = build_result(
        "quick_assist_app_detection",
        mode="full",
        subject={"label": "AssistantSessionContextEnhancer-heuristics", "case_count": len(rows)},
        parameters={"personalization": "disabled", "model_loaded": False, "instruction": "reply to this"},
        metrics=metrics,
        runs=rows,
        notes=[
            "Cases are synthetic, hand-written approximations of OCR output. Treat the numbers as an upper bound on real-world accuracy.",
            "Judgment rows (chat apps, spreadsheets, tickets) have no single right answer. They are reported separately.",
        ],
    )
    print(f"wrote {write_result(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
