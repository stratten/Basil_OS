"""Passive sample of the remote endpoints that running Basil processes hold sockets to (gap register item G-04, fidelity-limited).

It lists open internet sockets with `lsof -i -nP` for the selected process names once per interval and records every distinct remote address and port with the process that held it. It reads socket tables only: no packets are captured, no proxy is inserted, and nothing is sent. It cannot see short-lived connections between samples, cannot see content, and reports addresses rather than host names (a reverse lookup is attempted and is often unavailable for CDN addresses).

This observes whatever Basil instance is already running; it is NOT a clean-install observation. Loopback addresses are reported separately.

Usage: PYTHONPATH=scripts .venv/bin/python -m benchmarks.network_passive_sample [--minutes 5] [--interval 2] [--match 'uvicorn api.main,BasilClient']
"""
from __future__ import annotations

import argparse
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.common.results import build_result, write_result  # noqa: E402

ARROW = re.compile(r"->(\[?[0-9a-fA-F:.]+\]?):(\d+)")


def matching_pids(match: Tuple[str, ...]) -> Set[str]:
    """PIDs whose full command line contains any one of the match strings (case-insensitive)."""
    ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    pids: Set[str] = set()
    for line in ps.splitlines():
        pid, _, command = line.strip().partition(" ")
        if any(m.lower() in command.lower() for m in match):
            pids.add(pid)
    return pids


def sample(match: Tuple[str, ...]) -> Set[Tuple[str, str, str, str]]:
    wanted = matching_pids(match)
    out = subprocess.run(["lsof", "-i", "-nP", "-FpcnT"], capture_output=True, text=True).stdout
    found: Set[Tuple[str, str, str, str]] = set()
    command = pid = ""
    for line in out.splitlines():
        if not line:
            continue
        tag, value = line[0], line[1:]
        if tag == "p":
            pid = value
        elif tag == "c":
            command = value
        elif tag == "n" and "->" in value and pid in wanted:
            hit = ARROW.search(value)
            if hit:
                found.add((command, pid, hit.group(1).strip("[]"), hit.group(2)))
    return found


def reverse(address: str) -> str:
    try:
        return socket.gethostbyaddr(address)[0]
    except Exception:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--minutes", type=float, default=5.0)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--match", default="uvicorn api.main,BasilClient")
    args = parser.parse_args()
    match = tuple(part for part in args.match.split(",") if part)

    seen: Dict[Tuple[str, str, str], int] = {}
    samples = 0
    deadline = time.time() + args.minutes * 60
    while time.time() < deadline:
        for command, _pid, address, port in sample(match):
            key = (command, address, port)
            seen[key] = seen.get(key, 0) + 1
        samples += 1
        time.sleep(args.interval)

    rows = []
    for (command, address, port), count in sorted(seen.items()):
        loopback = address.startswith("127.") or address == "::1"
        rows.append({"process": command, "remote": address, "port": port, "loopback": loopback, "samples_seen": count, "reverse_name": "" if loopback else reverse(address)})
    external = [r for r in rows if not r["loopback"]]
    print(f"{samples} samples; {len(rows)} distinct endpoints; {len(external)} non-loopback", flush=True)
    for row in external:
        print(f"  {row['process']:<14} {row['remote']}:{row['port']}  seen {row['samples_seen']}/{samples}  {row['reverse_name']}")
    result = build_result(
        "network_passive_sample",
        mode="full",
        subject={"label": f"sockets held by processes matching {','.join(match)}"},
        parameters={"minutes": args.minutes, "interval_seconds": args.interval, "samples": samples, "match": list(match)},
        metrics={},
        runs=[{"endpoints": rows}],
        notes=[
            "Socket-table sampling only: short-lived connections between samples are missed, content and host names (SNI) are not visible, and processes are selected by command-line substring, so only the backend (uvicorn api.main) and the client are included.",
            "This observed the already-running development instance, not a clean install, and the owner may have been using it during the window.",
        ],
    )
    print(f"wrote {write_result(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
