import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from api.services.meeting_companion.capacity import CapacityAssessment
from api.services.meeting_companion.context_search import validate_root
from api.services.meeting_companion.context_service import ContextService
from api.services.meeting_companion.evaluator import EvaluationOutcome
from api.services.meeting_companion.models import CompanionItem, CompanionSettings, TranscriptRange
from api.services.meeting_companion.models import CompanionGlobalSettings
from api.services.meeting_companion.runtime import MeetingCompanionRuntime
from api.services.meeting_companion.session import CompanionSession
from api.services.meeting_companion.store import CompanionGlobalSettingsStore


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeGuard:
    def __init__(self) -> None:
        self.state = "ok"
        self.reason: Optional[str] = None
        self.lag = 0.0

    def assess(self, now: float) -> CapacityAssessment:
        return CapacityAssessment(self.state, self.reason, self.lag)


class FakeEvaluator:
    """Scripted evaluator: records requests and returns a default answer item unless overridden."""

    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self.requests: List[Any] = []
        self.override: Optional[EvaluationOutcome] = None
        self.release: Optional[asyncio.Event] = None
        self.advance_during = 0.0
        self.raise_error: Optional[Exception] = None
        self.conversation_state = "Billing retries were discussed."

    async def model_for(self, model_id: Optional[str]) -> Any:
        return SimpleNamespace(model_id=model_id)

    def forget_model(self) -> None:
        return None

    async def evaluate(self, request: Any) -> EvaluationOutcome:
        self.requests.append(request)
        if self.raise_error is not None:
            raise self.raise_error
        if self.release is not None:
            await self.release.wait()
        self._clock.advance(self.advance_during)
        if self.override is not None:
            return self.override
        first, last = request.new_turns[0], request.new_turns[-1]
        item = CompanionItem(
            id=f"item-{len(self.requests)}",
            kind="answer",
            text="Default answer.",
            confidence=0.9,
            no_source=True,
            transcript_range=TranscriptRange(start=first.start, end=last.end, turn_ids=[turn.id for turn in request.new_turns]),
            trigger=request.trigger,
        )
        return EvaluationOutcome(items=[item], conversation_state=self.conversation_state)


class Harness:
    def __init__(self, tmp_path: Path, session: CompanionSession, clock: FakeClock, evaluator: FakeEvaluator, guard: FakeGuard, context: ContextService, broadcasts: List[Dict[str, Any]]) -> None:
        self.tmp_path = tmp_path
        self.session = session
        self.clock = clock
        self.evaluator = evaluator
        self.guard = guard
        self.context = context
        self.broadcasts = broadcasts

    def add_member(self, meeting_id: str = "mic1", *, role: str = "self", speaker: str = "Microphone", start_epoch: Optional[float] = 1000.0, existing: Any = ()) -> SimpleNamespace:
        directory = self.tmp_path / meeting_id
        directory.mkdir(parents=True, exist_ok=True)
        recorder = SimpleNamespace(meeting_id=meeting_id, meeting_dir=directory, transcript_segments=list(existing), transcription_lag_seconds=0.0)
        self.session.add_member(meeting_id=meeting_id, role=role, speaker=speaker, recorder=recorder, start_epoch=start_epoch, existing_segments=list(existing))
        return recorder

    def say(self, text: str, start: float, end: Optional[float] = None, *, meeting_id: str = "mic1", speaker: Optional[str] = None, interim: bool = False) -> None:
        self.session.on_segment(meeting_id, {"start": start, "end": end if end is not None else start + 3.0, "text": text, "speaker": speaker or "Microphone", "is_interim": interim})

    async def settle(self) -> None:
        await self.session.tick()
        await self.session.wait_idle()

    def event_kinds(self, kind: str) -> List[Any]:
        return [event for event in self.session.events() if event.kind == kind]


@pytest.fixture
def make_session(tmp_path):
    created: List[Harness] = []

    def factory(*, settings: Optional[CompanionSettings] = None, chat_service: Any = None, context: Optional[ContextService] = None, **extra: Any) -> Harness:
        clock = FakeClock()
        evaluator = FakeEvaluator(clock)
        guard = FakeGuard()
        broadcasts: List[Dict[str, Any]] = []

        async def broadcast(message: Dict[str, Any]) -> None:
            broadcasts.append(message)

        service = context or ContextService()
        session = CompanionSession(
            session_key="sess1",
            settings=settings or CompanionSettings(enabled=True),
            evaluator=evaluator,
            context=service,
            capacity_guard=guard,
            broadcast=broadcast,
            chat_service=chat_service,
            directory_resolver=lambda meeting_id: tmp_path / meeting_id,
            clock=clock,
            **extra,
        )
        harness = Harness(tmp_path, session, clock, evaluator, guard, service, broadcasts)
        created.append(harness)
        return harness

    yield factory


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "retry_policy.py").write_text("class RetryPolicy:\n    max_attempts = 5\n\n\ndef generate_invoice(customer):\n    return customer\n", encoding="utf-8")
    return root


@pytest.fixture
def attach_project():
    def attach(service: ContextService, root: Path, root_id: str = "r1") -> None:
        resolved, kind = validate_root(str(root), home=root.parent.parent)
        service.attach_root(root_id, resolved, kind, root.name)

    return attach


@pytest.fixture
def recorder_factory(tmp_path):
    def build(meeting_id: str, *, session_id: Optional[str] = None, audio_source: str = "Microphone", start_time: str = "2026-01-01T10:00:00.000000Z", existing: Any = ()) -> SimpleNamespace:
        directory = tmp_path / meeting_id
        directory.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            meeting_id=meeting_id,
            session_id=session_id,
            audio_source=audio_source,
            metadata=SimpleNamespace(start_time=start_time),
            meeting_dir=directory,
            transcript_segments=list(existing),
            transcription_lag_seconds=0.0,
        )

    return build


@pytest.fixture
def runtime_factory(tmp_path):
    def build(*, auto_enable: bool = False, default_mode: str = "active", chat_service: Any = None) -> SimpleNamespace:
        clock = FakeClock()
        evaluator = FakeEvaluator(clock)
        broadcasts: List[Dict[str, Any]] = []
        recorders: List[Any] = []
        store = CompanionGlobalSettingsStore(tmp_path / "global.json")
        store.save(CompanionGlobalSettings(auto_enable=auto_enable, default_mode=default_mode))

        async def broadcast(message: Dict[str, Any]) -> None:
            broadcasts.append(message)

        runtime = MeetingCompanionRuntime(
            global_store=store,
            evaluator=evaluator,
            chat_service=chat_service,
            broadcast=broadcast,
            directory_resolver=lambda meeting_id: tmp_path / meeting_id,
            recorders=lambda: list(recorders),
            clock=clock,
        )
        runtime.install(asyncio.get_running_loop(), register_listener=False)
        return SimpleNamespace(runtime=runtime, clock=clock, evaluator=evaluator, broadcasts=broadcasts, recorders=recorders, store=store, tmp_path=tmp_path)

    return build
