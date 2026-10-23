#!/usr/bin/env python3
"""Evergreen model x scenario smoke harness.

For the current registry + app state, discovers every reasoning-capable
model (built-in + custom) and, for every app scenario where it applies,
exercises the real in-process code path production uses (no HTTP server
required) and reports PASS/FAIL/SKIP/N/A per model x scenario cell.

Scenarios covered: Assistant Session, Meeting Analysis, AgentTask,
Setup Wizard. See
backend/scripts/model_scenario_smoke_core/ for the shared invokers (also
reused by the optional integration pytest wrapper).

Usage:
    python scripts/model_scenario_smoke.py
    python scripts/model_scenario_smoke.py --id claude
    python scripts/model_scenario_smoke.py --provider anthropic --location cloud
    python scripts/model_scenario_smoke.py --scenario agent_task

Exits non-zero if any model x scenario cell is a FAIL (SKIP/N/A do not
affect the exit code -- they reflect current app state / applicability,
not a defect).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# --json contract: stdout carries ONLY the JSON document. The app emits heavy
# INFO logging AND at least one raw print() to stdout during import of the
# api.* modules below (logging setup, ModelService singleton init), which fires
# long before argument parsing. So the redirect must happen HERE, before those
# imports: point sys.stdout at stderr for the whole process and keep the real
# stdout aside, then write the JSON to it (and nothing else) at the very end.
_JSON_MODE = "--json" in sys.argv[1:]
_REAL_STDOUT = sys.stdout
if _JSON_MODE:
    sys.stdout = sys.stderr

from model_scenario_smoke_core.matrix import run_matrix  # noqa: E402
from model_scenario_smoke_core.report import any_fail, render, render_json  # noqa: E402
from model_scenario_smoke_core.scenarios import SCENARIOS  # noqa: E402
from api.core.models.reasoning.llama_cpp_model import (  # noqa: E402
    shutdown_cached_llama_cpp_models,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--id", dest="id_filter", default=None, help="Substring filter on model id.")
    parser.add_argument("--provider", dest="provider_filter", default=None, help="Exact provider filter (e.g. anthropic, openai, custom).")
    parser.add_argument("--location", dest="location_filter", default=None, choices=["local", "cloud"], help="Filter to local or cloud models.")
    parser.add_argument("--scenario", dest="scenario_filter", default=None, choices=list(SCENARIOS), help="Run only this single scenario for every candidate.")
    parser.add_argument(
        "--sample-channels",
        dest="sample_channels",
        action="store_true",
        help="Run only one representative model per distinct channel (location/provider/handler) "
        "for a fast routine check instead of every model.",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit the matrix as JSON on stdout (for CI/diffing) instead of the text table. "
        "Progress lines are suppressed and app INFO/WARNING logging is muted so stdout is the JSON document.",
    )
    return parser.parse_args()


async def _main_async() -> int:
    args = _parse_args()

    # Progress goes to stderr so the report/JSON on stdout stays cleanly
    # separable and pipeable. Suppressed under --json (stdout is redirected at
    # module load; the JSON document is written to the real stdout at the end).
    def _progress(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    on_event = None if args.as_json else _progress

    rows = await run_matrix(
        id_filter=args.id_filter,
        provider_filter=args.provider_filter,
        location_filter=args.location_filter,
        scenario_filter=args.scenario_filter,
        sample_channels=args.sample_channels,
        on_event=on_event,
    )

    scenario_order = [args.scenario_filter] if args.scenario_filter else None

    if args.as_json:
        print(render_json(rows, scenario_order=scenario_order), file=_REAL_STDOUT, flush=True)
        return 1 if any_fail(rows) else 0

    if not rows:
        print("No reasoning-capable models matched the given filters.")
        return 0

    print(render(rows, scenario_order=scenario_order))
    return 1 if any_fail(rows) else 0


def main() -> None:
    exit_code = 1
    try:
        exit_code = asyncio.run(_main_async())
    finally:
        shutdown_cached_llama_cpp_models()
    # Some exercised code paths (LangChain/Anthropic/OpenAI SDK connection
    # pools, fire-and-forget background tasks such as agent-task title
    # generation) leave non-daemon threads or open sockets behind that
    # asyncio.run()'s shutdown does not join. The report has already been
    # printed and the exit code decided by this point, so force process
    # termination rather than hang indefinitely waiting on unrelated
    # background work this harness doesn't own.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)


if __name__ == "__main__":
    main()
