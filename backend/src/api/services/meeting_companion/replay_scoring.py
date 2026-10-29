"""Scores what a replay produced against the audit findings the user marked, so a tuning change is judged on evidence.

An agreed finding ("Good catch") is a moment the Companion should have spoken at. A disagreed one ("Not needed") is a moment where silence was right. Replay output is judged on how many agreed moments it covers, how many disagreed moments it spoke at anyway, and how many notes landed on neither.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from .models import AuditMoment, CompanionItem
from .similarity import content_tokens, jaccard

MATCH_SLACK_SECONDS = 30.0
MATCH_TEXT_SIMILARITY = 0.4


@dataclass
class ReplayScore:
    agreed_total: int = 0
    agreed_matched: int = 0
    disagreed_total: int = 0
    disagreed_hit: int = 0
    items: int = 0
    unmatched_items: int = 0
    matched_moment_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def _near(item: CompanionItem, moment: AuditMoment) -> bool:
    start, end = item.transcript_range.start, item.transcript_range.end
    return start <= moment.end + MATCH_SLACK_SECONDS and end >= moment.start - MATCH_SLACK_SECONDS


def covers(item: CompanionItem, moment: AuditMoment) -> bool:
    """A note covers a finding when it is about the same moment and either says something similar or sits right on it."""
    if not _near(item, moment):
        return False
    overlap = jaccard(content_tokens(item.text), content_tokens(moment.suggested_text)) >= MATCH_TEXT_SIMILARITY
    on_it = item.transcript_range.start <= moment.end and item.transcript_range.end >= moment.start
    return overlap or on_it


def score_replay(items: Sequence[CompanionItem], moments: Sequence[AuditMoment]) -> ReplayScore:
    """Compare replayed notes with the marked findings; unmarked findings are ignored because the user has not judged them."""
    agreed = [moment for moment in moments if moment.mark == "agree"]
    disagreed = [moment for moment in moments if moment.mark == "disagree"]
    visible = [item for item in items if item.kind != "proposal"]
    matched = [moment for moment in agreed if any(covers(item, moment) for item in visible)]
    hit = [moment for moment in disagreed if any(_near(item, moment) for item in visible)]
    unmatched = [item for item in visible if not any(covers(item, moment) for moment in agreed) and not any(_near(item, moment) for moment in disagreed)]
    return ReplayScore(
        agreed_total=len(agreed),
        agreed_matched=len(matched),
        disagreed_total=len(disagreed),
        disagreed_hit=len(hit),
        items=len(visible),
        unmatched_items=len(unmatched),
        matched_moment_ids=[moment.id for moment in matched],
    )


def improves(baseline: ReplayScore, candidate: ReplayScore) -> bool:
    """The plan's rule for applying a tuning change: more agreed moments covered, and no more notes where the user said silence was right."""
    return candidate.agreed_matched > baseline.agreed_matched and candidate.disagreed_hit <= baseline.disagreed_hit
