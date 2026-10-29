"""Integration wrapper around the evergreen model x scenario smoke harness.

Skipped by default: this makes real paid API calls, loads local GGUF models
into memory, and exercises live app services (disk-backed meeting fixtures,
AgentTask DB records). Set
RUN_MODEL_SCENARIO_SMOKE=1 to run it. Reuses the exact same enumeration /
availability / per-scenario invokers as the standalone CLI
(backend/scripts/model_scenario_smoke.py), so there is one implementation, not
two that can silently drift apart.
"""

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_MODEL_SCENARIO_SMOKE") != "1",
    reason="Set RUN_MODEL_SCENARIO_SMOKE=1 to run the live model x scenario smoke matrix "
    "(paid API calls + local model loads + live app services).",
)

_SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


async def test_model_scenario_smoke_matrix_has_no_failures():
    """Run the full evergreen matrix against the current registry + app state.

    Any FAIL cell (a model that IS available but mishandles a scenario it
    should support) fails this test. SKIP (model unavailable right now) and
    N/A (scenario doesn't apply to this model) are expected, informative
    outcomes and do not fail the test.
    """
    from model_scenario_smoke_core.matrix import run_matrix
    from model_scenario_smoke_core.report import any_fail, render

    rows = await run_matrix()
    assert rows, "No reasoning-capable models were discovered from the registry."

    report = render(rows)
    print(report)

    assert not any_fail(rows), f"One or more model x scenario cells FAILed:\n{report}"
