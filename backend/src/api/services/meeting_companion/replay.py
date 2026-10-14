"""Offline replay of a saved transcript through the Companion engine on a virtual clock."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from .context_pack import ContextPack
from .conversation_state import ConversationState
from .evaluator import EvaluationOutcome, EvaluationRequest
from .gate import ALL_TRIGGERS, Gate, GateConfig
from .models import CompanionItem, CompanionMode, CompanionTurn, CompanionWatch
from .utterances import UtteranceAssembler

SELF_SPEAKERS = frozenset({"microphone", "you", "me"})

Evaluate = Callable[[EvaluationRequest], Awaitable[EvaluationOutcome]]
ContextLookup = Callable[[str], Awaitable[Optional[ContextPack]]]


@dataclass
class ReplayStep:
    time: float
    trigger: str
    reason: str
    new_turn_ids: List[str]
    item_count: int = 0
    latency_ms: int = 0
    error: Optional[str] = None


@dataclass
class ReplayReport:
    turn_count: int = 0
    seconds_covered: float = 0.0
    steps: List[ReplayStep] = field(default_factory=list)
    items: List[CompanionItem] = field(default_factory=list)

    @property
    def trigger_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for step in self.steps:
            counts[step.trigger] = counts.get(step.trigger, 0) + 1
        return counts

    @property
    def error_count(self) -> int:
        return sum(1 for step in self.steps if step.error)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_count": self.turn_count,
            "seconds_covered": round(self.seconds_covered, 1),
            "trigger_counts": self.trigger_counts,
            "error_count": self.error_count,
            "steps": [step.__dict__ for step in self.steps],
            "items": [item.model_dump(mode="json") for item in self.items],
        }


def segments_to_turns(
    segments: Sequence[Dict[str, Any]],
    *,
    source_meeting_id: str = "replay",
    id_prefix: str = "r-",
) -> List[CompanionTurn]:
    """Assemble saved fragments into utterances the same way the live tap does, one assembler per speaker label."""
    usable = [
        segment
        for segment in segments
        if not segment.get("is_interim") and str(segment.get("text") or "").strip()
    ]
    usable.sort(key=lambda segment: (float(segment["start"]), float(segment["end"])))
    assemblers: Dict[str, UtteranceAssembler] = {}
    turns: List[CompanionTurn] = []
    for segment in usable:
        speaker = str(segment.get("speaker") or "Speaker")
        assembler = assemblers.get(speaker)
        if assembler is None:
            assembler = UtteranceAssembler(
                source_meeting_id=source_meeting_id,
                role="self" if speaker.lower() in SELF_SPEAKERS else "other",
                default_speaker=speaker,
                id_prefix=f"{id_prefix}{len(assemblers) + 1}-",
            )
            assemblers[speaker] = assembler
        now = float(segment["end"])
        for candidate in assemblers.values():
            turns.extend(candidate.flush_idle(now))
        turns.extend(
            assembler.add_fragment(
                start=float(segment["start"]),
                end=float(segment["end"]),
                text=str(segment["text"]),
                speaker=speaker,
                now_wall=now,
            )
        )
    for assembler in assemblers.values():
        turns.extend(assembler.flush_all())
    turns.sort(key=lambda turn: (turn.start, turn.id))
    return turns


async def replay(
    turns: Sequence[CompanionTurn],
    *,
    mode: CompanionMode = "active",
    watches: Sequence[CompanionWatch] = (),
    gate_config: Optional[GateConfig] = None,
    evaluate: Optional[Evaluate] = None,
    context_lookup: Optional[ContextLookup] = None,
    tick_seconds: float = 1.0,
    assumed_latency_seconds: float = 0.0,
    window_seconds: float = 90.0,
    model_id: Optional[str] = None,
) -> ReplayReport:
    """Run the gate (and optionally the evaluator) over ``turns`` on a virtual clock advanced by ``tick_seconds``."""
    report = ReplayReport(turn_count=len(turns))
    if not turns:
        return report
    ordered = sorted(turns, key=lambda turn: (turn.end, turn.id))
    report.seconds_covered = ordered[-1].end - ordered[0].start
    gate = Gate(gate_config)
    state = ConversationState()
    shown: List[str] = []
    index = 0
    now = ordered[0].end
    end_time = ordered[-1].end + 2 * tick_seconds
    while now <= end_time:
        while index < len(ordered) and ordered[index].end <= now:
            gate.add_turn(ordered[index], now)
            index += 1
        decision = gate.decide(now, mode=mode, watches=list(watches), allowed=ALL_TRIGGERS)
        if decision.fire and decision.trigger is not None:
            gate.commit(decision, now)
            step = ReplayStep(
                time=now,
                trigger=decision.trigger,
                reason=decision.reason,
                new_turn_ids=[turn.id for turn in decision.new_turns],
            )
            if evaluate is not None:
                pack = None
                if context_lookup is not None:
                    pack = await context_lookup(" ".join(turn.text for turn in decision.new_turns))
                outcome = await evaluate(
                    EvaluationRequest(
                        trigger=decision.trigger,
                        mode=mode,
                        meeting_time=now,
                        new_turns=list(decision.new_turns),
                        window_turns=gate.window(window_seconds),
                        conversation_state=state.text,
                        already_shown=list(shown),
                        pack=pack,
                        has_roots=context_lookup is not None,
                        watch=decision.watch,
                        model_id=model_id,
                    )
                )
                step.item_count = len(outcome.items)
                step.latency_ms = outcome.latency_ms
                step.error = outcome.error
                if outcome.conversation_state:
                    state.apply(outcome.conversation_state, now)
                for item in outcome.items:
                    report.items.append(item)
                    shown.append(item.text)
            report.steps.append(step)
            now += max(0.0, assumed_latency_seconds)
        now += tick_seconds
    return report


def format_report(report: ReplayReport) -> str:
    """Human-readable summary for the CLI."""
    lines = [
        f"turns: {report.turn_count}",
        f"covered: {report.seconds_covered:.0f}s",
        f"evaluations: {len(report.steps)} {report.trigger_counts}",
        f"items: {len(report.items)}",
        f"errors: {report.error_count}",
    ]
    for step in report.steps:
        minutes, seconds = divmod(int(step.time), 60)
        detail = f"items={step.item_count} latency={step.latency_ms}ms" if step.latency_ms or step.item_count else ""
        error = f" ERROR={step.error}" if step.error else ""
        lines.append(f"  {minutes:02d}:{seconds:02d} {step.trigger:<11} lines={len(step.new_turn_ids)} {detail}{error}".rstrip())
    return "\n".join(lines)
