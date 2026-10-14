#!/usr/bin/env python3
"""Replay a saved meeting transcript through the Companion engine to tune triggers and measure latency.

Default (dry run): no model, no network. Prints when and why the Companion would evaluate.

    cd backend && python scripts/companion_replay.py --meeting-id <id>
    cd backend && python scripts/companion_replay.py --meeting-id <id> --mode passive --watch "billing::Summarize the billing endpoint"

Live model replay invokes the selected model once per predicted evaluation and therefore needs BOTH flags:

    cd backend && python scripts/companion_replay.py --meeting-id <id> --live-model --yes [--model-id <analysis model id>] [--out report.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api.services.meeting_companion.gate import keywords_from_topic  # noqa: E402
from api.services.meeting_companion.models import CompanionWatch  # noqa: E402
from api.services.meeting_companion.replay import format_report, replay, segments_to_turns  # noqa: E402


def load_segments(meeting_id: str) -> list:
    path = Path.home() / ".basil" / "meetings" / meeting_id / "transcript.json"
    if not path.is_file():
        raise SystemExit(f"No transcript at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("segments") or [])


def parse_watches(values: List[str]) -> List[CompanionWatch]:
    watches: List[CompanionWatch] = []
    for index, value in enumerate(values, start=1):
        topic, _, instruction = value.partition("::")
        topic = topic.strip()
        if not topic:
            raise SystemExit(f"Invalid --watch value: {value!r} (expected 'topic::instruction')")
        watches.append(
            CompanionWatch(
                id=f"w{index}",
                topic=topic,
                instruction=instruction.strip() or topic,
                keywords=keywords_from_topic(topic),
                created_at=0.0,
            )
        )
    return watches


async def run(arguments: argparse.Namespace) -> int:
    turns = segments_to_turns(load_segments(arguments.meeting_id))
    watches = parse_watches(arguments.watch)
    dry = await replay(turns, mode=arguments.mode, watches=watches)
    print("DRY RUN (gate only)")
    print(format_report(dry))
    report = dry
    if arguments.live_model:
        if not arguments.yes:
            print(f"\nLive replay would invoke the model {len(dry.steps)} time(s). Re-run with --yes to proceed.")
            return 2
        from api.services.meeting_companion.evaluator import CompanionEvaluator

        evaluator = CompanionEvaluator()
        report = await replay(
            turns,
            mode=arguments.mode,
            watches=watches,
            evaluate=evaluator.evaluate,
            model_id=arguments.model_id,
        )
        print("\nLIVE MODEL REPLAY")
        print(format_report(report))
    if arguments.out:
        Path(arguments.out).write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        print(f"\nWrote {arguments.out}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--meeting-id", required=True)
    parser.add_argument("--mode", choices=["active", "passive"], default="active")
    parser.add_argument("--watch", action="append", default=[], help="topic::instruction (repeatable)")
    parser.add_argument("--live-model", action="store_true", help="invoke the model for each predicted evaluation")
    parser.add_argument("--yes", action="store_true", help="confirm the model invocations for --live-model")
    parser.add_argument("--model-id", default=None, help="analysis model id; default is the default reasoning model")
    parser.add_argument("--out", default=None, help="write the final report as JSON to this path")
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
