"""Ten-task agent suite against an isolated Basil backend (B3).

Runs fixture tasks through the real agent pipeline with a pinned local model and records, per run: pass or fail from an outcome verifier, wall time, terminal status, tool receipts from the work ledger, and repetition-guard trips from the backend log. Approvals are pre-approved (`always_approve`) because every task works only inside a temporary directory or the isolated profile's own database, so approvals prompted is not measured.

The backend must be the isolated session started by `start_isolated_backend.sh <session>`. Never point this at the owner's real backend: the script refuses any URL whose port file is not in the session directory, and tasks write real files and a real scheduled-task row.

Usage:
    HOME=<session>/home PYTHONPATH=scripts:backend/src .venv/bin/python -m benchmarks.agent_suite --session agent-suite --model Qwen-qwen3-8b-instruct-q4km --runs 3
    add --task T01 (repeatable) to limit tasks, and --smoke for a one-run check that is never reportable.
"""
from __future__ import annotations

import argparse
import json
import os
import pwd
import random
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.agent_suite_tasks import SuiteTask, build_tasks  # noqa: E402
from benchmarks.common.results import build_result, metric_from_summary, write_result  # noqa: E402
from benchmarks.common.timing import summarize  # noqa: E402

TERMINAL = {"completed", "completed_with_warnings", "failed", "partial", "awaiting_user_input", "canceled", "error"}
GUARD_MARKERS = ("Tool repetition guard stopping run", "Tool repetition guard emitting repair observation")
LOG_DIR = Path("/tmp/basil-bench-logs")
SETTLE_WINDOW_S = 90.0
STALL_WINDOW_S = 180.0
STALL_MIN_CPU_S = 3.0


class Session:
    def __init__(self, session: str) -> None:
        # HOME points at the isolated session when this runs (so the host token resolves there), so the real home comes from the account database.
        real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        base = real_home / "Library" / "Application Support" / "BasilValidation" / "sessions" / session
        if not (base / "port.txt").is_file():
            raise SystemExit(f"No isolated session at {base}; start one first.")
        self.root = base
        self.port = int((base / "port.txt").read_text().strip())
        self.url = f"http://127.0.0.1:{self.port}"
        self.log_path = base / "logs" / "backend.log"
        self.db_path = base / "home" / ".basil" / "knowledge_base.db"
        self.fixtures = base / "fixtures" / "suite"
        from api.core.security.backend_credentials import BACKEND_TOKEN_HEADER, load_host_token

        self.headers = {BACKEND_TOKEN_HEADER: load_host_token()}

    def backend_pid(self) -> Optional[int]:
        result = subprocess.run(["lsof", "-nP", f"-iTCP:{self.port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True)
        pids = [int(p) for p in result.stdout.split() if p.strip().isdigit()]
        return pids[0] if pids else None

    def backend_cpu_seconds(self) -> Optional[float]:
        pid = self.backend_pid()
        if pid is None:
            return None
        try:
            times = psutil.Process(pid).cpu_times()
        except psutil.Error:
            return None
        return times.user + times.system

    def restart_backend(self) -> float:
        """Kill the isolated backend (never any other process) and start it again; returns seconds until ready. Raises if it does not come back."""
        started = time.monotonic()
        pid = self.backend_pid()
        if pid is not None:
            os.kill(pid, signal.SIGTERM)
            for _ in range(20):
                if self.backend_pid() is None:
                    break
                time.sleep(0.5)
            if self.backend_pid() is not None:
                os.kill(pid, signal.SIGKILL)
                time.sleep(1.0)
        script = Path(__file__).resolve().parent / "start_isolated_backend.sh"
        subprocess.Popen([str(script), self.root.name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        token = (self.root / "control-token").read_text().strip()
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            try:
                if requests.get(f"{self.url}/validation/ready", headers={"X-Basil-Validation-Token": token}, timeout=3).status_code == 200:
                    return time.monotonic() - started
            except requests.RequestException:
                pass
            time.sleep(1.0)
        raise SystemExit("Isolated backend did not come back after a restart.")

    def get(self, path: str, timeout: float = 10.0) -> requests.Response:
        return requests.get(f"{self.url}{path}", headers=self.headers, timeout=timeout)

    def post(self, path: str, body: Dict[str, Any], timeout: float = 60.0) -> requests.Response:
        return requests.post(f"{self.url}{path}", json=body, headers=self.headers, timeout=timeout)


def receipts_for(db_path: Path, agent_task_id: str) -> List[Dict[str, str]]:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT service, method, execution_state, verification_status FROM agent_work_receipts WHERE agent_task_id = ? ORDER BY created_at",
            (agent_task_id,),
        ).fetchall()
    return [{"service": r[0], "method": r[1], "execution_state": r[2], "verification_status": r[3]} for r in rows]


def clear_schedule_rows(db_path: Path, marker: str) -> None:
    with sqlite3.connect(str(db_path)) as connection:
        connection.execute("DELETE FROM scheduled_agent_tasks WHERE title LIKE ? OR agent_task_text LIKE ?", (f"%{marker}%", f"%{marker}%"))


def log_slice(session: Session, start: int) -> str:
    with session.log_path.open("rb") as handle:
        handle.seek(start)
        return handle.read().decode("utf-8", "replace")


def run_one(session: Session, task: SuiteTask, model_id: str, run_index: int, timeout_s: float, seed: int) -> Dict[str, Any]:
    marker = uuid.uuid4().hex[:8]
    workdir = session.fixtures / f"{task.task_id}-{marker}"
    workdir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    ctx = task.build(workdir, marker, rng)
    prompt = task.prompt(ctx)
    log_start = session.log_path.stat().st_size
    row: Dict[str, Any] = {"task": task.task_id, "family": task.family, "model": model_id, "run": run_index, "seed": seed, "prompt": prompt}
    started = time.monotonic()
    try:
        submitted = session.post("/api/v1/agent-tasks/process", {"agent_task": prompt, "model_id": model_id, "approval_policy_override": {"approval_mode": "always_approve"}}, timeout=timeout_s)
        submitted.raise_for_status()
        agent_task_id = submitted.json().get("agent_task_id")
        row["agent_task_id"] = agent_task_id
        if not agent_task_id:
            row.update(status="no_task_id", passed=False, detail=str(submitted.json())[:200])
            return row
        detail: Dict[str, Any] = {}
        deadline = started + timeout_s
        first_terminal_at: Optional[float] = None
        cpu_mark = (time.monotonic(), session.backend_cpu_seconds())
        while time.monotonic() < deadline:
            time.sleep(1.0)
            resp = session.get(f"/api/v1/agent-tasks/{agent_task_id}")
            if resp.status_code != 200:
                continue
            detail = resp.json()
            if detail.get("status") not in TERMINAL:
                # Stall check: a live run keeps the backend busy (model load, prefill, decode, tools). A window with almost no CPU while the task is still running is a hang.
                now = time.monotonic()
                if now - cpu_mark[0] >= STALL_WINDOW_S:
                    cpu_now = session.backend_cpu_seconds()
                    if cpu_now is not None and cpu_mark[1] is not None and cpu_now - cpu_mark[1] < STALL_MIN_CPU_S:
                        row.update(stalled=True, stall_cpu_seconds=round(cpu_now - cpu_mark[1], 2), stall_window_s=STALL_WINDOW_S)
                        detail["status"] = "stalled"
                        break
                    cpu_mark = (now, cpu_now)
                continue
            # The pipeline can pass through a transient terminal status (observed: `failed`) and then settle to `completed` once the outcome evaluation returns, so a terminal status is final only when an outcome is recorded or a settle window has passed.
            if first_terminal_at is None:
                first_terminal_at = time.monotonic()
                row["first_terminal_status"] = detail.get("status")
                row["first_terminal_s"] = round(first_terminal_at - started, 2)
            if detail.get("outcome") or time.monotonic() - first_terminal_at >= SETTLE_WINDOW_S:
                break
        else:
            detail["status"] = "timeout"
        row["wall_s"] = round(time.monotonic() - started, 2)
        row["settled_after_terminal"] = row.get("first_terminal_status") is not None and row.get("first_terminal_status") != detail.get("status")
        row["status"] = detail.get("status")
        answer = detail.get("result_message") or detail.get("outcome") or ""
        row["answer"] = answer[:600]
        row["error_message"] = detail.get("error_message")
        row["timeline_events"] = len(detail.get("execution_timeline") or [])
        receipts = receipts_for(session.db_path, agent_task_id)
        row["receipts"] = receipts
        row["tool_calls"] = len(receipts)
        row["receipt_failures"] = sum(1 for item in receipts if item["execution_state"] not in {"succeeded", "success", "completed"})
        pairs = {(item["service"], item["method"]) for item in receipts}
        passed, why = task.verify(ctx, answer, pairs)
        row["outcome"] = detail.get("outcome")
        row["services_used"] = sorted({item["service"] for item in receipts})
        row["outcome_correct"] = bool(passed)
        row["passed"] = bool(passed) and detail.get("status") in {"completed", "completed_with_warnings", "partial"}
        row["detail"] = why if row["passed"] or detail.get("status") in {"completed", "completed_with_warnings", "partial"} else f"{detail.get('status')}: {why}"
    except Exception as exc:  # recorded as a failure of the run, never hidden
        row.update(status="harness_error", passed=False, detail=f"{type(exc).__name__}: {exc}")
        row.setdefault("wall_s", round(time.monotonic() - started, 2))
    finally:
        text = log_slice(session, log_start)
        row["repetition_guard_trips"] = sum(text.count(marker_text) for marker_text in GUARD_MARKERS)
        row["log_bytes"] = len(text)
        clear_schedule_rows(session.db_path, marker)
        shutil.rmtree(workdir, ignore_errors=True)
    return row


def summarize_model(rows: List[Dict[str, Any]], model_id: str) -> Dict[str, Dict[str, Any]]:
    metrics: Dict[str, Dict[str, Any]] = {}
    passes = [1.0 if r["passed"] else 0.0 for r in rows]
    metrics["pass_rate"] = metric_from_summary(summarize(passes), "fraction")
    metrics["wall_seconds"] = metric_from_summary(summarize([r["wall_s"] for r in rows if "wall_s" in r]), "s")
    metrics["tool_calls_per_run"] = metric_from_summary(summarize([float(r.get("tool_calls", 0)) for r in rows]), "calls")
    metrics["repetition_guard_trips_per_run"] = metric_from_summary(summarize([float(r.get("repetition_guard_trips", 0)) for r in rows]), "trips")
    for task_id in sorted({r["task"] for r in rows}):
        task_rows = [r for r in rows if r["task"] == task_id]
        metrics[f"{task_id}_pass_rate"] = metric_from_summary(summarize([1.0 if r["passed"] else 0.0 for r in task_rows]), "fraction")
        metrics[f"{task_id}_wall_seconds"] = metric_from_summary(summarize([r["wall_s"] for r in task_rows if "wall_s" in r] or [0.0]), "s")
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--model", required=True, help="Registry id, for example Qwen-qwen3-8b-instruct-q4km.")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--task", action="append", default=None)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    session = Session(args.session)
    if session.backend_pid() is None:
        print(f"isolated backend started in {session.restart_backend():.0f}s", flush=True)
    health = session.get("/docs")
    if health.status_code != 200:
        raise SystemExit(f"Isolated backend at {session.url} is not answering ({health.status_code}).")
    tasks = [t for t in build_tasks(session.db_path) if not args.task or t.task_id in args.task]
    runs = 1 if args.smoke else args.runs
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint = LOG_DIR / f"agent_suite_{args.model}.jsonl"
    rows: List[Dict[str, Any]] = []
    restarts = 0
    print(f"agent suite: model={args.model} tasks={[t.task_id for t in tasks]} runs={runs} backend={session.url}", flush=True)
    for run_index in range(1, runs + 1):
        for task in tasks:
            row = run_one(session, task, args.model, run_index, args.timeout, seed=run_index * 1000 + int(task.task_id[1:]))
            rows.append(row)
            if row.get("stalled") or row.get("status") in {"timeout", "harness_error"}:
                row["backend_restart_s"] = round(session.restart_backend(), 1)
                restarts += 1
            with checkpoint.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
            print(f"[run {run_index}] {task.task_id} {'PASS' if row['passed'] else 'FAIL'} {row.get('wall_s', '?')}s status={row.get('status')} calls={row.get('tool_calls')} guard={row.get('repetition_guard_trips')} | {row.get('detail')}", flush=True)

    result = build_result(
        "agent_suite",
        mode="smoke" if args.smoke else "full",
        subject={"label": args.model, "model_id": args.model},
        parameters={"runs_per_task": runs, "tasks": [t.task_id for t in tasks], "approval_mode": "always_approve", "isolated_session": args.session, "stall_window_s": STALL_WINDOW_S, "backend_restarts": restarts},
        metrics=summarize_model(rows, args.model),
        runs=rows,
        notes=[
            "Isolated backend profile (validation runtime, own HOME, no API keys, symlinked models). Fixtures are temporary directories; the scheduled-task fixture row is created and deleted in the isolated database.",
            "Approvals were pre-approved with always_approve, so approvals prompted is not measured. Token counts are not exposed by the task API and are not reported.",
            "Pass means the outcome verifier confirmed the result on disk or in the database and the task reached a completed status; it does not grade the wording of the answer.",
        ],
    )
    print(f"wrote {write_result(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
