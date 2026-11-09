"""Gathers the non-content facts for a problem report from the running backend."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from api.services.diagnostics.problem_report import ProblemReportFacts, sanitize_detail, sanitize_source

logger = logging.getLogger(__name__)

_HARDWARE_FIELDS = (
    "platform",
    "machine",
    "total_ram_gb",
    "chip_label",
    "memory_tier",
    "local_model_memory_budget_gb",
    "gpu_backend",
)
_SELECTED_MODEL_FIELDS = (
    "reasoning_model",
    "language_model",
    "transcription_model",
    "use_api_models",
)


def _hardware_facts(notes: List[str]) -> Dict[str, Any]:
    try:
        from api.core.runtime.hardware_capability_service import HardwareCapabilityService

        profile = HardwareCapabilityService().get_profile()
        return {name: getattr(profile, name, None) for name in _HARDWARE_FIELDS}
    except Exception as exc:
        notes.append(f"Hardware profile unavailable: {type(exc).__name__}")
        return {}


def _selected_model_facts(notes: List[str]) -> Dict[str, Any]:
    try:
        from api.core.preferences.preferences_io import load_preferences

        models = load_preferences().models
        return {name: getattr(models, name, None) for name in _SELECTED_MODEL_FIELDS}
    except Exception as exc:
        notes.append(f"Selected models unavailable: {type(exc).__name__}")
        return {}


def _installed_model_ids(model_service: Any, notes: List[str]) -> List[str]:
    try:
        installed = model_service.model_downloader.get_installed_models()
        ids: List[str] = []
        for model_type in installed.values():
            for variant in model_type.get("variants", {}).values():
                model_id = variant.get("model_id")
                if model_id:
                    ids.append(str(model_id))
        return ids
    except Exception as exc:
        notes.append(f"Installed models unavailable: {type(exc).__name__}")
        return []


def _local_model_plan(model_service: Any, reasoning_model: Optional[str], hardware: Dict[str, Any], notes: List[str]) -> Optional[Dict[str, Any]]:
    """How Basil would load the selected local llama.cpp model on this Mac. None for a cloud, MLX or unselected model."""
    if not reasoning_model:
        return None
    try:
        from api.core.models.models_registry import get_model
        from api.core.runtime.hardware_capability_service import HardwareCapabilityService
        from api.core.runtime.llama_cpp_load_plan import build_llama_cpp_load_plan
        from api.core.runtime.llama_cpp_memory_budget import read_model_memory_facts

        entry = get_model(reasoning_model)
        if not entry or entry.get("location") != "local":
            return None
        path = Path(model_service.model_downloader._get_model_path_for_id(reasoning_model))
        if path.suffix.lower() != ".gguf" or not path.is_file():
            return {"model_id": reasoning_model, "runtime": "not a llama.cpp file or not installed"}
        facts = read_model_memory_facts(path)
        plan = build_llama_cpp_load_plan(
            hardware_profile=HardwareCapabilityService().get_profile(),
            registry_config=entry,
            gguf_context_window=entry.get("context_window"),
            model_bytes=facts.model_bytes,
            kv_bytes_per_token=facts.kv_bytes_per_token,
        )
        return {
            "model_id": reasoning_model,
            "model_file_gb": round(facts.model_bytes / (1024 ** 3), 2),
            "kv_bytes_per_token": facts.kv_bytes_per_token,
            "registry_context_window": entry.get("context_window"),
            "planned_n_ctx": plan.n_ctx,
            "n_gpu_layers": plan.n_gpu_layers,
            "prompt_cache_bytes": plan.prompt_cache_bytes,
            "fallback_reasons": list(plan.fallback_reasons),
        }
    except Exception as exc:
        notes.append(f"Load plan unavailable: {type(exc).__name__}")
        return None


def collect_problem_report_facts(
    model_service: Any,
    source: Optional[str],
    detail: Optional[str],
    app_version: Optional[str],
    macos_version: Optional[str],
) -> ProblemReportFacts:
    """Collect every fact the bundle reports. A fact that cannot be read is skipped and noted, so the report is still produced."""
    notes: List[str] = []
    hardware = _hardware_facts(notes)
    selected = _selected_model_facts(notes)
    return ProblemReportFacts(
        source=sanitize_source(source),
        detail=sanitize_detail(detail),
        app_version=sanitize_detail(app_version)[:40],
        macos_version=sanitize_detail(macos_version)[:60],
        hardware=hardware,
        selected_models=selected,
        installed_model_ids=_installed_model_ids(model_service, notes),
        local_model_plan=_local_model_plan(model_service, selected.get("reasoning_model"), hardware, notes),
        collection_notes=notes,
    )
