"""The evaluator's optional request to hand a question to the investigator."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from ..similarity import normalize_text
from .triggers import MIN_QUESTION_CHARS, normalize_question

RESEARCH_TRIGGERS = ("question", "watch")
MAX_REASON_CHARS = 120


class ResearchRequest(BaseModel):
    """A self-contained question the fast single-shot evaluation could not answer from the transcript and the pack."""

    model_config = ConfigDict(extra="forbid")

    question: str
    reason: str = ""


def honored_research(research: Optional[ResearchRequest], *, trigger: str, item_count: int) -> Optional[ResearchRequest]:
    """The research request, cleaned, only for a question or watch trigger that produced no item."""
    if research is None or item_count > 0 or trigger not in RESEARCH_TRIGGERS:
        return None
    question = normalize_question(research.question)
    if len(question) < MIN_QUESTION_CHARS:
        return None
    return ResearchRequest(question=question, reason=normalize_text(research.reason)[:MAX_REASON_CHARS])
