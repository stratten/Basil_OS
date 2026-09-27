#!/usr/bin/env python3
"""Compare screen-block coalescing strategies against real captured activity.

Replays the activities table through candidate continuation predicates and
reports what each would have produced, so the grouping key and the gap tolerance
can be chosen from a real corpus instead of intuition.

Two things keep this honest. The production predicate is not reimplemented: the
report calls ScreenActivitySource._continues directly as an oracle and verifies
the parameterized "app + gap" candidate reproduces it exactly at the default gap,
so a future change to production that this script fails to track is reported
rather than hidden. And the block-splitting cap is replicated from the source, so
simulated block sizes match what carding would really store.

Read-only. The database is opened with mode=ro and never written. Already-carded
captures are included, because the point is to simulate grouping across the whole
corpus rather than to card anything.

Usage:
    poetry run python backend/scripts/screen_block_strategy_eval.py
    poetry run python backend/scripts/screen_block_strategy_eval.py --days 1
    poetry run python backend/scripts/screen_block_strategy_eval.py --since 2026-07-27
    poetry run python backend/scripts/screen_block_strategy_eval.py --gaps 300,600,1800
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api.services.zettel.sources.screen_source import (  # noqa: E402
    BLOCK_GAP_SECONDS,
    MAX_CAPTURES_PER_BLOCK,
    MAX_CONTEXT_CAPTURES,
    ScreenActivitySource,
)

DEFAULT_DB = os.path.expanduser("~/.basil/knowledge_base.db")
DEFAULT_GAPS = (300, 600, 1800)

_SOURCE = ScreenActivitySource()

Predicate = Callable[[sqlite3.Row, sqlite3.Row, float], bool]


def _gap_seconds(previous: sqlite3.Row, candidate: sqlite3.Row) -> float:
    """Reuse the source's own arithmetic; it normalizes mixed tz formats."""
    return _SOURCE._gap_seconds(previous["timestamp"], candidate["timestamp"])


def _same_app(previous: sqlite3.Row, candidate: sqlite3.Row, gap_limit: float) -> bool:
    if previous["app_name"] != candidate["app_name"]:
        return False
    return _gap_seconds(previous, candidate) <= gap_limit


def _same_app_and_title(
    previous: sqlite3.Row, candidate: sqlite3.Row, gap_limit: float
) -> bool:
    if (previous["window_title"] or "") != (candidate["window_title"] or ""):
        return False
    return _same_app(previous, candidate, gap_limit)


def _same_content_hash(
    previous: sqlite3.Row, candidate: sqlite3.Row, gap_limit: float
) -> bool:
    if (previous["context_hash"] or "") != (candidate["context_hash"] or ""):
        return False
    return _same_app(previous, candidate, gap_limit)


STRATEGIES: Dict[str, Predicate] = {
    "app + gap (production)": _same_app,
    "app + window title + gap": _same_app_and_title,
    "app + content hash + gap (pre-fix)": _same_content_hash,
}


def _load(db_path: str, since: Optional[str]) -> List[sqlite3.Row]:
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        sql = (
            "SELECT id, timestamp, app_name, window_title, context_hash "
            "FROM activities"
        )
        params: Sequence[object] = ()
        if since:
            sql += " WHERE timestamp >= ?"
            params = (since,)
        sql += " ORDER BY timestamp ASC, id ASC"
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _block_sizes(
    rows: Sequence[sqlite3.Row], predicate: Predicate, gap_limit: float
) -> List[int]:
    """Block sizes a run of captures would produce, including the split cap."""
    sizes: List[int] = []
    current = 0
    for index, row in enumerate(rows):
        if current == 0:
            current = 1
            continue
        previous = rows[index - 1]
        if predicate(previous, row, gap_limit) and current < MAX_CAPTURES_PER_BLOCK:
            current += 1
            continue
        sizes.append(current)
        current = 1
    if current:
        sizes.append(current)
    return sizes


def _oracle_disagreements(rows: Sequence[sqlite3.Row]) -> int:
    """Pairs where production disagrees with the app+gap candidate at the default gap."""
    return sum(
        1
        for previous, candidate in zip(rows, rows[1:])
        if _SOURCE._continues(previous, candidate)
        != _same_app(previous, candidate, BLOCK_GAP_SECONDS)
    )


def _describe(sizes: Sequence[int]) -> str:
    blocks = len(sizes)
    if not blocks:
        return "no captures"
    singles = sum(1 for size in sizes if size == 1)
    sampled = sum(1 for size in sizes if size > MAX_CONTEXT_CAPTURES)
    at_cap = sum(1 for size in sizes if size >= MAX_CAPTURES_PER_BLOCK)
    return (
        f"{blocks:>7} {singles:>7} {singles / blocks * 100:>6.0f}% "
        f"{statistics.mean(sizes):>7.2f} {statistics.median(sizes):>7.1f} "
        f"{max(sizes):>6} {sampled:>8} {at_cap:>7}"
    )


def _report(rows: Sequence[sqlite3.Row], gaps: Sequence[int]) -> None:
    print(f"captures analysed          : {len(rows)}")
    if rows:
        print(f"range                      : {rows[0]['timestamp']} .. {rows[-1]['timestamp']}")
        print(f"distinct apps              : {len({r['app_name'] for r in rows})}")
    disagreements = _oracle_disagreements(rows)
    verdict = "matches production" if disagreements == 0 else f"DIVERGED on {disagreements} pairs"
    print(f"app+gap vs _continues      : {verdict}")
    print(
        f"per-capture analysis calls : {len(rows)}  "
        "(one model call each, independent of grouping)"
    )
    if disagreements:
        print(
            "\nWARNING: production _continues no longer matches the app+gap candidate, "
            "so the row labelled 'production' below is not what carding does. "
            "Update STRATEGIES to track screen_source._continues."
        )

    header = (
        f"\n{'strategy':<36}{'blocks':>7} {'single':>7} {'  %':>7} "
        f"{'avg':>7} {'median':>7} {'max':>6} {'sampled':>8} {'at cap':>7}"
    )
    for gap_limit in gaps:
        print(f"\n=== gap tolerance: {gap_limit}s ===")
        print(header)
        print("-" * 100)
        for name, predicate in STRATEGIES.items():
            sizes = _block_sizes(rows, predicate, gap_limit)
            print(f"{name:<36}{_describe(sizes)}")
        print(
            f"\n  'sampled' = blocks over {MAX_CONTEXT_CAPTURES} captures, so the narrative "
            f"sees a sample; 'at cap' = blocks hitting the {MAX_CAPTURES_PER_BLOCK}-capture split."
        )
        print("  'blocks' is also the narrative model-call count for this strategy.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to knowledge_base.db")
    parser.add_argument("--since", help="Only captures at or after this ISO timestamp")
    parser.add_argument("--days", type=int, help="Only captures from the last N days")
    parser.add_argument(
        "--gaps",
        default=",".join(str(gap) for gap in DEFAULT_GAPS),
        help="Comma-separated gap tolerances in seconds",
    )
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"database not found: {args.db}", file=sys.stderr)
        return 1

    since = args.since
    if args.days is not None:
        since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    rows = _load(args.db, since)
    if not rows:
        print("no captures in range", file=sys.stderr)
        return 1

    gaps = [int(value) for value in args.gaps.split(",") if value.strip()]
    _report(rows, gaps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
