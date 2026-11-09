"""Runs Siri 62-test prompts one at a time against the owner's running backend and records the evidence the protocol asks for (see `local/w. Documentation/b.Benchmark_Tracking/Siri_62/Siri62_Protocol.md`).

Each request uses the product's default approval policy (no override), so a test that needs an approval stops at `awaiting_user_input` and is recorded as blocked for a person to answer in the app. Nothing here approves, sends, or retries. One prompt per call, one result file per run.

Usage:
    PYTHONPATH=scripts:backend/src .venv/bin/python -m benchmarks.siri62_run --arm A --test 13
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.core.security.backend_credentials import BACKEND_TOKEN_HEADER, load_host_token  # noqa: E402
from benchmarks.common.results import build_result, write_result  # noqa: E402

BASE_URL = "http://127.0.0.1:8000"
ARMS = {"A": "claude-sonnet-5-5", "B": "Qwen-qwen3-30b-a3b-q4km", "C": "Qwen-qwen35-9b-q4km"}
TERMINAL = {"completed", "completed_with_warnings", "failed", "partial", "canceled", "error"}
SETTLE_WINDOW_S = 90.0
BLOCKED_AFTER_S = 120.0

# Prompts exactly as in the source doc, with one concrete value only where the doc says "a named spa".
PROMPTS: Dict[int, str] = {
    9: "What's the best driving route from central Amsterdam to Thermen Bussloo?",
    10: "When is the next Khruangbin concert in Europe, and when do tickets go on sale?",
    11: "What is Nate Silver's latest Senate forecast after the midterms?",
    12: "What is Jalen Hurts' prognosis?",
    13: "When and where is the next Grand Prix?",
    14: "Can Max Verstappen still win the championship?",
    59: "What's the latest version of Fantastical on the App Store?",
}


def real_db_path() -> Path:
    return Path.home() / ".basil" / "knowledge_base.db"


def receipts_for(agent_task_id: str) -> List[Dict[str, str]]:
    with sqlite3.connect(f"file:{real_db_path()}?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT service, method, execution_state FROM agent_work_receipts WHERE agent_task_id = ? ORDER BY created_at", (agent_task_id,)).fetchall()
    return [{"service": r[0], "method": r[1], "execution_state": r[2]} for r in rows]


def run_test(test: int, arm: str, timeout_s: float) -> Dict[str, Any]:
    headers = {BACKEND_TOKEN_HEADER: load_host_token()}
    prompt = PROMPTS[test]
    row: Dict[str, Any] = {"test": test, "arm": arm, "model": ARMS[arm], "prompt": prompt}
    started = time.monotonic()
    submitted = requests.post(f"{BASE_URL}/api/v1/agent-tasks/process", json={"agent_task": prompt, "model_id": ARMS[arm]}, headers=headers, timeout=60)
    submitted.raise_for_status()
    agent_task_id = submitted.json().get("agent_task_id")
    row["agent_task_id"] = agent_task_id
    detail: Dict[str, Any] = {}
    first_terminal_at: Optional[float] = None
    awaiting_since: Optional[float] = None
    approvals = 0
    seen_awaiting = False
    while time.monotonic() - started < timeout_s:
        time.sleep(1.0)
        resp = requests.get(f"{BASE_URL}/api/v1/agent-tasks/{agent_task_id}", headers=headers, timeout=15)
        if resp.status_code != 200:
            continue
        detail = resp.json()
        status = detail.get("status")
        if status == "awaiting_user_input":
            if not seen_awaiting:
                approvals += 1
                seen_awaiting = True
                awaiting_since = time.monotonic()
            if time.monotonic() - (awaiting_since or time.monotonic()) > BLOCKED_AFTER_S:
                row["blocked_awaiting_user_input"] = True
                break
            continue
        seen_awaiting = False
        if status not in TERMINAL:
            continue
        if first_terminal_at is None:
            first_terminal_at = time.monotonic()
            row["first_terminal_status"] = status
            row["first_terminal_s"] = round(first_terminal_at - started, 2)
        if detail.get("outcome") or time.monotonic() - first_terminal_at >= SETTLE_WINDOW_S:
            break
    row["wall_s"] = round(time.monotonic() - started, 2)
    row["status"] = detail.get("status")
    row["outcome"] = detail.get("outcome")
    row["answer"] = detail.get("result_message") or ""
    row["error_message"] = detail.get("error_message")
    row["approval_prompts"] = approvals
    row["files_in_answer"] = [f.get("file_name") or f.get("path") for f in (detail.get("files") or [])]
    # The work ledger records only some tool calls and the timeline holds phases, not tool steps, so a zero here means "no ledger receipts"; the answer text and timeline are the cross-check.
    row["timeline_entries"] = len(detail.get("execution_timeline") or [])
    row["timeline_titles"] = [e.get("title") for e in (detail.get("execution_timeline") or []) if e.get("type") == "phase"]
    receipts = receipts_for(agent_task_id)
    row["tool_calls"] = len(receipts)
    row["tools"] = [f"{r['service']}.{r['method']}" for r in receipts]
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arm", required=True, choices=sorted(ARMS))
    parser.add_argument("--test", type=int, action="append", required=True)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--smoke", action="store_true", help="Label the result as a pilot that is not reportable.")
    args = parser.parse_args()
    unknown = [t for t in args.test if t not in PROMPTS]
    if unknown:
        raise SystemExit(f"No prompt defined yet for test(s) {unknown}; add it to PROMPTS after checking the run sheet gate.")
    rows = []
    for test in args.test:
        row = run_test(test, args.arm, args.timeout)
        rows.append(row)
        print(f"test {test} arm {args.arm}: status={row['status']} outcome={row['outcome']} {row['wall_s']}s tools={row['tool_calls']} approvals={row['approval_prompts']}", flush=True)
    result = build_result(
        "siri62_live",
        mode="smoke" if args.smoke else "full",
        subject={"label": f"arm_{args.arm}_{ARMS[args.arm]}", "arm": args.arm, "model_id": ARMS[args.arm]},
        parameters={"tests": args.test, "approval_policy": "product default (no override)", "backend": "owner's running backend on the real profile"},
        metrics={},
        runs=rows,
        notes=["Correctness and richness are scored by a person against Siri62_Protocol.md; this file holds the evidence only."],
    )
    print(f"wrote {write_result(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
