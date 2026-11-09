"""Kill an overnight benchmark stage that has stopped doing work, so a hang costs minutes instead of hours.

Run beside scripts/benchmarks/run_overnight.sh: .venv/bin/python scripts/benchmarks/stall_watchdog.py --runner-pid <pid of the run_overnight.sh shell>
Every 60 seconds it sums the CPU time of the stage process tree under the runner. When that total grows by less than --min-cpu-seconds over --window-seconds, the stage is stalled: its processes are killed by PID (the runner shell is never touched, so the script moves on to the next stage) and a STALL line is appended to the status file.
A busy benchmark burns far more CPU than the threshold; a worker polling a file that will never appear burns about 6 seconds in 15 minutes.
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import psutil

STATUS_FILE = Path("/tmp/basil-bench-logs/overnight_status.txt")
STAGE_MARKER = "benchmarks"


def find_stage(runner: psutil.Process) -> Optional[psutil.Process]:
    for child in runner.children(recursive=False):
        try:
            if STAGE_MARKER in " ".join(child.cmdline()):
                return child
        except psutil.Error:
            continue
    return None


def tree(stage: psutil.Process) -> List[psutil.Process]:
    return [stage] + stage.children(recursive=True)


def tree_cpu_seconds(processes: List[psutil.Process]) -> float:
    total = 0.0
    for process in processes:
        try:
            times = process.cpu_times()
            total += times.user + times.system
        except psutil.Error:
            continue
    return total


def log_status(message: str, status_file: Path) -> None:
    line = f"{time.strftime('%F %T')} {message}"
    print(line, flush=True)
    if status_file.exists():
        with status_file.open("a") as handle:
            handle.write(line + "\n")


def kill_tree(processes: List[psutil.Process]) -> None:
    for process in reversed(processes):
        try:
            process.kill()
        except psutil.Error:
            continue


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner-pid", type=int, required=True)
    parser.add_argument("--window-seconds", type=int, default=900)
    parser.add_argument("--min-cpu-seconds", type=float, default=30.0)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--status-file", type=Path, default=STATUS_FILE)
    parser.add_argument("--dry-run", action="store_true", help="Report stalls without killing anything.")
    args = parser.parse_args()

    history: Dict[int, List[tuple]] = {}
    log_status(f"watchdog started: window {args.window_seconds}s, minimum CPU {args.min_cpu_seconds}s, dry-run {args.dry_run}", args.status_file)
    while True:
        try:
            runner = psutil.Process(args.runner_pid)
        except psutil.NoSuchProcess:
            log_status("watchdog exiting: runner is gone", args.status_file)
            return 0
        stage = find_stage(runner)
        if stage is not None:
            processes = tree(stage)
            samples = history.setdefault(stage.pid, [])
            now = time.time()
            samples.append((now, tree_cpu_seconds(processes)))
            while samples and now - samples[0][0] > args.window_seconds:
                samples.pop(0)
            covered = now - samples[0][0]
            gained = samples[-1][1] - samples[0][1]
            if covered >= args.window_seconds - args.poll_seconds and gained < args.min_cpu_seconds:
                log_status(f"STALL {' '.join(stage.cmdline())[:120]}: {gained:.1f}s CPU in {covered:.0f}s across {len(processes)} processes" + ("" if args.dry_run else "; killing the stage"), args.status_file)
                if not args.dry_run:
                    kill_tree(processes)
                history.pop(stage.pid, None)
        else:
            history.clear()
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    sys.exit(main())
