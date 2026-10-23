#!/usr/bin/env python3
"""Run the opt-in local Mail work-ledger validation harness."""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    harness_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "tests"
        / "services"
        / "agent_processing_tests"
        / "live_work_ledger_validation.py"
    )
    runpy.run_path(str(harness_path), run_name="__main__")
