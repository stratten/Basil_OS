"""One JSON file per benchmark run, validated against a fixed schema before it is written or rendered."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import jsonschema

from .machine import REPO_ROOT, describe_machine

DEFAULT_BENCHMARKS_DIR = (
    REPO_ROOT / "local" / "w. Documentation" / "a.GTM_Docs" / "Feature_Analysis" / "Benchmarks"
)

MODES = ("full", "smoke", "simulated")

RESULT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": [
        "schema_version", "benchmark", "run_id", "timestamp", "mode", "reportable",
        "machine", "subject", "parameters", "metrics", "runs", "notes",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "benchmark": {"type": "string", "minLength": 1},
        "run_id": {"type": "string", "minLength": 1},
        "timestamp": {"type": "string"},
        "mode": {"enum": list(MODES)},
        "reportable": {"type": "boolean"},
        "machine": {
            "type": "object",
            "required": ["machine_id", "chip", "memory_gb", "macos", "power", "basil_commit"],
        },
        "subject": {"type": "object"},
        "parameters": {"type": "object"},
        "metrics": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["unit", "n", "median", "min", "max", "stdev"],
            },
        },
        "runs": {"type": "array"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
}


def benchmarks_dir() -> Path:
    override = os.environ.get("BASIL_BENCH_DIR")
    return Path(override) if override else DEFAULT_BENCHMARKS_DIR


def raw_dir() -> Path:
    return benchmarks_dir() / "raw"


def validate_result(result: Dict[str, Any]) -> None:
    jsonschema.validate(instance=result, schema=RESULT_SCHEMA)


def build_result(
    benchmark: str,
    *,
    mode: str,
    subject: Dict[str, Any],
    parameters: Dict[str, Any],
    metrics: Dict[str, Dict[str, Any]],
    runs: List[Dict[str, Any]],
    notes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Assemble a result. Smoke and simulated runs are never marked reportable as real-hardware figures."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    machine = describe_machine()
    result_notes = list(notes or [])
    if machine["power"]["source"] != "ac":
        result_notes.append("Not on AC power: timing may be throttled.")
    return {
        "schema_version": 1,
        "benchmark": benchmark,
        "run_id": uuid.uuid4().hex[:12],
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "reportable": mode == "full",
        "machine": machine,
        "subject": subject,
        "parameters": parameters,
        "metrics": metrics,
        "runs": runs,
        "notes": result_notes,
    }


def metric_from_summary(summary: Dict[str, Any], unit: str) -> Dict[str, Any]:
    return {"unit": unit, **summary}


def write_result(result: Dict[str, Any], directory: Optional[Path] = None) -> Path:
    validate_result(result)
    target_dir = directory or raw_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    subject_label = re.sub(r"[^A-Za-z0-9._-]+", "_", str(result["subject"].get("label", "subject")))[:60]
    name = f"{result['benchmark']}__{result['machine']['machine_id']}__{subject_label}__{result['mode']}__{stamp}_{result['run_id']}.json"
    path = target_dir / name
    path.write_text(json.dumps(result, indent=2, sort_keys=False), encoding="utf-8")
    return path


def load_results(directory: Optional[Path] = None) -> Iterable[Dict[str, Any]]:
    source = directory or raw_dir()
    if not source.is_dir():
        return []
    loaded = []
    for path in sorted(source.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        validate_result(data)
        loaded.append(data)
    return loaded
