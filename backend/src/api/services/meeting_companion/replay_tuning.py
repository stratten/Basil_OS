"""The tuning candidates from the Companion plan, expressed so a replay can try each one without editing the shipped defaults.

Nothing here changes behavior in the app. A candidate is applied only inside ``applied`` while a replay runs, and a candidate becomes a shipped default only by a deliberate edit after ``improves`` says it helped on a meeting with marked audit findings.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, replace
from typing import Dict, Iterator, Optional

from . import evaluator as evaluator_module
from . import prompts as prompts_module
from .gate import GateConfig

ORIGINAL_RULE_ONE = "1. Silence is the default. If nothing is clearly useful right now, return an empty items list. A wrong or repetitive note is worse than no note."
SOFTENED_RULE_ONE = (
    "1. Prefer silence over a weak note, but do not stay silent when a decision was made, someone committed to a follow-up, "
    "a risk or contradiction came up, or a question went unanswered: those deserve a short note. A wrong or repetitive note is worse than no note."
)


@dataclass(frozen=True)
class Candidate:
    name: str
    description: str
    gate: Dict[str, float]
    periodic_floor: Optional[float] = None
    softened_prompt: bool = False


CANDIDATES: Dict[str, Candidate] = {
    "floor-0.5": Candidate("floor-0.5", "Confidence floor for unprompted notes 0.6 to 0.5", {}, periodic_floor=0.5),
    "min-turns-2": Candidate("min-turns-2", "Gate needs 2 new lines instead of 3", {"min_new_turns": 2}),
    "ttl-120": Candidate("ttl-120", "Pending lines stay eligible for 120 s instead of 60 s", {"ttl_seconds": 120.0}),
    "periodic-60": Candidate("periodic-60", "Periodic check every 60 s instead of 90 s", {"periodic_cooldown": 60.0}),
    "soften-silence": Candidate("soften-silence", "Rule 1 names decisions, commitments, risks and unanswered questions as worth a note", {}, softened_prompt=True),
}


def candidate_names() -> list:
    return list(CANDIDATES) + ["all"]


def resolve(name: str) -> Candidate:
    """One named candidate, or ``all`` for every candidate at once."""
    if name == "all":
        gate: Dict[str, float] = {}
        for candidate in CANDIDATES.values():
            gate.update(candidate.gate)
        return Candidate("all", "Every candidate together", gate, periodic_floor=0.5, softened_prompt=True)
    if name not in CANDIDATES:
        raise ValueError(f"Unknown candidate {name!r}; choose from {', '.join(candidate_names())}")
    return CANDIDATES[name]


def gate_config_for(candidate: Optional[Candidate]) -> GateConfig:
    base = GateConfig()
    return replace(base, **candidate.gate) if candidate is not None and candidate.gate else base


@contextlib.contextmanager
def applied(candidate: Optional[Candidate]) -> Iterator[None]:
    """Run a replay with the candidate's confidence floor and prompt wording in place, then restore the shipped values."""
    saved_floor = evaluator_module.DEFAULT_CONFIDENCE_FLOOR
    saved_rules = prompts_module.RULES
    try:
        if candidate is not None:
            if candidate.periodic_floor is not None:
                evaluator_module.DEFAULT_CONFIDENCE_FLOOR = candidate.periodic_floor
            if candidate.softened_prompt:
                if saved_rules.count(ORIGINAL_RULE_ONE) != 1:
                    raise RuntimeError("Rule 1 of the evaluation prompt changed; update ORIGINAL_RULE_ONE before testing the softened prompt.")
                prompts_module.RULES = saved_rules.replace(ORIGINAL_RULE_ONE, SOFTENED_RULE_ONE)
        yield
    finally:
        evaluator_module.DEFAULT_CONFIDENCE_FLOOR = saved_floor
        prompts_module.RULES = saved_rules
