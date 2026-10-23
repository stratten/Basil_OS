"""A compact record of how the Companion was configured when a session started, saved on the timeline so meetings can be compared fairly after a setting, model or prompt has changed."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from typing import Any, Dict

from .audit import AUDIT_RULES
from .evaluator import DEFAULT_CONFIDENCE_FLOOR, QUESTION_CONFIDENCE_FLOOR
from .gate import GateConfig
from .models import CompanionSettings
from .prompts import FOCUS_HEADING, RULES, TRIGGER_DESCRIPTIONS

HASH_CHARS = 12


def prompt_hash() -> str:
    """A short digest of every prompt text that shapes what the Companion says, so any wording change shows up as a different value."""
    parts = [RULES, FOCUS_HEADING, AUDIT_RULES]
    parts.extend(f"{name}={text}" for name, text in sorted(TRIGGER_DESCRIPTIONS.items()))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:HASH_CHARS]


def build_run_payload(settings: CompanionSettings, gate_config: GateConfig) -> Dict[str, Any]:
    """The payload of the ``run`` timeline event: the settings, thresholds and prompt digest in force when the session started."""
    return {
        "mode": settings.mode,
        "model_id": settings.model_id,
        "investigate": settings.investigate,
        "has_focus": bool(settings.focus.strip()),
        "confidence_floor": DEFAULT_CONFIDENCE_FLOOR,
        "question_confidence_floor": QUESTION_CONFIDENCE_FLOOR,
        "gate": asdict(gate_config),
        "prompt_hash": prompt_hash(),
    }
