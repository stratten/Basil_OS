#!/usr/bin/env python3
"""Replay a saved meeting transcript through the Companion engine to tune triggers and measure latency.

Default (dry run): no model, no network. Prints when and why the Companion would evaluate.

    cd backend && python scripts/companion_replay.py --meeting-id <id>
    cd backend && python scripts/companion_replay.py --meeting-id <id> --mode passive --watch "billing::Summarize the billing endpoint"

Live model replay invokes the selected model once per predicted evaluation and therefore needs BOTH flags:

    cd backend && python scripts/companion_replay.py --meeting-id <id> --live-model --yes [--model-id <analysis model id>] [--out report.json]

Tuning comparison: score the shipped behavior and each candidate against the audit findings you marked Good catch or Not needed in the Companion pane. Each variant needs its own model pass, so --yes covers all of them. --record saves the baseline's model responses; --recorded replays them with no model, which is valid for the floor-0.5 candidate only: the gate must fire at the same moments and the prompt must not change, because the model is not called.

    cd backend && python scripts/companion_replay.py --meeting-id <id> --live-model --yes --candidate floor-0.5 --candidate all --record /tmp/baseline.json
    cd backend && python scripts/companion_replay.py --meeting-id <id> --recorded /tmp/baseline.json --candidate floor-0.5

Candidates: floor-0.5, min-turns-2, ttl-120, periodic-60, soften-silence, all. Nothing is applied to the app by this script; a candidate becomes a default only by a deliberate edit when the table says APPLY.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api.core.models.model_invocation import call_model_with_schema  # noqa: E402
from api.services.meeting_companion import offline  # noqa: E402
from api.services.meeting_companion.evaluator import CompanionEvaluator  # noqa: E402
from api.services.meeting_companion.gate import keywords_from_topic  # noqa: E402
from api.services.meeting_companion.models import CompanionWatch  # noqa: E402
from api.services.meeting_companion.replay import format_report, replay, segments_to_turns  # noqa: E402
from api.services.meeting_companion.replay_compare import RecordedCaller, RecordingCaller, format_comparison, load_marked_moments, row_for  # noqa: E402
from api.services.meeting_companion.replay_scoring import score_replay  # noqa: E402
from api.services.meeting_companion.replay_tuning import applied, candidate_names, gate_config_for, resolve  # noqa: E402


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


def build_evaluator(recorder: Optional[RecordingCaller], recorded: Optional[RecordedCaller]) -> CompanionEvaluator:
    """The real evaluator, one that records its responses, or one that answers from a recording."""
    if recorded is not None:
        async def stub_model(model_id):
            return SimpleNamespace(model_id=model_id)

        return CompanionEvaluator(model_loader=stub_model, schema_caller=recorded, token_budget=lambda model: 1500)
    if recorder is not None:
        return CompanionEvaluator(schema_caller=recorder)
    return CompanionEvaluator(schema_caller=call_model_with_schema)


async def compare(arguments: argparse.Namespace, turns, watches) -> int:
    """Score the baseline and each candidate against the meeting's marked audit findings."""
    candidates = [resolve(name) for name in arguments.candidate]
    moments = load_marked_moments(offline.load_stored_snapshot(arguments.meeting_id))
    variants = [(None, "baseline")] + [(candidate, candidate.name) for candidate in candidates]
    recorded = RecordedCaller.load(Path(arguments.recorded)) if arguments.recorded else None
    if recorded is not None:
        variants = [(candidate, name) for candidate, name in variants if candidate is None or (not candidate.gate and not candidate.softened_prompt)]
    dry_counts = {}
    for candidate, name in variants:
        dry = await replay(turns, mode=arguments.mode, watches=watches, gate_config=gate_config_for(candidate))
        dry_counts[name] = len(dry.steps)
        print(f"{name}: the gate would evaluate {len(dry.steps)} time(s)")
    if recorded is None:
        total = sum(dry_counts.values())
        if not (arguments.live_model and arguments.yes):
            print(f"\nComparing would invoke the model {total} time(s) across {len(variants)} variant(s). Re-run with --live-model --yes to proceed.")
            return 2
    rows = []
    for index, (candidate, name) in enumerate(variants):
        recorder = RecordingCaller(call_model_with_schema) if (arguments.record and index == 0 and recorded is None) else None
        if recorded is not None:
            recorded = RecordedCaller.load(Path(arguments.recorded))
        evaluator = build_evaluator(recorder, recorded)
        with applied(candidate):
            report = await replay(turns, mode=arguments.mode, watches=watches, gate_config=gate_config_for(candidate), evaluate=evaluator.evaluate, model_id=arguments.model_id)
        if recorder is not None:
            recorder.save(Path(arguments.record))
            print(f"Saved the baseline's model responses to {arguments.record}")
        rows.append(row_for(name, report, score_replay(report.items, moments)))
    print("\nCOMPARISON")
    print(format_comparison(rows))
    return 0


async def run(arguments: argparse.Namespace) -> int:
    turns = segments_to_turns(load_segments(arguments.meeting_id))
    watches = parse_watches(arguments.watch)
    if arguments.candidate or arguments.recorded:
        return await compare(arguments, turns, watches)
    dry = await replay(turns, mode=arguments.mode, watches=watches)
    print("DRY RUN (gate only)")
    print(format_report(dry))
    report = dry
    if arguments.live_model:
        if not arguments.yes:
            print(f"\nLive replay would invoke the model {len(dry.steps)} time(s). Re-run with --yes to proceed.")
            return 2
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
    parser.add_argument("--candidate", action="append", default=[], choices=candidate_names(), help="a tuning candidate to score against the baseline (repeatable)")
    parser.add_argument("--record", default=None, help="with --candidate and --live-model: save the baseline's model responses to this path")
    parser.add_argument("--recorded", default=None, help="answer evaluations from responses saved by --record instead of calling a model")
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
