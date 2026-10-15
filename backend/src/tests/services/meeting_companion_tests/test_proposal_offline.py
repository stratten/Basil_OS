import asyncio

import pytest

from api.services.meeting_companion import offline
from api.services.meeting_companion import store as store_module
from api.services.meeting_companion.models import CompanionItem, CompanionSettings, ProposalInfo, TimelineEvent, TranscriptRange
from api.services.meeting_companion.proposals import ProposalLaunchError, ProposalNotFound, ProposalRejected
from api.services.meeting_companion.store import CompanionDocument, CompanionStore

from .proposal_fakes import FakeLauncher


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "meetings_root", lambda: tmp_path)
    return tmp_path


def proposal_event(seq, item_id, action="todo", title="Add a renewal reminder"):
    item = CompanionItem(
        id=item_id,
        kind="proposal",
        text=title,
        confidence=0.9,
        transcript_range=TranscriptRange(start=1.0, end=2.0, turn_ids=[]),
        trigger="investigation",
        researched=True,
        proposal=ProposalInfo(proposal_id=f"pr-{item_id}", action=action, title=title, instruction=f"Please {title.lower()} now"),
    )
    return TimelineEvent(id=f"e{seq}", seq=seq, kind="item", meeting_time=2.0, wall_time="w", payload={"item": item.model_dump(mode="json")})


def save(home, events, meeting_id="m1"):
    directory = home / meeting_id
    directory.mkdir(parents=True, exist_ok=True)
    CompanionStore(directory).save(CompanionDocument(session_key=meeting_id, settings=CompanionSettings(enabled=True), events=events, saved_at="w"))


def states(meeting_id="m1"):
    return {item.id: item.proposal.state for item in offline.load_stored_snapshot(meeting_id).items}


@pytest.mark.asyncio
async def test_approving_in_a_finished_meeting_starts_the_action_and_saves_the_outcome(home):
    save(home, [proposal_event(1, "i1")])
    launcher = FakeLauncher()
    outcome = await offline.decide_stored_proposal("m1", "i1", "approve", launcher)
    assert outcome.state == "started" and outcome.todo_id == "todo-1"
    assert launcher.created[0]["session_key"] == "m1" and launcher.created[0]["proposal_id"] == "pr-i1"
    snapshot = offline.load_stored_snapshot("m1")
    assert snapshot.items[0].proposal.state == "started" and snapshot.items[0].proposal.todo_id == "todo-1" and snapshot.last_seq == 2


@pytest.mark.asyncio
async def test_dismissing_in_a_finished_meeting_is_saved_and_blocks_a_later_approval(home):
    save(home, [proposal_event(1, "i1")])
    await offline.decide_stored_proposal("m1", "i1", "dismiss", FakeLauncher())
    snapshot = offline.load_stored_snapshot("m1")
    assert snapshot.items[0].dismissed is True and snapshot.items[0].proposal.state == "dismissed"
    with pytest.raises(ProposalRejected, match="dismissed"):
        await offline.decide_stored_proposal("m1", "i1", "approve", FakeLauncher())


@pytest.mark.asyncio
async def test_nothing_saved_unknown_items_and_repeats_are_reported(home):
    (home / "m2").mkdir()
    assert await offline.decide_stored_proposal("m2", "i1", "approve", FakeLauncher()) is None
    save(home, [proposal_event(1, "i1")])
    with pytest.raises(ProposalNotFound):
        await offline.decide_stored_proposal("m1", "nope", "approve", FakeLauncher())
    await offline.decide_stored_proposal("m1", "i1", "approve", FakeLauncher())
    with pytest.raises(ProposalRejected, match="already started"):
        await offline.decide_stored_proposal("m1", "i1", "approve", FakeLauncher())
    assert states() == {"i1": "started"}


@pytest.mark.asyncio
async def test_a_failed_start_is_saved_and_a_retry_repeats_only_the_failed_step(home):
    save(home, [proposal_event(1, "i1", action="agent_task")])
    launcher = FakeLauncher()
    launcher.launch_error = ProposalLaunchError("The To-Do worker is not ready yet. Try again in a moment.")
    failed = await offline.decide_stored_proposal("m1", "i1", "approve", launcher)
    assert failed.state == "failed" and states() == {"i1": "failed"}
    assert offline.load_stored_snapshot("m1").items[0].proposal.todo_id == "todo-1"
    launcher.launch_error = None
    retried = await offline.decide_stored_proposal("m1", "i1", "approve", launcher)
    assert retried.state == "started" and retried.todo_id == "todo-1" and retried.agent_task_id == "task-1"
    assert len(launcher.created) == 1 and launcher.launched == ["todo-1"]


@pytest.mark.asyncio
async def test_two_decisions_at_once_both_survive_in_the_saved_file(home):
    save(home, [proposal_event(1, "i1"), proposal_event(2, "i2", action="todo", title="Schedule security review")])
    launcher = FakeLauncher()
    launcher.gate = asyncio.Event()
    first = asyncio.ensure_future(offline.decide_stored_proposal("m1", "i1", "approve", launcher))
    second = asyncio.ensure_future(offline.decide_stored_proposal("m1", "i2", "approve", launcher))
    await asyncio.sleep(0.05)
    launcher.gate.set()
    await asyncio.gather(first, second)
    assert states() == {"i1": "started", "i2": "started"}


@pytest.mark.asyncio
async def test_feedback_and_a_decision_do_not_overwrite_each_other(home):
    save(home, [proposal_event(1, "i1")])
    await offline.decide_stored_proposal("m1", "i1", "approve", FakeLauncher())
    assert offline.record_stored_feedback("m1", "i1", "pinned") is True
    snapshot = offline.load_stored_snapshot("m1")
    assert snapshot.items[0].pinned is True and snapshot.items[0].proposal.state == "started"
