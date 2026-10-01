#!/usr/bin/env python3
"""Live per-tool-family + mixed-tool verification against the RUNNING backend.

This is the lightweight counterpart to ``model_scenario_smoke.py``. That harness
boots a second, in-process copy of the whole app so it can construct and sweep
every model in the registry -- which is why it is slow to start and heavy. When
you only care about the single configured reasoning model (Sonnet 5 right now),
you do not need any of that: the backend is already running, already has the
model loaded, and already writes every tool call into the durable work ledger.

So this script reuses the exact same scenario definitions
(``model_scenario_smoke_core.tool_scenarios.TOOL_SCENARIO_SPECS`` -- prompts,
setup/cleanup, and expected (service, method) invocations) but:

  1. submits each scenario's prompt to POST /api/v1/agent-tasks/process on the
     already-running backend (model pinned via model_id),
  2. polls GET /api/v1/agent-tasks/{id} until the task reaches a terminal state,
  3. verifies the expected tool family actually fired by reading
     ``agent_work_receipts`` from the shared ledger DB (same evidence check the
     matrix harness uses), not merely that the task completed.

Usage (from the Basil/ project dir, backend already up):
    PYTHONPATH=src poetry run python scripts/tool_scenarios_live.py
    PYTHONPATH=src poetry run python scripts/tool_scenarios_live.py --scenario tool_shell --scenario mixed_file_shell
    PYTHONPATH=src poetry run python scripts/tool_scenarios_live.py --families-only
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from api.core.security.backend_credentials import BACKEND_TOKEN_HEADER, load_host_token  # noqa: E402
from api.dependencies import get_sqlite_knowledge_service  # noqa: E402
from model_scenario_smoke_core.scenarios import (  # noqa: E402
    MIXED_TOOL_SCENARIO_IDS,
    SMOKE_TAG,
    TOOL_FAMILY_SCENARIO_IDS,
)
from model_scenario_smoke_core.tool_scenarios import (  # noqa: E402
    TOOL_SCENARIO_SPECS,
    ToolScenarioSpec,
    _new_sandbox,
    spec_invocation_satisfied,
)
from model_scenario_smoke_core.ledger_evidence import invoked_service_methods  # noqa: E402

BASE_URL = "http://127.0.0.1:8000"
DEFAULT_MODEL = "claude-sonnet-5"
TERMINAL_STATUSES = {
    "completed", "completed_with_warnings", "failed", "partial", "awaiting_user_input",
}
# A task must at least have run to completion (in some form) for a tool-invocation
# check to be meaningful. awaiting_user_input means it stalled on a clarification.
RAN_STATUSES = {"completed", "completed_with_warnings", "partial"}


def _health_check() -> bool:
    try:
        resp = requests.get(f"{BASE_URL}/docs", headers={BACKEND_TOKEN_HEADER: load_host_token()}, timeout=5)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def _submit(prompt: str, model_id: str, approval_override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    body: Dict[str, Any] = {"agent_task": prompt, "model_id": model_id}
    if approval_override:
        body["approval_policy_override"] = approval_override
    resp = requests.post(
        f"{BASE_URL}/api/v1/agent-tasks/process",
        json=body,
        headers={BACKEND_TOKEN_HEADER: load_host_token()},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _poll_until_terminal(agent_task_id: str, timeout_s: float, interval_s: float = 1.0) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            resp = requests.get(
                f"{BASE_URL}/api/v1/agent-tasks/{agent_task_id}",
                headers={BACKEND_TOKEN_HEADER: load_host_token()},
                timeout=10,
            )
        except requests.RequestException:
            time.sleep(interval_s)
            continue
        if resp.status_code == 200:
            last = resp.json()
            if last.get("status") in TERMINAL_STATUSES:
                return last
        time.sleep(interval_s)
    last["_timed_out"] = True
    return last


class Result:
    __slots__ = ("scenario_id", "verdict", "status", "detail", "invoked")

    def __init__(self, scenario_id: str, verdict: str, status: str, detail: str, invoked: str = ""):
        self.scenario_id = scenario_id
        self.verdict = verdict  # PASS | FAIL | SKIP
        self.status = status
        self.detail = detail
        self.invoked = invoked


async def _run_one(spec: ToolScenarioSpec, model_id: str, timeout_s: float, database_path: Path, approval_override: Optional[Dict[str, Any]]) -> Result:
    sandbox = _new_sandbox()
    try:
        if spec.setup:
            try:
                spec.setup(sandbox)
            except ValueError as exc:
                return Result(spec.scenario_id, "SKIP", "setup", str(exc))

        prompt = f"{SMOKE_TAG} {spec.build_prompt(sandbox)}"
        try:
            submitted = _submit(prompt, model_id, approval_override)
        except requests.RequestException as exc:
            return Result(spec.scenario_id, "FAIL", "submit_error", str(exc))

        agent_task_id = submitted.get("agent_task_id")
        if not agent_task_id:
            return Result(spec.scenario_id, "FAIL", "no_task_id", str(submitted)[:200])

        final = _poll_until_terminal(agent_task_id, timeout_s=timeout_s)
        status = final.get("status") or ("timeout" if final.get("_timed_out") else "unknown")

        detail = final.get("error_message") or final.get("result_message") or ""
        if status in {"failed", "error"} and "no email client" in str(detail).lower():
            return Result(spec.scenario_id, "SKIP", status, "no email client available")

        invoked = invoked_service_methods(database_path, agent_task_id)
        invoked_str = ", ".join(sorted(f"{s}.{m}" for s, m in invoked)) or "(none)"

        if status not in RAN_STATUSES:
            return Result(
                spec.scenario_id, "FAIL", status,
                f"task={agent_task_id} did not run to completion: {str(detail)[:160]}",
                invoked_str,
            )

        if spec_invocation_satisfied(database_path, agent_task_id, spec):
            return Result(spec.scenario_id, "PASS", status, f"task={agent_task_id}", invoked_str)

        return Result(
            spec.scenario_id, "FAIL", status,
            f"task={agent_task_id} ran but expected tool(s) not invoked "
            f"[expected={spec.expected_service_methods} groups={spec.required_groups} "
            f"services={spec.required_services}]",
            invoked_str,
        )
    finally:
        if spec.cleanup:
            try:
                await spec.cleanup(sandbox)
            except Exception:
                pass
        shutil.rmtree(sandbox.tmp_dir, ignore_errors=True)


def _select_scenarios(args: argparse.Namespace) -> List[str]:
    if args.scenario:
        return list(args.scenario)
    ids: List[str] = []
    if not args.mixed_only:
        ids.extend(TOOL_FAMILY_SCENARIO_IDS)
    if not args.families_only:
        ids.extend(MIXED_TOOL_SCENARIO_IDS)
    return ids


async def _main_async() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model id to pin per request (default {DEFAULT_MODEL}).")
    parser.add_argument("--scenario", action="append", default=None, help="Run only this scenario id (repeatable).")
    parser.add_argument("--families-only", action="store_true", help="Only per-tool-family scenarios.")
    parser.add_argument("--mixed-only", action="store_true", help="Only mixed-tool scenarios.")
    parser.add_argument("--timeout", type=float, default=240.0, help="Per-scenario terminal-state timeout (seconds).")
    parser.add_argument("--approve-mode", default="always_approve", help="Per-run approval_mode override (always_approve|whitelist_only|always_prompt|none). Default always_approve for headless testing.")
    parser.add_argument("--timeout-behavior", default=None, help="Optional per-run timeout_behavior override (wait_forever|deny_on_timeout|retry_alternative).")
    args = parser.parse_args()

    approval_override: Optional[Dict[str, Any]] = None
    if args.approve_mode and args.approve_mode.lower() != "none":
        approval_override = {"approval_mode": args.approve_mode}
        if args.timeout_behavior:
            approval_override["timeout_behavior"] = args.timeout_behavior

    if not _health_check():
        print(f"Backend not reachable at {BASE_URL}. Start it first, then re-run.")
        return 2

    database_path = Path(get_sqlite_knowledge_service().db_path)
    scenario_ids = _select_scenarios(args)
    print(f"Live tool-scenario verification -> model={args.model} backend={BASE_URL}")
    print(f"Ledger DB: {database_path}")
    print(f"Running {len(scenario_ids)} scenario(s): {', '.join(scenario_ids)}\n")

    results: List[Result] = []
    for idx, scenario_id in enumerate(scenario_ids, start=1):
        spec = TOOL_SCENARIO_SPECS.get(scenario_id)
        if spec is None:
            results.append(Result(scenario_id, "SKIP", "unknown", "no such scenario id"))
            print(f"[{idx}/{len(scenario_ids)}] {scenario_id}: SKIP (unknown scenario id)")
            continue
        print(f"[{idx}/{len(scenario_ids)}] {scenario_id}: running…", flush=True)
        t0 = time.monotonic()
        result = await _run_one(spec, args.model, args.timeout, database_path, approval_override)
        dt = time.monotonic() - t0
        results.append(result)
        print(f"    -> {result.verdict} [{result.status}] {dt:.0f}s | {result.detail}")
        if result.invoked:
            print(f"       invoked: {result.invoked}")

    passed = sum(1 for r in results if r.verdict == "PASS")
    failed = sum(1 for r in results if r.verdict == "FAIL")
    skipped = sum(1 for r in results if r.verdict == "SKIP")

    print("\n" + "=" * 90)
    print(f"SUMMARY  model={args.model}  PASS={passed}  FAIL={failed}  SKIP={skipped}  (of {len(results)})")
    print("=" * 90)
    for r in results:
        print(f"  {r.verdict:4}  {r.scenario_id:24}  [{r.status}]  {r.detail}")
    return 1 if failed else 0


def main() -> None:
    raise SystemExit(asyncio.run(_main_async()))


if __name__ == "__main__":
    main()
