"""The evaluator's optional request to hand a question to the investigator."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from ..similarity import normalize_text
from .triggers import MIN_QUESTION_CHARS, normalize_question

MAX_REASON_CHARS = 120


class ResearchRequest(BaseModel):
    """A self-contained question the fast single-shot evaluation could not answer from the transcript and the pack."""

    model_config = ConfigDict(extra="forbid")

    question: str
    reason: str = ""


def honored_research(research: Optional[ResearchRequest], *, trigger: str, item_count: int, sourced_item_count: int = 0) -> Optional[ResearchRequest]:
    """The research request, cleaned, for any trigger unless the evaluation already produced an item grounded in a source.

    An item with no source (a note or answer from the conversation alone) can sit beside a request to check the user's files, so a vague note is not the end of the matter. ``trigger`` and ``item_count`` are kept for the record; the rule depends on ``sourced_item_count`` only. The investigation itself still passes every guard: the per-meeting switch, the run cap, duplicate questions, capacity and concurrency.
    """
    if research is None or sourced_item_count > 0:
        return None
    question = normalize_question(research.question)
    if len(question) < MIN_QUESTION_CHARS:
        return None
    return ResearchRequest(question=question, reason=normalize_text(research.reason)[:MAX_REASON_CHARS])
