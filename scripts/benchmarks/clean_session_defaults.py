"""Static-plus-runtime check of what a clean install does by default for activity capture and ambient suggestions (gap register items G-02 and G-03).

It constructs the preference models with no saved file (the code defaults a fresh install gets), resolves the activity-processing model through the same function the run policy uses, looks the id up in the model registry, and scans the backend source for any code that reads the ambient `allow_cloud_evaluation` flag. Nothing is written under ~/.basil, no network call is made, and no service is started.

Usage: PYTHONPATH=scripts:backend/src .venv/bin/python -m benchmarks.clean_session_defaults
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.common.machine import REPO_ROOT  # noqa: E402
from benchmarks.common.results import build_result, write_result  # noqa: E402

FLAG = "allow_cloud_evaluation"


def registry_entry(model_id: str) -> Dict[str, Any]:
    from api.core.models.models_registry import get_model

    entry = get_model(model_id)
    if not isinstance(entry, dict):
        return {"model_id": model_id, "in_registry": False}
    return {"model_id": model_id, "in_registry": True, "location": entry.get("location"), "provider": entry.get("provider"), "display_name": entry.get("display_name")}


def flag_readers() -> List[str]:
    """Return 'path:line' for every non-test backend source line that mentions the flag."""
    hits: List[str] = []
    for path in sorted((REPO_ROOT / "backend" / "src" / "api").rglob("*.py")):
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if re.search(FLAG, line):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()[:140]}")
    return hits


def main() -> int:
    from api.core.models.preference_models.ui_and_capture import ActivityCaptureSettings, AmbientSuggestionSettings
    from api.core.models.preference_models.migrations import RETIRED_LOCAL_MODEL_REPLACEMENTS
    from api.services.capture.automatic.activity_processing_run_policy import resolve_activity_processing_model_id, resolve_activity_processing_run_policy

    capture = ActivityCaptureSettings()
    ambient = AmbientSuggestionSettings()
    resolved = resolve_activity_processing_model_id(capture.processing_model)
    policy = resolve_activity_processing_run_policy(capture.processing_model, is_manual_backlog_run=False)
    readers = flag_readers()

    findings = {
        "activity_capture_defaults": {"enabled": capture.enabled, "start_at_startup": capture.start_at_startup, "processing_model": capture.processing_model, "processing_mode": capture.processing_mode, "frequency_minutes": capture.frequency_minutes},
        "activity_processing_model": {
            "default_id": capture.processing_model,
            "resolves_to_registry_id": resolved,
            "registry": registry_entry(capture.processing_model),
            "run_policy_model_id": policy.model_id,
            "retired_replacement_map_covers_default": capture.processing_model in RETIRED_LOCAL_MODEL_REPLACEMENTS,
        },
        "ambient_defaults": {"enabled": ambient.enabled, "evaluation_model": ambient.evaluation_model, "allow_cloud_evaluation": ambient.allow_cloud_evaluation, "mode": ambient.mode, "frequency_seconds": ambient.frequency_seconds},
        "ambient_evaluation_model_registry": registry_entry(ambient.evaluation_model),
        "allow_cloud_evaluation_mentions_in_backend": readers,
    }
    for key, value in findings.items():
        print(key, value, flush=True)

    unresolved = resolved is None
    cloud_default = findings["ambient_evaluation_model_registry"].get("location") == "cloud"
    unenforced = all(("preference_models" in h or "routes" in h or "status" in h or "runtime.py" in h) for h in readers) and not any("evaluator" in h for h in readers)
    result = build_result(
        "clean_session_defaults",
        mode="full",
        subject={"label": "preference code defaults"},
        parameters={"source": "pydantic defaults, no saved preferences file"},
        metrics={},
        runs=[findings],
        notes=[
            f"G-02: the default activity-processing model id {'does NOT resolve' if unresolved else 'resolves'} in the registry (resolved: {resolved}). The retired-model replacement map {'covers' if findings['activity_processing_model']['retired_replacement_map_covers_default'] else 'does not cover'} that id.",
            f"G-03: the default ambient evaluation model is {ambient.evaluation_model} (registry location: {findings['ambient_evaluation_model_registry'].get('location')}) while allow_cloud_evaluation defaults to {ambient.allow_cloud_evaluation}. Cloud default: {cloud_default}.",
            f"allow_cloud_evaluation appears on {len(readers)} backend source lines; none of them is in the evaluator, so the flag is {'plumbed and reported but not enforced as a gate' if unenforced else 'possibly read somewhere beyond status reporting; inspect the listed lines'}.",
            "This is a static and in-process check of code defaults; it does not start capture or run a model, so it does not show the user-visible failure mode when an unresolvable model is selected.",
        ],
    )
    print(f"wrote {write_result(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
