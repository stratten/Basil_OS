#!/usr/bin/env python3
"""Routing accuracy check against the RUNNING backend.

Submits a fixed set of short prompts to ``POST /api/v1/agent-tasks/process`` for each model you name, reads the model's first tool calls back from the work ledger, and scores them against the route the system prompt and tool family catalog call for.
It exists to answer one question before and after a prompt, tool-description, or context change: does the model still reach for the right tool first?

Every task runs with approvals set to always prompt, so the model stops at the first command or script it asks to run.
A shell command or AppleScript the backend's classifiers prove read-only is approved so the run can continue; any other approval card is scored as the model's call, then denied and the task canceled.
A task that never reaches an approval is canceled once the routing window (default 4 substantive tool calls) is full, so a run is short and a wrong route cannot execute anything that is not provably a read.
Cases marked live read the owner's real accounts, local Basil data, or the visible desktop, so they are skipped unless you pass --allow-live-read-only for that run.

--out writes the results and a separate evidence snapshot (every database row the run created, including final answers) as locked, read-only files with a SHA-256 beside each; an existing file is never overwritten.
--cleanup then deletes the run's database rows, but only after both files verify and the rows still match the snapshot. --finalize does the same for a results file from an earlier run. --dry-run shows what cleanup would do without deleting anything.

Usage (from backend/, backend already running):
    PYTHONPATH=src ../.venv/bin/python scripts/routing_accuracy_check.py --list
    PYTHONPATH=src ../.venv/bin/python scripts/routing_accuracy_check.py --model Qwen-qwen3-8b-instruct-q4km --out ../local/routing_baselines/before.json
    PYTHONPATH=src ../.venv/bin/python scripts/routing_accuracy_check.py --model Qwen-qwen3-8b-instruct-q4km --baseline ../local/routing_baselines/before.json

Exit codes: 0 clean, 1 a case regressed against --baseline, 2 a harness error left a case unscored.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from routing_accuracy_core.cases import RoutingCase, build_cases  # noqa: E402
from routing_accuracy_core.cleanup import CleanupRefused, plan_cleanup, repair_orphans, run_cleanup  # noqa: E402
from routing_accuracy_core.evidence import collect_evidence, evidence_path_for, validate_evidence  # noqa: E402
from routing_accuracy_core.fixture import create_fixture, remove_fixture  # noqa: E402
from routing_accuracy_core.ledger_reader import DEFAULT_DATABASE_PATH  # noqa: E402
from routing_accuracy_core.locked_store import LockedStoreError, digest_path, lock_existing, verify_locked, write_locked  # noqa: E402
from routing_accuracy_core.report import (  # noqa: E402
    build_document,
    compare,
    has_regression,
    load_document,
    render_comparison,
    render_text,
)
from routing_accuracy_core.route_tokens import DEFAULT_WINDOW_SIZE  # noqa: E402
from routing_accuracy_core.runner import BackendClient, CaseResult, run_case  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", action="append", default=[], help="Registry model id to test. Repeat for several models. Required unless --list.")
    parser.add_argument("--case", action="append", default=[], help="Run only this case id. Repeatable.")
    parser.add_argument("--category", action="append", default=[], help="Run only cases in this category. Repeatable.")
    parser.add_argument("--list", action="store_true", help="Print the cases and exit without contacting the backend.")
    parser.add_argument("--allow-live-read-only", action="store_true", help="Also run the live cases, which read the owner's real accounts, Basil data, or desktop.")
    parser.add_argument("--gmail-basil-connection-id", default=None, help='Make the Gmail case require this exact connection id, or pass "auto" to look up the one connection named "Gmail - Basil" in the connection inventory.')
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW_SIZE, help="Substantive tool calls scored per case.")
    parser.add_argument("--case-timeout", type=float, default=240.0, help="Seconds to wait for the routing window before a case is INCOMPLETE.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH, help="Work ledger database to read.")
    parser.add_argument("--label", default="", help="Free-text label stored in the output document.")
    parser.add_argument("--out", type=Path, default=None, help="Write the locked result document here as JSON, with its evidence snapshot beside it. The path must not exist yet.")
    parser.add_argument("--baseline", type=Path, default=None, help="Compare against a document written earlier by --out.")
    parser.add_argument("--cleanup", action="store_true", help="After the results and evidence are locked and verified, delete this run's database rows. Requires --out (or --finalize).")
    parser.add_argument("--finalize", type=Path, default=None, help="Skip the run: capture and lock the evidence for the tasks in this earlier results file, then clean up with --cleanup or preview with --dry-run.")
    parser.add_argument("--dry-run", action="store_true", help="With --finalize or --repair-orphans, print what would be deleted and any blockers, and delete nothing.")
    parser.add_argument("--repair-orphans", type=Path, default=None, help="Remove rows an earlier cleanup left detached (receipts, events, sessions whose task id was cleared), using the verified evidence file beside this results file.")
    return parser.parse_args()


def _select(cases: tuple[RoutingCase, ...], args: argparse.Namespace) -> list[RoutingCase]:
    chosen = [c for c in cases if (not args.case or c.case_id in args.case) and (not args.category or c.category in args.category)]
    unknown = sorted(set(args.case) - {c.case_id for c in cases})
    if unknown:
        raise SystemExit(f"Unknown case id(s): {', '.join(unknown)}")
    return chosen


def _print_list(cases: tuple[RoutingCase, ...]) -> None:
    for case in cases:
        live = f"LIVE ({case.live_reason})" if case.live else "fixture"
        print(f"{case.case_id:<28} {case.category:<11} {live}")
        print(f"    {case.steer}")


def _task_ids(document: dict) -> list[str]:
    return sorted({entry["task_id"] for cases in document["models"].values() for entry in cases.values() if entry.get("task_id")})


def _print_plan(plan) -> None:
    print("Rows that belong to this run:")
    for name, count in sorted(plan.counts.items()):
        print(f"  {name}: {count}")
    blockers = plan.blockers
    print("Cleanup blockers: " + ("; ".join(blockers) if blockers else "none"))


def _finalize(results_path: Path, database_path: Path, cleanup: bool, dry_run: bool) -> int:
    """Lock the results, capture and lock the evidence, then (only if asked) delete the run's rows. Returns the exit code."""
    try:
        if not digest_path(results_path).exists():
            lock_existing(results_path)
            print(f"Locked {results_path}", file=sys.stderr)
        document = verify_locked(results_path)
        task_ids = _task_ids(document)
        if not task_ids:
            print("The results file lists no tasks, so there is nothing to capture or clean up.", file=sys.stderr)
            return 0
        evidence_path = evidence_path_for(results_path)
        if not evidence_path.exists():
            write_locked(evidence_path, collect_evidence(database_path, task_ids))
            print(f"Wrote and locked {evidence_path}", file=sys.stderr)
        evidence = verify_locked(evidence_path)
        validate_evidence(evidence, task_ids)
        print(f"Evidence verified for {len(task_ids)} task(s): {evidence_path}", file=sys.stderr)
        if not cleanup:
            _print_plan(plan_cleanup(database_path, task_ids, evidence["row_counts"]))
            return 0
        if dry_run:
            plan = plan_cleanup(database_path, task_ids, evidence["row_counts"])
            _print_plan(plan)
            return 2 if plan.blockers else 0
        outcome = run_cleanup(BackendClient(), database_path, task_ids, evidence["row_counts"])
        removed = sum(outcome["before"].values())
        print(f"Cleanup finished: {removed} row(s) across {len(outcome['before'])} table(s) removed, 0 remain.", file=sys.stderr)
        return 0
    except (LockedStoreError, CleanupRefused, ValueError, OSError) as exc:
        print(f"Not cleaned up: {exc}", file=sys.stderr)
        return 2


def _repair(results_path: Path, database_path: Path, dry_run: bool) -> int:
    """Delete the detached rows an earlier cleanup left behind. Both files must verify, and only rows identical to the captured ones are removed."""
    try:
        document = verify_locked(results_path)
        task_ids = _task_ids(document)
        evidence = verify_locked(evidence_path_for(results_path))
        validate_evidence(evidence, task_ids)
        removed = repair_orphans(database_path, evidence, dry_run=dry_run)
        verb = "would remove" if dry_run else "removed"
        print(f"{verb} {sum(removed.values())} detached row(s): {removed or 'none'}", file=sys.stderr)
        return 0
    except (LockedStoreError, CleanupRefused, ValueError, OSError) as exc:
        print(f"Not repaired: {exc}", file=sys.stderr)
        return 2


def main() -> int:
    args = _parse_args()
    if args.repair_orphans:
        return _repair(args.repair_orphans, args.database, args.dry_run)
    if args.finalize:
        return _finalize(args.finalize, args.database, args.cleanup, args.dry_run)
    if args.cleanup and not args.out:
        raise SystemExit("--cleanup needs --out, so the results and evidence are locked before anything is deleted.")
    if args.out and any(path.exists() for path in (args.out, digest_path(args.out), evidence_path_for(args.out))):
        raise SystemExit(f"{args.out} or its evidence file already exists. Locked results are never overwritten, so choose a new name.")
    resolve_gmail = args.gmail_basil_connection_id == "auto"
    all_cases = build_cases(None if resolve_gmail else args.gmail_basil_connection_id)
    if args.list:
        _print_list(all_cases)
        return 0
    if not args.model:
        raise SystemExit("Name at least one --model (a registry model id). Cloud models cost API money, so there is no default.")
    selected = _select(all_cases, args)
    skipped_live = [c for c in selected if c.live and not args.allow_live_read_only]
    runnable = [c for c in selected if c not in skipped_live]
    if skipped_live:
        print(f"Skipping {len(skipped_live)} live case(s); pass --allow-live-read-only to run them: {', '.join(c.case_id for c in skipped_live)}", file=sys.stderr)
    for case in (c for c in runnable if c.live):
        print(f"LIVE {case.case_id}: {case.live_reason}", file=sys.stderr)
    if not runnable:
        raise SystemExit("No cases selected.")

    client = BackendClient()
    if not client.healthy():
        raise SystemExit("The backend is not reachable at 127.0.0.1:8000. Start it first.")
    if resolve_gmail:
        resolved = client.connection_id_by_name("Gmail - Basil")
        if resolved is None:
            raise SystemExit('Could not find exactly one connection named "Gmail - Basil" in the connection inventory.')
        by_id = {case.case_id: case for case in build_cases(resolved)}
        runnable = [by_id[case.case_id] for case in runnable]

    fixture = create_fixture() if any(c.needs_fixture for c in runnable) else None
    results: list[CaseResult] = []
    stuck: CaseResult | None = None
    try:
        for model_id in args.model:
            for case in runnable:
                print(f"[{model_id}] {case.case_id} ...", file=sys.stderr, flush=True)
                result = run_case(client, case, model_id, fixture, args.database, window_size=args.window, case_timeout_s=args.case_timeout)
                print(f"[{model_id}] {case.case_id}: {result.verdict.verdict} ({result.seconds:.0f}s)", file=sys.stderr, flush=True)
                results.append(result)
                if result.still_running:
                    stuck = result
                    break
            if stuck:
                break
    finally:
        if fixture is not None:
            remove_fixture(fixture)

    document = build_document(results, args.window, args.label)
    print(render_text(document))
    exit_code = 2 if any(r.error for r in results) else 0
    if stuck:
        print(
            f"STOPPED EARLY: task {stuck.task_id} ({stuck.case_id}) was still running after cancel, so no further cases were started. "
            "Cancel it in the app or wait for it to end before running the check again.",
            file=sys.stderr,
        )
        exit_code = 2
    if args.out:
        write_locked(args.out, document)
        print(f"Wrote and locked {args.out}", file=sys.stderr)
        if _task_ids(document):
            # A task that is still running blocks cleanup by itself; the snapshot is still taken so what exists is recorded.
            exit_code = max(exit_code, _finalize(args.out, args.database, args.cleanup, False))
    if args.baseline:
        baseline = load_document(args.baseline)
        changes = compare(baseline, document)
        print(render_comparison(changes, baseline.get("label") or args.baseline.name))
        if has_regression(changes):
            exit_code = max(exit_code, 1)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
