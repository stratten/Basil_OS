"""Per-schedule chain settings: whether each run starts its own task or continues one conversation, and when that conversation rolls over."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

CHAIN_MODE_INDEPENDENT = "independent"
CHAIN_MODE_CHAINED = "chained"
MAX_CHAIN_RUNS_LIMIT = 1000
MAX_CHAIN_AGE_MINUTES_LIMIT = 60 * 24 * 366


@dataclass(frozen=True)
class ChainConfig:
    """What the runner needs to know about a schedule's chain."""

    mode: str = CHAIN_MODE_INDEPENDENT
    max_runs: Optional[int] = None  # Stored under this name for compatibility; it limits the total turns in the conversation, not only scheduled runs.
    max_age_minutes: Optional[int] = None
    carry_over: bool = True
    carry_checklist: bool = False  # Applies to independent and chained schedules: open checklist items (and notes) of the previous run seed the next run.

    @property
    def is_chained(self) -> bool:
        return self.mode == CHAIN_MODE_CHAINED


def _optional_limit(raw: Any, label: str, upper: int) -> Optional[int]:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool) or (isinstance(raw, float) and not raw.is_integer()):
        raise ValueError(f"{label} must be a whole number.")
    try:
        number = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a whole number.") from None
    if number < 1 or number > upper:
        raise ValueError(f"{label} must be between 1 and {upper}.")
    return number


def normalize_chain_config(raw: Any) -> Dict[str, Any]:
    """Validate a chain config from an API caller and return it in canonical form; raises ValueError with a plain message."""
    if raw is None:
        return {"mode": CHAIN_MODE_INDEPENDENT}
    if not isinstance(raw, dict):
        raise ValueError("chain_config must be an object.")
    mode = str(raw.get("mode") or CHAIN_MODE_INDEPENDENT).strip().lower()
    if mode not in (CHAIN_MODE_INDEPENDENT, CHAIN_MODE_CHAINED):
        raise ValueError("The chain mode must be independent or chained.")
    carry_checklist = raw.get("carry_checklist", False)
    if not isinstance(carry_checklist, bool):
        raise ValueError("carry_checklist must be true or false.")
    if mode == CHAIN_MODE_INDEPENDENT:
        independent: Dict[str, Any] = {"mode": CHAIN_MODE_INDEPENDENT}
        if carry_checklist:
            independent["carry_checklist"] = True
        return independent
    max_runs = _optional_limit(raw.get("max_runs"), "The turn limit", MAX_CHAIN_RUNS_LIMIT)
    max_age = _optional_limit(raw.get("max_age_minutes"), "The time limit", MAX_CHAIN_AGE_MINUTES_LIMIT)
    if max_runs is None and max_age is None:
        raise ValueError("A chained schedule needs a turn limit, a time limit, or both, so one conversation cannot grow without end.")
    carry_over = raw.get("carry_over", True)
    if not isinstance(carry_over, bool):
        raise ValueError("carry_over must be true or false.")
    config: Dict[str, Any] = {"mode": CHAIN_MODE_CHAINED, "carry_over": carry_over}
    if max_runs is not None:
        config["max_runs"] = max_runs
    if max_age is not None:
        config["max_age_minutes"] = max_age
    if carry_checklist:
        config["carry_checklist"] = True
    return config


def parse_chain_config(raw: Any) -> ChainConfig:
    """Lenient reader for stored values: anything unusable means independent runs, so a bad row never blocks a schedule."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else None
        except ValueError:
            raw = None
    try:
        normalized = normalize_chain_config(raw)
    except ValueError:
        return ChainConfig()
    carry_checklist = bool(normalized.get("carry_checklist", False))
    if normalized["mode"] != CHAIN_MODE_CHAINED:
        return ChainConfig(carry_checklist=carry_checklist)
    return ChainConfig(
        mode=CHAIN_MODE_CHAINED,
        max_runs=normalized.get("max_runs"),
        max_age_minutes=normalized.get("max_age_minutes"),
        carry_over=bool(normalized.get("carry_over", True)),
        carry_checklist=carry_checklist,
    )
