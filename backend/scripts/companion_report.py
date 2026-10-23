#!/usr/bin/env python3
"""Compare how the Companion behaved across saved meetings. Read-only: no model, no network, nothing is written.

    cd backend && python scripts/companion_report.py
    cd backend && python scripts/companion_report.py --since 2026-10-21 --json
    cd backend && python scripts/companion_report.py --meeting-id <id>

Reads ``~/.basil/meetings/*/companion.json`` (or the directory given with --root).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api.services.meeting_companion.meeting_report import format_table, summarize_meeting  # noqa: E402
from api.services.meeting_companion.store import COMPANION_FILE_NAME, CompanionStore  # noqa: E402


def collect_rows(root: Path, *, meeting_id: Optional[str], since: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not root.is_dir():
        raise SystemExit(f"No meetings directory at {root}")
    for directory in sorted(child for child in root.iterdir() if child.is_dir()):
        if meeting_id and directory.name != meeting_id:
            continue
        if not (directory / COMPANION_FILE_NAME).is_file():
            continue
        document = CompanionStore(directory).load()
        if document is None or not document.events:
            continue
        if since and document.saved_at and document.saved_at[:10] < since:
            continue
        rows.append(summarize_meeting(directory.name, document.events, document.saved_at))
    rows.sort(key=lambda row: row["saved_at"])
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path.home() / ".basil" / "meetings")
    parser.add_argument("--meeting-id")
    parser.add_argument("--since", default="", help="Only meetings saved on or after this date (YYYY-MM-DD).")
    parser.add_argument("--json", action="store_true", help="Print the full per-meeting detail as JSON instead of the table.")
    args = parser.parse_args()
    rows = collect_rows(args.root, meeting_id=args.meeting_id, since=args.since)
    if not rows:
        raise SystemExit("No saved Companion data matched.")
    print(json.dumps(rows, indent=2) if args.json else format_table(rows))


if __name__ == "__main__":
    main()
