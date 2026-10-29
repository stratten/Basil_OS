"""Deterministic trigger gate: decides when the Companion should evaluate, never what it says."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, FrozenSet, List, Literal, Optional, Sequence, Tuple

from .models import CompanionMode, CompanionTurn, CompanionWatch
from .similarity import content_tokens, is_backchannel, jaccard, looks_like_question

TriggerName = Literal["question", "topic_shift", "periodic", "watch"]
ALL_TRIGGERS: FrozenSet[str] = frozenset({"question", "topic_shift", "periodic", "watch"})
DEFERRED_TRIGGERS: FrozenSet[str] = frozenset({"question", "watch"})
_NEVER = float("-inf")


@dataclass(frozen=True)
class GateConfig:
    min_new_turns: int = 3
    min_seconds_between_evaluations: float = 5.0
    question_cooldown: float = 10.0
    topic_shift_cooldown: float = 45.0
    periodic_cooldown: float = 90.0
    first_periodic_delay: float = 45.0
    watch_cooldown: float = 120.0
    ttl_seconds: float = 60.0
    topic_shift_threshold: float = 0.12
    min_topic_tokens: int = 4
    baseline_turns: int = 6
    min_baseline_turns: int = 3
    history_limit: int = 80


@dataclass(frozen=True)
class GateDecision:
    fire: bool
    trigger: Optional[TriggerName] = None
    new_turns: Tuple[CompanionTurn, ...] = ()
    watch: Optional[CompanionWatch] = None
    reason: str = ""


def light_stem(token: str) -> str:
    """Tiny suffix stripper so billing/bills/billed and invoice/invoices compare equal."""
    for suffix in ("ing", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    if len(token) > 5 and token.endswith("e"):
        return token[:-1]
    return token


def watch_matches(watch: CompanionWatch, turns: Sequence[CompanionTurn]) -> bool:
    """True when at least half of the watch keywords (stemmed) appear in the given turns."""
    keywords = {light_stem(keyword.lower()) for keyword in watch.keywords if keyword}
    if not keywords:
        return False
    seen = {light_stem(token) for turn in turns for token in content_tokens(turn.text)}
    return len(keywords & seen) >= max(1, math.ceil(len(keywords) / 2))


def keywords_from_topic(topic: str, limit: int = 6) -> List[str]:
    """Searchable keywords for a watch topic: its content words, alphabetical, at most ``limit``."""
    return sorted(content_tokens(topic))[:limit]


class Gate:
    def __init__(self, config: Optional[GateConfig] = None) -> None:
        self.config = config or GateConfig()
        self._pending: List[Tuple[float, CompanionTurn]] = []
        self._history: Deque[CompanionTurn] = deque(maxlen=self.config.history_limit)
        self._first_arrival_at: Optional[float] = None
        self._last_evaluation_at: Optional[float] = None
        self._last_trigger_at: Dict[str, float] = {}
        self._watch_last_at: Dict[str, float] = {}

    def add_turn(self, turn: CompanionTurn, now: float) -> None:
        if self._first_arrival_at is None:
            self._first_arrival_at = now
        self._pending.append((now, turn))

    def seed_history(self, turn: CompanionTurn) -> None:
        """Add an already-spoken line as context only; it can never trigger an evaluation."""
        self._history.append(turn)

    def pending_count(self) -> int:
        return len(self._pending)

    def window(self, window_seconds: float = 90.0, max_turns: int = 40) -> List[CompanionTurn]:
        """The most recent turns (evaluated and pending) within ``window_seconds`` of the latest line, oldest first."""
        turns = list(self._history) + [turn for _arrival, turn in self._pending]
        if not turns:
            return []
        turns.sort(key=lambda turn: (turn.start, turn.id))
        latest = max(turn.end for turn in turns)
        recent = [turn for turn in turns if turn.end >= latest - window_seconds]
        return recent[-max_turns:]

    def decide(
        self,
        now: float,
        *,
        mode: CompanionMode,
        watches: Sequence[CompanionWatch],
        allowed: FrozenSet[str],
    ) -> GateDecision:
        self._expire(now)
        if not self._pending:
            return GateDecision(False, reason="idle")
        if not allowed:
            return GateDecision(False, reason="capacity")
        turns = tuple(turn for _arrival, turn in self._pending)
        substantive = [turn for turn in turns if not is_backchannel(turn.text)]
        if not substantive:
            return GateDecision(False, reason="backchannel")
        if (
            self._last_evaluation_at is not None
            and now - self._last_evaluation_at < self.config.min_seconds_between_evaluations
        ):
            return GateDecision(False, reason="pacing")
        if "watch" in allowed:
            for watch in watches:
                if not watch.active:
                    continue
                if now - self._watch_last_at.get(watch.id, _NEVER) < self.config.watch_cooldown:
                    continue
                if watch_matches(watch, substantive):
                    return GateDecision(True, "watch", turns, watch, f"watch {watch.id}")
        if "question" in allowed and now - self._last_trigger_at.get("question", _NEVER) >= self.config.question_cooldown:
            if any(looks_like_question(turn.text) for turn in substantive[-3:]):
                return GateDecision(True, "question", turns, None, "question")
        if mode != "active":
            return GateDecision(False, reason="passive")
        if len(substantive) < self.config.min_new_turns:
            return GateDecision(False, reason="few lines")
        if "topic_shift" in allowed and now - self._last_trigger_at.get("topic_shift", _NEVER) >= self.config.topic_shift_cooldown:
            if self._topic_shifted(substantive):
                return GateDecision(True, "topic_shift", turns, None, "topic shift")
        if "periodic" in allowed and self._periodic_due(now):
            return GateDecision(True, "periodic", turns, None, "periodic")
        return GateDecision(False, reason="waiting")

    def commit(self, decision: GateDecision, now: float) -> None:
        """Record that an evaluation for ``decision`` started: pending lines move to history and cooldowns restart."""
        moved = sorted((turn for _arrival, turn in self._pending), key=lambda turn: (turn.start, turn.id))
        self._history.extend(moved)
        self._pending = []
        self._last_evaluation_at = now
        if decision.trigger is not None:
            self._last_trigger_at[decision.trigger] = now
        if decision.watch is not None:
            self._watch_last_at[decision.watch.id] = now

    def _expire(self, now: float) -> None:
        if not self._pending:
            return
        fresh: List[Tuple[float, CompanionTurn]] = []
        expired: List[CompanionTurn] = []
        for arrival, turn in self._pending:
            if now - arrival > self.config.ttl_seconds:
                expired.append(turn)
            else:
                fresh.append((arrival, turn))
        if expired:
            self._history.extend(sorted(expired, key=lambda turn: (turn.start, turn.id)))
            self._pending = fresh

    def _periodic_due(self, now: float) -> bool:
        if self._last_evaluation_at is not None:
            return now - self._last_evaluation_at >= self.config.periodic_cooldown
        if self._first_arrival_at is None:
            return False
        return now - self._first_arrival_at >= self.config.first_periodic_delay

    def _topic_shifted(self, substantive: Sequence[CompanionTurn]) -> bool:
        baseline = list(self._history)[-self.config.baseline_turns :]
        if len(baseline) < self.config.min_baseline_turns:
            return False
        new_tokens = set().union(*(content_tokens(turn.text) for turn in substantive))
        if len(new_tokens) < self.config.min_topic_tokens:
            return False
        baseline_tokens = set().union(*(content_tokens(turn.text) for turn in baseline))
        return jaccard(new_tokens, baseline_tokens) < self.config.topic_shift_threshold
